from harness.config import Config
from harness.shell import Shell, cap_to_room, format_observation, to_posix


def test_starts_in_workdir(shell, workdir):
    assert shell.run("pwd").output.strip() == to_posix(workdir)


def test_cwd_persists_across_commands(shell):
    shell.run("mkdir sub && cd sub")
    assert shell.run("pwd").output.strip().endswith("/work dir/sub")


def test_exported_variable_persists(shell):
    shell.run("export FOO='a b'")
    assert shell.run('echo "$FOO"').output.strip() == "a b"


def test_exit_code_is_reported(shell):
    assert shell.run("false").exit_code == 1
    assert shell.run("true").exit_code == 0


def test_explicit_exit_still_saves_state(shell):
    shell.run("mkdir sub")
    result = shell.run("cd sub; exit 3")
    assert result.exit_code == 3
    assert shell.run("pwd").output.strip().endswith("/sub")


def test_stderr_is_merged(shell):
    assert "oops" in shell.run("echo oops >&2").output


def test_command_with_quotes_dollar_and_newlines_runs_intact(shell):
    command = "printf '%s\\n' \"it's \\$5\" 'single \"q\"'\necho second"
    assert shell.run(command).output.splitlines() == ["it's $5", 'single "q"', "second"]


def test_ctx_variable_points_at_a_writable_file(shell):
    result = shell.run('echo hello > "$CTX" && cat "$CTX" && echo "$CTX_DIR"')
    lines = result.output.splitlines()
    assert lines[0] == "hello"
    assert lines[1].endswith("/sess dir")


def test_reset_forgets_cwd_and_environment(shell, workdir):
    shell.run("mkdir sub && cd sub && export FOO=1")
    shell.reset()
    assert shell.run('pwd; echo "[$FOO]"').output.splitlines() == [to_posix(workdir), "[]"]


def test_timeout_kills_the_command(workdir, session_dir):
    shell = Shell(workdir, session_dir, Config(command_timeout=2))
    result = shell.run("echo started; sleep 30; echo finished")
    assert result.timed_out and result.exit_code == -1
    assert result.seconds < 20
    assert "finished" not in result.output
    assert shell.run("echo ok").output.strip() == "ok"  # still usable afterwards


def test_short_output_is_shown_whole(shell, session_dir):
    cfg = Config()
    text = format_observation(shell.run("echo hi"), "turn-0001", session_dir / "outputs", cfg)
    assert text == "hi\n(exit_code=0)"


def test_empty_output_is_labelled(shell, session_dir):
    text = format_observation(shell.run("true"), "turn-0001", session_dir / "outputs", Config())
    assert text == "(no output)\n(exit_code=0)"


def test_long_output_is_cut_and_saved(shell, session_dir):
    cfg = Config(inline_chars=1000, head_chars=300, tail_chars=200)
    result = shell.run("for i in $(seq 1 400); do echo line-$i; done")
    text = format_observation(result, "turn-0007", session_dir / "outputs", cfg)
    full = result.output.rstrip()
    assert text.startswith(full[:300])
    assert f"[{len(full) - 500:,} characters elided" in text
    assert full[-200:] in text and text.endswith("(exit_code=0)")
    assert (session_dir / "outputs" / "turn-0007.txt").read_text(encoding="utf-8") == full


def test_cap_to_room_cuts_and_saves(session_dir, est):
    observation = "x" * 8000
    out = cap_to_room(observation, 500, est, "turn-0002", session_dir / "outputs")
    assert est.tokens(out) <= 500
    assert "characters elided" in out
    assert (session_dir / "outputs" / "turn-0002.txt").read_text(encoding="utf-8") == observation


def test_cap_to_room_leaves_fitting_text_alone(session_dir, est):
    assert cap_to_room("short", 500, est, "turn-0003", session_dir / "outputs") == "short"
    assert not (session_dir / "outputs" / "turn-0003.txt").exists()


def test_background_job_does_not_hold_up_the_turn(shell):
    result = shell.run("sleep 6 & echo started")
    assert result.output.strip() == "started" and result.exit_code == 0
    assert result.seconds < 4  # with a pipe this waited for the sleep to finish


def test_background_job_keeps_running_for_the_next_command(shell):
    shell.run("(sleep 1; echo done > marker.txt) &")
    assert "done" in shell.run("sleep 3; cat marker.txt").output


def test_runaway_output_is_killed(workdir, session_dir):
    shell = Shell(workdir, session_dir, Config(command_timeout=30, max_output_bytes=200_000))
    result = shell.run("yes abcdefghij")
    assert result.output_limit and result.exit_code == -1 and not result.timed_out
    assert result.seconds < 15
    text = format_observation(result, "turn-0001", session_dir / "outputs", shell.cfg)
    assert "killed: output passed" in text


def test_large_finished_output_is_read_as_head_and_tail_only(workdir, session_dir):
    shell = Shell(workdir, session_dir, Config(max_output_bytes=100_000))
    result = shell.run("echo START; head -c 3000000 /dev/zero | tr '\\0' 'a'; echo; echo END")
    assert len(result.output) < 110_000  # never the full 3 MB in memory
    assert result.output.startswith("START") and result.output.rstrip().endswith("END")
    assert "bytes omitted by the harness" in result.output


def test_output_files_are_cleaned_up(shell):
    shell.run("echo one")
    shell.run("echo two")
    assert not list(shell.state.glob("out-*.bin"))


def test_api_credentials_are_not_visible_to_commands(shell, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-secret")
    out = shell.run('echo "[$ANTHROPIC_API_KEY][$ANTHROPIC_AUTH_TOKEN]"; env | grep -ci anthropic').output
    assert out.splitlines() == ["[][]", "0"]
