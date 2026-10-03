import json

from harness.baseline import CLEARED, maybe_compact
from harness.budget import context_tokens
from harness.config import Config
from harness.session import Session, Usage

from conftest import make_ctx

CFG = Config(mode="baseline", budget_tokens=12_048)  # limit 10,000; trigger 8,000


def filled(outputs=8, size=4000):
    ctx = make_ctx(("user", "please do the thing"))
    for i in range(outputs):
        ctx.add("assistant", f"$ cmd-{i}", command=f"cmd-{i}")
        ctx.add("output", f"out-{i} " + "o" * size)  # ~1000 tokens each
    return ctx


def test_nothing_happens_below_the_trigger(workdir, est):
    ctx = filled(outputs=3)
    before = [b.body for b in ctx.blocks]
    maybe_compact(ctx, "", est, CFG, Session(workdir, CFG), 1)
    assert [b.body for b in ctx.blocks] == before


def test_old_outputs_are_cleared_and_recent_ones_kept(workdir, est):
    ctx = filled(outputs=9)  # ~9,000 tokens, over the 8,000 trigger
    session = Session(workdir, CFG)
    maybe_compact(ctx, "", est, CFG, session, 1)
    outputs = [b for b in ctx.blocks if b.role == "output"]
    assert outputs[0].body == CLEARED and outputs[-1].body.startswith("out-8")
    assert all(b.body.startswith("$ cmd-") for b in ctx.blocks if b.role == "assistant")
    assert context_tokens(ctx, "", est) <= 0.8 * CFG.limit
    event = json.loads(session.transcript.read_text().splitlines()[-1])
    assert event["type"] == "compact" and event["stage"] == "clear"


def test_summarise_runs_when_clearing_is_not_enough(workdir, est):
    ctx = make_ctx(("user", "please do the thing"))
    for i in range(12):
        ctx.add("assistant", f"reasoning {i} " + "r" * 3200, command=f"cmd-{i}")  # not clearable
    session = Session(workdir, CFG)
    calls = []

    def summarise(record):
        calls.append(record)
        return "did twelve things", Usage(input=5000, output=200)

    maybe_compact(ctx, "", est, CFG, session, 1, summarise)
    assert len(calls) == 1 and "reasoning 0" in calls[0] and "please do the thing" in calls[0]
    roles = [b.role for b in ctx.blocks]
    assert roles[:2] == ["user", "note"] and len(ctx.blocks) == 2 + 6
    assert ctx.blocks[1].body == "[Summary of earlier work]\ndid twelve things"
    assert ctx.blocks[-1].body.startswith("reasoning 11")  # the newest blocks are untouched
    assert session.usage.output == 200  # the summary call is charged to the run


def test_user_messages_survive_every_stage(workdir, est):
    ctx = make_ctx(("user", "first request"))
    for i in range(12):
        ctx.add("assistant", "r" * 3200)
    ctx.add("user", "second request")
    maybe_compact(ctx, "", est, CFG, Session(workdir, CFG), 1, lambda r: ("s", Usage()))
    assert [b.body for b in ctx.blocks if b.role == "user"] == ["first request", "second request"]


def test_oldest_blocks_are_dropped_as_a_last_resort(workdir, est):
    ctx = make_ctx(("user", "u"))
    for i in range(12):
        ctx.add("assistant", f"a{i} " + "r" * 3200)
    maybe_compact(ctx, "", est, CFG, Session(workdir, CFG), 1, summarise=None)
    assert context_tokens(ctx, "", est) <= CFG.limit
    assert ctx.blocks[0].role == "user" and ctx.blocks[-1].body.startswith("a11")
