import json

import pytest

from clm_harness.config import Config
from clm_harness.context import apply_edit, parse, raw_tokens, render, render_block
from clm_harness.session import Session, Usage, undo

from conftest import make_ctx


def count(blocks):
    return sum(raw_tokens(render_block(b)) for b in blocks)


def test_cost_matches_a_hand_calculation():
    usage = Usage(input=1_000_000, output=100_000, cache_read=2_000_000, cache_write=500_000)
    # 1M x $4 + 0.1M x $20 + 2M x $0.20 + 0.5M x $5
    assert usage.cost() == pytest.approx(4.0 + 2.0 + 0.4 + 2.5)
    assert usage.prompt_total == 3_500_000


def test_events_are_json_lines_in_order(workdir):
    s = Session(workdir, Config())
    s.event("start", 0, task="t")
    s.event("reply", 1, text="héllo")
    lines = s.transcript.read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines]
    assert [e["type"] for e in events] == ["start", "reply"]
    assert events[1]["text"] == "héllo" and events[1]["turn"] == 1


def test_block_original_is_written_once(workdir):
    s = Session(workdir, Config())
    ctx = make_ctx(("output", "the original"))
    block = ctx.blocks[0]
    s.save_block(block)
    block.body = "edited later"
    s.save_block(block)
    assert (s.dir / "blocks" / "b0001.txt").read_text(encoding="utf-8") == "the original"


def test_usage_file(workdir):
    s = Session(workdir, Config())
    s.add_usage(Usage(input=1000, output=10))
    s.bump("steps")
    s.bump("steps")
    s.write_usage("finished")
    data = json.loads((s.dir / "usage.json").read_text())
    assert data["status"] == "finished" and data["steps"] == 2
    assert data["tokens"]["input"] == 1000
    assert data["dollars"] == pytest.approx(0.0042)


def test_undo_restores_the_context_and_keeps_later_blocks(workdir):
    s = Session(workdir, Config())
    ctx = make_ctx(("user", "op"), ("output", "long original output"))
    before = list(ctx.blocks)
    rendered = render(ctx)
    result = apply_edit(ctx, rendered, rendered.replace("long original output", "short"), 10_000, count)
    assert result.status == "applied"
    s.snapshot(3, before)
    ctx.add("assistant", "$ next")  # created after the edit
    s.ctx_path.write_text(render(ctx), encoding="utf-8", newline="\n")

    assert undo(s.dir) == 3
    restored = parse(s.ctx_path.read_text(encoding="utf-8"))
    assert [(i, b) for i, _, b in restored] == [
        ("b0001", "op"),
        ("b0002", "long original output"),
        ("b0003", "$ next"),
    ]
    last = json.loads(s.transcript.read_text(encoding="utf-8").splitlines()[-1])
    assert last["type"] == "undo"


def test_undo_without_an_edit_raises(workdir):
    s = Session(workdir, Config())
    with pytest.raises(FileNotFoundError):
        undo(s.dir)
