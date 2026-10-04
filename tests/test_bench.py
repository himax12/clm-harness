import csv
import json

import pytest

from clm_harness.bench import kv_store, ledger
from clm_harness.bench.common import (ALL_DELIVERED, READY, Op, StreamDriver, check_sizing, extract_answers,
                          score, sized_for, total_tokens)
from clm_harness.bench.run import report, run_matrix
from clm_harness.config import Config
from clm_harness.loop import ModelReply

CFG = Config()


def transcript(tmp_path, *replies):
    path = tmp_path / "transcript.jsonl"
    lines = [json.dumps({"type": "start", "turn": 0})]
    lines += [json.dumps({"type": "reply", "turn": i, "text": t, "command": c})
              for i, (t, c) in enumerate(replies, 1)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.mark.parametrize("module", [kv_store, ledger])
def test_same_seed_gives_identical_operations(module):
    assert module.generate(7, 3) == module.generate(7, 3)
    assert module.generate(7, 3) != module.generate(8, 3)


@pytest.mark.parametrize("module", [kv_store, ledger])
@pytest.mark.parametrize("pressure", [1.5, 3, 6])
def test_stream_is_sized_to_the_pressure_and_each_op_fits(module, pressure):
    ops = sized_for(module.generate, 1, pressure, CFG.budget_tokens)
    assert total_tokens(ops) >= pressure * CFG.budget_tokens
    check_sizing(ops, CFG.limit)


def test_sizing_check_rejects_an_oversized_operation():
    with pytest.raises(ValueError):
        check_sizing([Op("x" * 40_000)], CFG.limit)


def test_kv_store_shape():
    ops = kv_store.generate(1, 3)
    sets, gets = ops[:3], ops[3:]
    assert len(gets) == 24 and all(op.answer_id is None for op in sets)
    lines = sets[0].text.splitlines()
    assert lines[0] == "<<<SET-BATCH 0000 BEGIN>>>" and len(lines) == 102
    key, value = lines[1].removeprefix("SET ").split(" = ")
    assert key == "K00000" and len(value.split()) == 25 and value.split()[-1].startswith("#")
    get = gets[0]
    assert get.text == f"GET {get.answer_id}"
    assert any(f"SET {get.answer_id} = {get.answer}" in s.text for s in sets)


def test_ledger_answers_match_a_replay_of_the_transfers():
    ops = ledger.generate(3, 6)
    balance = {}
    answers = {}
    for op in ops:
        for line in op.text.splitlines():
            if line.startswith("OPEN A"):
                name, amount = line.removeprefix("OPEN ").split(" = ")
                balance[name] = int(amount)
            elif line.startswith("TRANSFER"):
                _, src, _, dst, _, amount = line.split()
                balance[src] -= int(amount)
                balance[dst] += int(amount)
        if op.answer_id:
            name = op.text.rstrip("?").split()[-1]
            answers[op.answer_id] = str(balance[name])
    expected = {op.answer_id: op.answer for op in ops if op.answer_id}
    assert expected == answers and list(expected) == ["q01", "q02"]


def test_driver_releases_one_operation_per_ready_line():
    driver = StreamDriver([Op("one"), Op("two")])
    assert driver.start() == "one"
    assert driver.after_command("ls", "a.txt\n(exit_code=0)") is None
    assert driver.after_command("echo", f"saved\n{READY}\n(exit_code=0)") == "two"
    assert driver.after_command("echo", f"{READY}\n(exit_code=0)") == ALL_DELIVERED
    assert driver.after_command("echo", f"{READY}\n(exit_code=0)") is None


def test_driver_ignores_ready_inside_other_text():
    driver = StreamDriver([Op("one"), Op("two")])
    driver.start()
    assert driver.after_command("x", f"not {READY} yet\n(exit_code=0)") is None


def test_answers_are_read_from_reply_text_and_commands(tmp_path):
    path = transcript(
        tmp_path,
        ("<<<ANSWER K00001>>> the  amber\nriver #ab12 <<<ANSWER END>>>", f"echo {READY}"),
        ("", 'echo "<<<ANSWER q02>>> 731 <<<ANSWER END>>>"'),
        ("<<<ANSWER K00001>>> corrected #ab12 <<<ANSWER END>>>", None),
    )
    assert extract_answers(path) == {"K00001": "corrected #ab12", "q02": "731"}


def test_score_is_exact_match_per_question(tmp_path):
    ops = kv_store.generate(1, 1)
    gets = [op for op in ops if op.answer_id]
    perfect = transcript(tmp_path, *[
        (f"<<<ANSWER {op.answer_id}>>> {op.answer} <<<ANSWER END>>>", f"echo {READY}")
        for op in gets])
    assert score(ops, perfect) == 1.0

    replies = [(f"<<<ANSWER {op.answer_id}>>> {op.answer} <<<ANSWER END>>>", None) for op in gets]
    replies[0] = (replies[0][0].replace("#", "#x"), None)  # one wrong tag
    assert score(ops, transcript(tmp_path, *replies)) == pytest.approx(23 / 24)
    assert score(ops, transcript(tmp_path)) == 0.0


class Oracle:
    """A model that knows every answer: stores nothing, releases each op, answers each query."""

    def __init__(self, ops):
        self.answers = {op.text: op for op in ops if op.answer_id}

    def reply(self, system, ctx):
        last = next((b for b in reversed(ctx.blocks) if b.role == "input"), None)
        if last is None or last.body == ALL_DELIVERED:
            return ModelReply(text="DONE")
        op = self.answers.get(last.body)
        text = f"<<<ANSWER {op.answer_id}>>> {op.answer} <<<ANSWER END>>>" if op else ""
        return ModelReply(text=text, command=f"echo {READY}", stop_reason="tool_use")


@pytest.mark.parametrize("mode", ["clm", "baseline"])
def test_matrix_runs_end_to_end_with_an_oracle(tmp_path, mode):
    def make_model(cfg):
        return Oracle(sized_for(kv_store.generate, 1, 0.3, cfg.budget_tokens))

    rows = run_matrix(["kv"], [mode], [1], pressure=0.3, ceiling_usd=100, out_dir=tmp_path,
                      make_model=make_model)
    (row,) = rows
    n_ops = len(sized_for(kv_store.generate, 1, 0.3, CFG.budget_tokens))
    assert row["status"] == "finished" and row["accuracy"] == 1.0
    assert row["ops"] == n_ops and row["steps"] == n_ops  # one command per operation
    with (tmp_path / "results.csv").open() as f:
        assert [r["mode"] for r in csv.DictReader(f)] == [mode]
    assert "kv" in report(tmp_path / "results.csv")


def test_spend_ceiling_skips_runs(tmp_path, capsys):
    rows = run_matrix(["kv"], ["clm"], [1, 2], pressure=0.3, ceiling_usd=5, out_dir=tmp_path,
                      make_model=lambda cfg: None, max_cost_per_run=8)
    assert rows == [] and "spend ceiling" in capsys.readouterr().out
