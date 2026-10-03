from harness.budget import Estimator, Nudger, context_tokens, rollback
from harness.config import Config

from conftest import make_ctx

CFG = Config(budget_tokens=12_048)  # limit 10,000


def test_limit_and_call_cap():
    cfg = Config()
    assert cfg.limit == 29_952 and cfg.lm_call_cap == 152


def test_calibration_scales_and_is_clamped():
    est = Estimator()
    assert est.tokens("x" * 400) == 100
    est.calibrate(1500, 1000)
    assert est.tokens("x" * 400) == 150
    est.calibrate(100_000, 1000)
    assert est.ratio == 3.0
    est.calibrate(1, 1000)
    assert est.ratio == 0.5
    est.calibrate(0, 1000)  # a model that reports no usage leaves the ratio alone
    assert est.ratio == 0.5


def test_context_tokens_counts_system_task_note_and_blocks(est):
    ctx = make_ctx(("output", "x" * 400))
    base = context_tokens(ctx, "s" * 40, est)
    ctx.rollback_note = "n" * 40
    assert context_tokens(ctx, "s" * 40, est) == base + 10
    assert context_tokens(ctx, "s" * 40, est, blocks=[]) < base


def test_each_tier_fires_once():
    n = Nudger()
    assert n.decide(1000, [], CFG) is None
    assert "25%" in n.decide(2600, [], CFG)
    assert n.decide(2700, [], CFG) is None
    assert "50%" in n.decide(5100, [], CFG)
    assert n.decide(5200, [], CFG) is None


def test_jumping_past_two_tiers_fires_only_the_higher():
    n = Nudger()
    assert "50%" in n.decide(5100, [], CFG)
    assert n.decide(5200, [], CFG) is None  # 25% was marked fired too


def test_tier_rearms_after_the_context_shrinks():
    n = Nudger()
    assert "50%" in n.decide(5100, [], CFG)
    assert n.decide(2000, [], CFG) is None
    assert "50%" in n.decide(5100, [], CFG)


def test_lowest_tier_carries_no_how_to():
    text = Nudger().decide(2600, [], CFG)
    assert "No action needed" in text and "compact" not in text.lower()


def test_urgent_fires_every_turn_near_the_limit():
    n = Nudger()
    assert "about to overflow" in n.decide(9500, [], CFG)
    assert "about to overflow" in n.decide(9500, [], CFG)


def test_urgent_threshold_follows_recent_output_size():
    n = Nudger()
    assert "about to overflow" not in (n.decide(7600, [100], CFG) or "")
    assert "about to overflow" in Nudger().decide(7600, [1500], CFG)  # needs 3000 of room


def big_ctx():
    ctx = make_ctx(("user", "op one"))
    for i in range(6):
        ctx.add("assistant", f"$ cmd-{i}", command=f"cmd-{i}   --flag")
        ctx.add("output", "o" * 8000)  # 2000 tokens each
    return ctx


def test_rollback_drops_newest_until_under_the_margin(est):
    ctx = big_ctx()
    assert context_tokens(ctx, "", est) > CFG.limit
    dropped = rollback(ctx, "", est, CFG, consecutive=1, attempt=1)
    assert dropped and dropped[0].id == "b0013"  # newest first
    assert context_tokens(ctx, "", est) <= CFG.limit - CFG.rollback_margin
    assert ctx.blocks[0].role == "user"


def test_rollback_note_lists_dropped_commands(est):
    ctx = big_ctx()
    rollback(ctx, "", est, CFG, consecutive=1, attempt=2)
    note = ctx.rollback_note
    assert "retry 2/6" in note and "rolled back" in note
    assert "  - cmd-5 --flag" in note  # whitespace collapsed
    assert note.count("  - ") <= 5


def test_rollback_never_drops_user_blocks(est):
    ctx = make_ctx(("user", "u" * 60_000), ("output", "small"))
    dropped = rollback(ctx, "", est, CFG, consecutive=1, attempt=1)
    assert [b.role for b in dropped] == ["output"]
    assert [b.role for b in ctx.blocks] == ["user"]


def test_rollback_with_nothing_droppable_returns_empty(est):
    ctx = make_ctx(("user", "u" * 60_000))
    assert rollback(ctx, "", est, CFG, consecutive=1, attempt=1) == []
    assert ctx.rollback_note is None


def test_margin_grows_after_repeated_rollbacks(est):
    first, later = big_ctx(), big_ctx()
    rollback(first, "", est, CFG, consecutive=1, attempt=1)
    rollback(later, "", est, CFG, consecutive=5, attempt=5)
    assert context_tokens(later, "", est) < context_tokens(first, "", est)
