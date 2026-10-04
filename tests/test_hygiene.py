"""Run hygiene: clean shutdown, progress output,
per-model prices, configuration checks and the CLI conveniences."""
import io
import json
from types import SimpleNamespace as NS

import pytest

from clm_harness import cli as cli_module
from clm_harness.cli import main as cli
from clm_harness.config import Config, prices_for
from clm_harness.llm import parse_response
from clm_harness.loop import ModelReply, ScriptedModel, run, run_command
from clm_harness.session import Session, Usage


def events(session_dir, kind=None):
    lines = (session_dir / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
    out = [json.loads(line) for line in lines]
    return [e for e in out if e["type"] == kind] if kind else out


def latest_session(workdir):
    return sorted((workdir / ".ctx" / "sessions").iterdir())[-1]


# --- sessions on disk ---------------------------------------------------------


def test_session_folder_ignores_itself_in_git(workdir):
    Session(workdir, Config())
    assert (workdir / ".ctx" / ".gitignore").read_text() == "*\n"


def test_an_existing_ignore_file_is_left_alone(workdir):
    (workdir / ".ctx").mkdir()
    (workdir / ".ctx" / ".gitignore").write_text("custom\n")
    Session(workdir, Config())
    assert (workdir / ".ctx" / ".gitignore").read_text() == "custom\n"


def test_start_event_carries_the_schema_version(workdir):
    result = run("t", workdir, Config(), ScriptedModel([]))
    assert events(result.session_dir, "start")[0]["schema"] == 1


# --- shutdown -----------------------------------------------------------------


def test_ctrl_c_still_closes_the_session(workdir):
    def interrupt(system, ctx):
        raise KeyboardInterrupt

    result = run("t", workdir, Config(), ScriptedModel([run_command("echo one"), interrupt]))
    assert result.status == "interrupted"
    assert events(result.session_dir, "finish")[0]["status"] == "interrupted"
    assert json.loads((result.session_dir / "usage.json").read_text())["status"] == "interrupted"


def test_a_harness_bug_closes_the_session_and_is_still_raised(workdir):
    class BrokenDriver:
        def start(self):
            return "first"

        def after_command(self, command, observation):
            raise RuntimeError("driver bug")

    with pytest.raises(RuntimeError, match="driver bug"):
        run("t", workdir, Config(), ScriptedModel([run_command("true")]), driver=BrokenDriver())
    session = latest_session(workdir)
    finish = events(session, "finish")[0]
    assert finish["status"] == "error" and "driver bug" in finish["answer"]
    assert (session / "usage.json").exists()


# --- replies ------------------------------------------------------------------


def test_the_model_is_told_when_extra_tool_calls_were_ignored(workdir):
    reply = ModelReply(command="echo a", stop_reason="tool_use", dropped_calls=2)
    model = ScriptedModel([reply])
    run("t", workdir, Config(), model)
    assert "2 more in the same reply were ignored" in model.seen[1]


def test_refusal_category_is_recorded(workdir):
    reply = ModelReply(stop_reason="refusal", refusal="cyber: looked like an exploit")
    result = run("t", workdir, Config(), ScriptedModel([reply]))
    assert result.status == "refusal" and "cyber" in result.answer
    assert events(result.session_dir, "reply")[0]["refusal"].startswith("cyber")


def test_parse_response_reads_refusal_details_and_counts_extra_calls():
    usage = NS(input_tokens=1, output_tokens=0, cache_read_input_tokens=0,
               cache_creation_input_tokens=0)
    refused = NS(content=[], stop_reason="refusal", model="m", usage=usage,
                 stop_details=NS(category="bio", explanation="declined"))
    assert parse_response(refused).refusal == "bio: declined"
    bare = NS(content=[], stop_reason="refusal", model="m", usage=usage, stop_details=None)
    assert parse_response(bare).refusal == "no category given"

    call = lambda c: NS(type="tool_use", name="bash", input={"command": c})  # noqa: E731
    three = NS(content=[call("a"), call("b"), call("c")], stop_reason="tool_use", model="m",
               usage=usage)
    reply = parse_response(three)
    assert reply.command == "a" and reply.dropped_calls == 2


# --- progress -----------------------------------------------------------------


def test_progress_reports_each_turn_and_each_edit(workdir):
    lines = []
    edit = ("perl -0pi -e 's/(\\[\\[BLOCK id=b0002 [^\\n]*\\n).*?(?=\\n\\n\\[\\[BLOCK|\\z)/${1}"
            "short/s' \"$CTX\"")
    model = ScriptedModel([run_command("seq 1 200"), run_command(edit),
                           run_command('echo nope > "$CTX"')])
    run("t", workdir, Config(), model, progress=lines.append)
    assert any("$ seq 1 200" in line and "ctx=" in line and "$  0.00" in line for line in lines)
    assert any("edit applied:" in line for line in lines)
    assert any("edit REFUSED:" in line for line in lines)
    assert any("(no command)" in line for line in lines)


# --- prices -------------------------------------------------------------------


def test_cost_uses_the_given_models_prices():
    usage = Usage(input=1_000_000, output=1_000_000)
    assert usage.cost() == pytest.approx(24.0)  # Opus 5.5 by default
    assert usage.cost("claude-sonnet-5-5") == pytest.approx(12.0)
    assert usage.cost("claude-opus-5") == pytest.approx(30.0)


def test_a_fallback_turn_is_charged_at_the_serving_models_prices(workdir):
    s = Session(workdir, Config())
    s.add_usage(Usage(output=1_000_000))  # served by the configured model
    s.add_usage(Usage(output=1_000_000), "claude-opus-5")
    assert s.dollars == pytest.approx(20.0 + 25.0) and not s.price_estimated


def test_an_unknown_model_is_priced_as_a_guess_and_flagged(workdir):
    assert prices_for("some-future-model") == (prices_for("claude-opus-5-5")[0], False)
    s = Session(workdir, Config())
    s.add_usage(Usage(output=1_000_000), "some-future-model")
    s.write_usage("finished")
    data = json.loads((s.dir / "usage.json").read_text())
    assert data["price_estimated"] is True and data["dollars"] == pytest.approx(20.0)


# --- configuration ------------------------------------------------------------


@pytest.mark.parametrize("kwargs, message", [
    ({"budget_tokens": 1_000}, "budget_tokens"),
    ({"mode": "magic"}, "mode"),
    ({"effort": "extreme"}, "effort"),
    ({"max_steps": 0}, "max_steps"),
    ({"max_cost_usd": 0}, "max_cost_usd"),
    ({"command_timeout": -5}, "command_timeout"),
    ({"head_chars": 9_000, "tail_chars": 9_000}, "head_chars"),
    ({"nudge_tiers": (0.5, 1.5)}, "nudge_tiers"),
])
def test_bad_configuration_is_rejected_with_the_field_named(kwargs, message):
    with pytest.raises(ValueError, match=message):
        Config(**kwargs)


def test_default_configuration_is_valid():
    assert Config().limit == 29_952


# --- command line -------------------------------------------------------------


@pytest.fixture
def fake_claude(monkeypatch):
    made = []

    def make(cfg):
        made.append(cfg)
        return ScriptedModel([run_command("echo hi"), ModelReply(text="all done")])

    monkeypatch.setattr(cli_module, "_claude", make)
    return made


def test_run_prints_progress_and_the_answer(workdir, fake_claude, capsys):
    assert cli(["run", "say hi", "--dir", str(workdir)]) == 0
    out = capsys.readouterr()
    assert out.out.strip() == "all done"
    assert "$ echo hi" in out.err and "[finished]" in out.err


def test_quiet_suppresses_progress(workdir, fake_claude, capsys):
    assert cli(["run", "say hi", "--dir", str(workdir), "--quiet"]) == 0
    assert "$ echo hi" not in capsys.readouterr().err


def test_flags_reach_the_configuration(workdir, fake_claude):
    cli(["run", "t", "--dir", str(workdir), "--effort", "high", "--timeout", "30",
         "--budget", "20000", "--max-steps", "7", "--max-cost", "1.5", "--allow-push", "--quiet"])
    cfg = fake_claude[0]
    assert (cfg.effort, cfg.command_timeout, cfg.budget_tokens, cfg.max_steps, cfg.max_cost_usd,
            cfg.allow_push) == ("high", 30, 20000, 7, 1.5, True)


def test_untested_model_gets_a_warning(workdir, fake_claude, capsys):
    cli(["run", "t", "--dir", str(workdir), "--model", "claude-sonnet-5-5", "--quiet"])
    err = capsys.readouterr().err
    assert "claude-sonnet-5-5 is untested" in err and "prices are unknown" not in err
    cli(["run", "t", "--dir", str(workdir), "--model", "mystery-model", "--quiet"])
    assert "prices are unknown" in capsys.readouterr().err


def test_invalid_flags_fail_cleanly(workdir, fake_claude, capsys):
    assert cli(["run", "t", "--dir", str(workdir), "--budget", "500"]) == 2
    assert "budget_tokens" in capsys.readouterr().err and not fake_claude


def test_task_can_come_from_a_file_or_stdin(workdir, fake_claude, monkeypatch, tmp_path):
    task_file = tmp_path / "task.txt"
    task_file.write_text("task from a file\n", encoding="utf-8")
    cli(["run", "--task-file", str(task_file), "--dir", str(workdir), "--quiet"])
    assert events(latest_session(workdir), "start")[0]["task"] == "task from a file"

    monkeypatch.setattr("sys.stdin", io.StringIO("task from stdin"))
    cli(["run", "--task-file", "-", "--dir", str(workdir), "--quiet"])
    tasks = {events(d, "start")[0]["task"] for d in (workdir / ".ctx" / "sessions").iterdir()}
    assert "task from stdin" in tasks


def test_missing_task_is_an_error(workdir, fake_claude, capsys):
    assert cli(["run", "--dir", str(workdir)]) == 2
    assert "no task given" in capsys.readouterr().err


def test_sessions_lists_status_cost_and_task(workdir, fake_claude, capsys):
    cli(["run", "summarise the repo", "--dir", str(workdir), "--quiet"])
    capsys.readouterr()
    assert cli(["sessions", "--dir", str(workdir)]) == 0
    out = capsys.readouterr().out
    assert "finished" in out and "$0.00" in out and "summarise the repo" in out


def test_sessions_on_an_empty_folder(workdir, capsys):
    assert cli(["sessions", "--dir", str(workdir)]) == 0
    assert "no sessions" in capsys.readouterr().out
