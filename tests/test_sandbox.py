import subprocess
import time
from pathlib import Path

import pytest

from clm_harness import sandbox
from clm_harness.cli import main
from clm_harness.config import Config
from clm_harness.loop import ModelReply, ScriptedModel, load_system, run, run_command
from clm_harness.sandbox import Sandbox, docker_status, exec_argv, run_argv
from clm_harness.shell import Shell


def _argv(cfg: Config, masked=()) -> list[str]:
    return run_argv("docker", "clm-x", cfg.sandbox_image, Path("/w"), Path("/s"), cfg,
                    [Path(m) for m in masked], Path("/s/state/empty"))


def test_container_is_locked_down_by_default():
    argv = _argv(Config(sandbox="docker"))
    joined = " ".join(argv)
    assert "--network none" in joined
    assert "--cap-drop ALL" in joined and "no-new-privileges" in joined
    assert "--memory 2g" in joined and "--pids-limit 512" in joined and "--cpus 2.0" in joined
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "--mount"]
    assert [m.rpartition("target=")[2] for m in mounts] == ["/work", "/session"]  # nothing else


def test_network_only_when_asked_for():
    assert "--network" not in _argv(Config(sandbox="docker", sandbox_network=True))


def test_container_ends_by_itself_after_the_run_limit():
    assert _argv(Config(sandbox="docker", max_wall_seconds=100))[-2:] == ["sleep", "1000"]


def test_dotenv_files_are_covered_by_an_empty_file():
    argv = _argv(Config(sandbox="docker"), masked=["/w/.env", "/w/.env.local"])
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "--mount"]
    assert mounts[2:] == [
        f"type=bind,source={Path('/s/state/empty')},target=/work/.env,readonly",
        f"type=bind,source={Path('/s/state/empty')},target=/work/.env.local,readonly",
    ]


def test_only_named_secret_variables_are_passed_in(monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "t")
    monkeypatch.setenv("OTHER_TOKEN", "o")
    argv = exec_argv("docker", "clm-x", "/session/state/run.sh", "/session/state/out-1.bin",
                     ("MY_TOKEN", "NOT_SET_ANYWHERE"))
    assert argv[:4] == ["docker", "exec", "-e", "MY_TOKEN"]
    assert "OTHER_TOKEN" not in argv and "NOT_SET_ANYWHERE" not in argv
    assert argv[-2:] == ["/session/state/run.sh", "/session/state/out-1.bin"]


def test_paths_map_into_the_container(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "find_docker", lambda: "docker")
    work, sess = tmp_path / "work dir", tmp_path / "work dir" / ".ctx" / "sessions" / "s1"
    sess.mkdir(parents=True)
    box = Sandbox(work, sess, Config(sandbox="docker"))
    assert box.path(work) == "/work"
    assert box.path(work / "src" / "a b.py") == "/work/src/a b.py"
    assert box.path(sess / "LIVE_CTX.md") == "/session/LIVE_CTX.md"  # the session wins
    with pytest.raises(ValueError):
        box.path(tmp_path / "elsewhere")


def test_a_path_with_a_comma_is_refused():
    with pytest.raises(RuntimeError, match="comma"):
        sandbox._mount(Path("/a,b"), "/work")


def test_config_rejects_an_unknown_sandbox():
    with pytest.raises(ValueError, match="sandbox"):
        Config(sandbox="chroot")


def test_system_prompt_describes_the_sandbox_and_stays_constant():
    off = load_system(Config(mode="baseline", sandbox="docker"))
    on = load_system(Config(mode="baseline", sandbox="docker", sandbox_network=True))
    assert "Linux container" in off and "no network access" in off and "Git Bash" not in off
    assert "The network is available" in on
    assert off == load_system(Config(mode="baseline", sandbox="docker"))
    assert "Linux container" not in load_system(Config(mode="baseline"))


def test_run_stops_before_spending_when_docker_is_unusable(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("clm_harness.cli._claude", lambda cfg: object())
    monkeypatch.setattr("clm_harness.sandbox.docker_status", lambda: (False, "engine is off"))
    assert main(["run", "do it", "--dir", str(tmp_path), "--sandbox", "docker"]) == 2
    assert "engine is off" in capsys.readouterr().err


# ---- with a real Docker engine ----------------------------------------------------

# Ends by itself after about a minute, so a failed kill or a failed test leaves nothing behind.
HEARTBEAT = "for i in $(seq 1 200); do date +%s%N > beat.txt; sleep 0.2; done"


@pytest.fixture(scope="module")
def docker_ready():
    usable, detail = docker_status(timeout=10)
    if not usable:
        pytest.skip(f"needs a Docker engine running Linux containers ({detail})")


@pytest.fixture
def boxed(docker_ready, workdir, session_dir):
    (workdir / ".env").write_text("DB_PASSWORD=hunter2hunter2\n", encoding="utf-8")
    shell = Shell(workdir, session_dir, Config(command_timeout=20, sandbox="docker"))
    yield shell
    shell.close()


def _containers(name: str) -> str:
    done = subprocess.run(["docker", "ps", "-a", "--filter", f"name={name}", "-q"],
                          capture_output=True, text=True, timeout=30)
    return done.stdout.strip()


def test_commands_run_in_the_container_and_see_only_the_project(boxed, workdir, tmp_path):
    (tmp_path / "outside.txt").write_text("host only", encoding="utf-8")
    result = boxed.run('uname -s; pwd; echo made > new.txt; ls ..; echo "[$CTX]"')
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[:2] == ["Linux", "/work"]
    assert "outside.txt" not in result.output and "sess dir" not in result.output
    assert lines[-1] == "[/session/LIVE_CTX.md]"
    assert (workdir / "new.txt").read_text().strip() == "made"


def test_state_carries_over_between_commands(boxed):
    boxed.run("mkdir -p sub && cd sub && export COLOUR=teal")
    assert boxed.run('pwd; echo "$COLOUR"').output.splitlines() == ["/work/sub", "teal"]
    boxed.reset()
    assert boxed.run('pwd; echo "[$COLOUR]"').output.splitlines() == ["/work", "[]"]


def test_dotenv_reads_as_empty(boxed):
    result = boxed.run("cat .env; wc -c < .env")
    assert "hunter2" not in result.output and result.output.split() == ["0"]


def test_no_network_and_no_host_secrets(boxed, monkeypatch):
    monkeypatch.setenv("SOME_API_KEY", "value-that-must-not-leak")
    script = ("import socket\ntry:\n socket.create_connection(('1.1.1.1', 53), 3); print('ONLINE')"
              "\nexcept OSError: print('OFFLINE')")
    result = boxed.run(f"python3 -c \"{script}\"; env | grep -c SOME_API_KEY")
    assert result.output.split() == ["OFFLINE", "0"]


def test_exit_code_and_background_job(boxed):
    assert boxed.run("exit 7").exit_code == 7
    started = time.monotonic()
    assert boxed.run("sleep 8 & echo started").output.strip() == "started"
    assert time.monotonic() - started < 6  # did not wait for the background job


def test_timeout_kills_everything_the_command_started(docker_ready, workdir, session_dir):
    shell = Shell(workdir, session_dir, Config(command_timeout=3, sandbox="docker"))
    try:
        result = shell.run(f"({HEARTBEAT}) & {HEARTBEAT}")
        assert result.timed_out and result.exit_code == -1
        time.sleep(1.0)
        first = (workdir / "beat.txt").read_text()
        time.sleep(1.5)
        assert (workdir / "beat.txt").read_text() == first  # both loops are dead
        assert shell.run("echo still usable").output.strip() == "still usable"
    finally:
        shell.close()


def test_runaway_output_is_killed(docker_ready, workdir, session_dir):
    cfg = Config(command_timeout=60, max_output_bytes=200_000, sandbox="docker")
    shell = Shell(workdir, session_dir, cfg)
    try:
        # Bounded: 40 MB at most, even if the kill fails.
        result = shell.run("for i in $(seq 1 400); do head -c 100000 /dev/zero | tr '\\0' a; done")
        assert result.output_limit and result.exit_code == -1 and result.seconds < 30
        assert shell.run("echo still usable").output.strip() == "still usable"
    finally:
        shell.close()


def test_scripting_tool_is_found_in_the_container(boxed):
    assert boxed.scripting_hint() == "`python3` and `re.sub`"


def test_a_whole_run_with_a_context_edit(docker_ready, workdir):
    # Replace the first block's body through "$CTX", as the model would.
    edit = ("perl -0pi -e 's/(\\[\\[BLOCK id=b0001 [^\\n]*\\n).*?(?=\\n\\n\\[\\[BLOCK|\\z)/${1}"
            "noted/s' \"$CTX\"")
    model = ScriptedModel([run_command("uname -s > os.txt; seq 1 300"), run_command(edit),
                           ModelReply(text="done")])
    result = run("t", workdir, Config(sandbox="docker"), model)
    assert result.status == "finished"
    assert (workdir / "os.txt").read_text().strip() == "Linux"
    transcript = (result.session_dir / "transcript.jsonl").read_text(encoding="utf-8")
    assert '"edit_applied"' in transcript and '"edit_refused"' not in transcript
    assert not subprocess.run(["docker", "ps", "-q", "--filter", "label=clm-harness=1"],
                              capture_output=True, text=True, timeout=30).stdout.strip()


def test_close_removes_the_container(docker_ready, workdir, session_dir):
    shell = Shell(workdir, session_dir, Config(command_timeout=20, sandbox="docker"))
    shell.run(f"({HEARTBEAT}) &")
    name = shell.sandbox.name
    assert _containers(name)
    shell.close()
    assert not _containers(name)
