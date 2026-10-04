import json

from clm_harness.cli import main as cli
from clm_harness.config import Config
from clm_harness.loop import ModelReply, ScriptedModel, run, run_command

# Replace the body of one block in "$CTX" with a short note, using perl (present in
# Git Bash and on Linux). Prints nothing, so an accepted edit makes the turn free.
def shrink(block_id: str, note: str) -> str:
    return (
        "perl -0pi -e 's/(\\[\\[BLOCK id=" + block_id + " [^\\n]*\\n).*?(?=\\n\\n\\[\\[BLOCK|\\z)/${1}"
        + note + "/s' \"$CTX\""
    )


def events(result, kind=None):
    lines = (result.session_dir / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
    out = [json.loads(line) for line in lines]
    return [e for e in out if e["type"] == kind] if kind else out


def usage(result):
    return json.loads((result.session_dir / "usage.json").read_text())


def test_run_finishes_on_a_reply_without_a_command(workdir):
    model = ScriptedModel([run_command("echo hello > f.txt"), run_command("cat f.txt"),
                           ModelReply(text="the file says hello")])
    result = run("write and read a file", workdir, Config(), model)
    assert result.status == "finished" and result.answer == "the file says hello"
    assert (workdir / "f.txt").read_text().strip() == "hello"
    assert usage(result)["steps"] == 2 and usage(result)["model_calls"] == 3


def test_model_sees_its_command_and_the_output_next_turn(workdir):
    model = ScriptedModel([run_command("echo marker-123")])
    run("t", workdir, Config(), model)
    assert "[[BLOCK" not in model.seen[0]  # nothing yet on the first turn
    second = model.seen[1]
    assert "role=assistant" in second and "$ echo marker-123" in second
    assert "marker-123\n(exit_code=0)" in second and "[context: " in second


def test_reasoning_and_text_are_written_into_the_context(workdir):
    reply = ModelReply(thinking="I should look around", text="Listing files.", command="ls",
                       stop_reason="tool_use")
    model = ScriptedModel([reply])
    run("t", workdir, Config(), model)
    assert "I should look around\nListing files.\n$ ls" in model.seen[1]


def test_accepted_edit_changes_what_the_model_sees(workdir):
    model = ScriptedModel([
        run_command("seq 1 300"),                    # b0001 assistant, b0002 output
        run_command(shrink("b0002", "300 numbers")),
        ModelReply(text="done"),
    ])
    result = run("t", workdir, Config(), model)
    assert "\n299\n" in model.seen[1]
    assert "\n299\n" not in model.seen[2] and "300 numbers" in model.seen[2]
    assert "[context edit applied:" in model.seen[2]

    (applied,) = events(result, "edit_applied")
    assert applied["after_tokens"] < applied["before_tokens"]
    assert applied["first_changed"] == 1 and applied["reread_tokens"] > 0
    # The original survives on disk, and the edit was snapshotted.
    assert "\n299\n" in (result.session_dir / "blocks" / "b0002.txt").read_text()
    assert len(list((result.session_dir / "snapshots").glob("*.json"))) == 1
    # The edit printed nothing and succeeded, so it did not cost a step.
    assert usage(result)["steps"] == 1 and usage(result)["free_turns"] == 1


def test_refused_edit_leaves_the_context_unchanged(workdir):
    model = ScriptedModel([
        run_command("echo keep-me"),
        run_command('echo "everything summarised" > "$CTX"'),
        ModelReply(text="done"),
    ])
    result = run("t", workdir, Config(), model)
    assert "keep-me" in model.seen[2]
    assert "[context edit REFUSED:" in model.seen[2]
    assert len(events(result, "edit_refused")) == 1 and not events(result, "edit_applied")
    assert usage(result)["steps"] == 2  # a refused edit costs a normal step


def test_edit_that_matches_nothing_gets_a_receipt(workdir):
    model = ScriptedModel([run_command("echo x"), run_command(shrink("b0999", "n")),
                           ModelReply(text="done")])
    run("t", workdir, Config(), model)
    assert "matched nothing" in model.seen[2]


def test_three_refused_edits_in_a_row_add_a_notice(workdir):
    bad = run_command('echo nope > "$CTX"')
    model = ScriptedModel([bad, bad, bad, ModelReply(text="done")])
    run("t", workdir, Config(), model)
    assert "Stop editing and continue the task" in model.seen[3]


def test_free_edit_turns_are_capped(workdir):
    cfg = Config(max_free_edits_in_row=2)
    model = ScriptedModel([
        run_command("seq 1 50"),
        run_command(shrink("b0002", "aaa")),
        run_command(shrink("b0002", "bb")),
        run_command(shrink("b0002", "c")),
        ModelReply(text="done"),
    ])
    result = run("t", workdir, cfg, model)
    assert usage(result)["free_turns"] == 2 and usage(result)["steps"] == 2


def test_overflow_rolls_back_and_pins_a_note(workdir):
    cfg = Config(budget_tokens=5_048, inline_chars=100_000)  # limit 3,000
    model = ScriptedModel([
        run_command("echo small"),
        run_command("seq 1 3000"),  # capped to the room that is left
        run_command("seq 1 3000"),
        run_command("seq 1 3000"),
        ModelReply(text="done"),
    ])
    result = run("t", workdir, cfg, model)
    rollbacks = events(result, "rollback")
    assert rollbacks and rollbacks[0]["tokens_after"] < rollbacks[0]["tokens_before"]
    assert usage(result)["rollbacks"] >= 1
    replies = events(result, "reply")
    assert all(e["context_tokens"] <= cfg.limit for e in replies)  # never sent over the limit


def test_output_is_capped_to_the_room_left(workdir):
    cfg = Config(budget_tokens=5_048, inline_chars=100_000)
    model = ScriptedModel([run_command("seq 1 5000")])
    result = run("t", workdir, cfg, model)
    assert "characters elided" in model.seen[1]
    assert (result.session_dir / "outputs" / "turn-0001.txt").exists()


def test_step_limit(workdir):
    model = ScriptedModel([run_command("true")] * 10)
    assert run("t", workdir, Config(max_steps=3), model).status == "step_limit"


def test_cost_limit(workdir):
    from clm_harness.session import Usage

    pricey = ModelReply(command="true", stop_reason="tool_use", usage=Usage(output=100_000))
    result = run("t", workdir, Config(max_cost_usd=3.0), ScriptedModel([pricey] * 10))
    assert result.status == "cost_limit" and usage(result)["model_calls"] == 2  # $2 each


def test_time_limit(workdir):
    result = run("t", workdir, Config(max_wall_seconds=0), ScriptedModel([run_command("true")]))
    assert result.status == "time_limit"


def test_refusal_stops_the_run(workdir):
    model = ScriptedModel([ModelReply(stop_reason="refusal")])
    assert run("t", workdir, Config(), model).status == "refusal"


def test_command_from_a_cut_off_reply_is_not_run(workdir):
    cut = ModelReply(command="touch should-not-exist", stop_reason="max_tokens")
    model = ScriptedModel([cut, ModelReply(text="done")])
    result = run("t", workdir, Config(), model)
    assert result.status == "finished"
    assert not (workdir / "should-not-exist").exists()
    assert "cut off at the output limit" in model.seen[1]


def test_three_cut_off_replies_in_a_row_stop_the_run(workdir):
    cut = ModelReply(command="true", stop_reason="max_tokens")
    assert run("t", workdir, Config(), ScriptedModel([cut] * 5)).status == "error"


def test_blocked_command_is_not_run(workdir):
    model = ScriptedModel([run_command("rm -rf ~"), ModelReply(text="done")])
    result = run("t", workdir, Config(), model)
    assert "[command blocked:" in model.seen[1]
    assert usage(result)["blocked"] == 1 and not events(result, "command")


def test_restart_resets_shell_state(workdir):
    model = ScriptedModel([
        run_command("mkdir sub && cd sub"),
        ModelReply(restart=True, stop_reason="tool_use"),
        run_command("pwd"),
    ])
    run("t", workdir, Config(), model)
    assert "(shell state reset)" in model.seen[2]
    assert "work dir\n(exit_code=0)" in model.seen[3]


class TwoOps:
    def __init__(self):
        self.ops = ["second operation"]

    def start(self):
        return "first operation"

    def after_command(self, command, observation):
        if observation.startswith("READY") and self.ops:
            return self.ops.pop(0)
        return None


def test_driver_feeds_operations_as_input_blocks(workdir):
    model = ScriptedModel([run_command("echo READY"), ModelReply(text="done")])
    run("t", workdir, Config(), model, driver=TwoOps())
    assert "role=input" in model.seen[0] and "first operation" in model.seen[0]
    assert "second operation" in model.seen[1]


def test_baseline_mode_renders_no_file_and_applies_no_edits(workdir):
    model = ScriptedModel([run_command("echo x"), run_command('echo hi > "$CTX"'),
                           ModelReply(text="done")])
    result = run("t", workdir, Config(mode="baseline"), model)
    assert "echo x" in model.seen[2]
    assert not events(result, "edit_refused") and not events(result, "notice")


def test_notice_appears_when_a_tier_is_crossed(workdir):
    cfg = Config(budget_tokens=6_048, inline_chars=100_000)  # limit 4,000
    model = ScriptedModel([run_command("seq 1 600"), ModelReply(text="done")])
    result = run("t", workdir, cfg, model)
    notices = events(result, "notice")
    assert notices and "of the limit" in notices[0]["text"]
    assert "role=notice" in model.seen[1]


def test_log_and_undo_commands(workdir, capsys):
    model = ScriptedModel([run_command("seq 1 300"), run_command(shrink("b0002", "300 numbers")),
                           ModelReply(text="done")])
    result = run("t", workdir, Config(), model)

    assert cli(["log", str(result.session_dir)]) == 0
    out = capsys.readouterr().out
    assert "$ seq 1 300" in out and "edit applied:" in out and "finished: finished" in out

    assert cli(["undo", str(result.session_dir)]) == 0
    assert "\n299\n" in (result.session_dir / "LIVE_CTX.md").read_text(encoding="utf-8")


def test_model_can_edit_task_input_but_rollback_never_drops_it(workdir):
    model = ScriptedModel([run_command(shrink("b0001", "op stored in ops.txt")),
                           ModelReply(text="done")])
    result = run("t", workdir, Config(), model, driver=TwoOps())
    assert len(events(result, "edit_applied")) == 1
    assert "op stored in ops.txt" in model.seen[1]


def test_failed_model_call_still_finishes_the_session(workdir):
    def boom(system, ctx):
        raise RuntimeError("network down")

    result = run("t", workdir, Config(), ScriptedModel([boom]))
    assert result.status == "error" and "network down" in result.answer
    assert usage(result)["status"] == "error"


def test_invalid_tool_input_is_reprompted(workdir):
    bad = ModelReply(stop_reason="invalid_tool")
    model = ScriptedModel([bad, ModelReply(text="done")])
    assert run("t", workdir, Config(), model).status == "finished"
    assert "invalid input" in model.seen[1]
