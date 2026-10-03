from __future__ import annotations

import math

from .config import Config
from .context import Block, Context, raw_tokens, render_block


class Estimator:
    """Characters / 4, scaled by a ratio calibrated against the API's own count."""

    def __init__(self) -> None:
        self.ratio = 1.0

    def scale(self, raw: int) -> int:
        return math.ceil(raw * self.ratio)

    def tokens(self, text: str) -> int:
        return self.scale(raw_tokens(text))

    def calibrate(self, api_prompt_total: int, raw_request: int) -> None:
        if api_prompt_total <= 0 or raw_request <= 0:
            return
        self.ratio = min(3.0, max(0.5, api_prompt_total / raw_request))


def raw_context(ctx: Context, system: str, blocks: list[Block] | None = None) -> int:
    blocks = ctx.blocks if blocks is None else blocks
    return (
        raw_tokens(system)
        + raw_tokens(ctx.pinned)
        + raw_tokens(ctx.rollback_note or "")
        + sum(raw_tokens(render_block(b)) for b in blocks)
    )


def context_tokens(
    ctx: Context, system: str, est: Estimator, blocks: list[Block] | None = None
) -> int:
    """Calibrated size of the whole request: system, pinned task, note and blocks."""
    return est.scale(raw_context(ctx, system, blocks))


_TIER_TEXT = {
    0.25: (
        "Context is at about 25% of the limit. No action needed. "
        "Make sure your tracker records what you have already tried."
    ),
    0.50: (
        "Context is at about 50% of the limit. "
        "Finish the unit of work in flight, then tidy once."
    ),
    0.75: (
        "Context is at about 75% of the limit. Compact settled spans now, but do not wipe: "
        "shorten stale output in place and copy exact facts forward."
    ),
}


class Nudger:
    def __init__(self) -> None:
        self.fired: set[float] = set()

    def decide(self, tokens: int, recent_outputs: list[int], cfg: Config) -> str | None:
        limit = cfg.limit
        # Re-arm any tier the context has dropped back below.
        self.fired = {t for t in self.fired if tokens >= t * limit}

        need = min(max(0.10 * limit, 2 * max(recent_outputs[-3:], default=0)), 0.50 * limit)
        if limit - tokens < need:
            return (
                f"Context is at {tokens:,} / {limit:,} tokens and about to overflow. "
                "Compact this turn and do nothing else, or your newest turns will be rolled back."
            )

        crossed = [t for t in cfg.nudge_tiers if tokens >= t * limit and t not in self.fired]
        if not crossed:
            return None
        tier = max(crossed)
        self.fired.update(t for t in cfg.nudge_tiers if t <= tier)
        pct = int(tier * 100)
        return _TIER_TEXT.get(tier, f"Context is at about {pct}% of the limit.")


def rollback(
    ctx: Context, system: str, est: Estimator, cfg: Config, consecutive: int, attempt: int
) -> list[Block]:
    """Drop the newest droppable blocks until the context fits, and pin a note about it.

    Returns the dropped blocks; empty means nothing could be dropped.
    """
    margin = cfg.rollback_margin
    if consecutive > 3:
        margin = min(margin * (consecutive - 3), int(0.75 * cfg.limit))
    target = cfg.limit - margin

    dropped: list[Block] = []
    while context_tokens(ctx, system, est) > target:
        idx = next(
            (i for i in range(len(ctx.blocks) - 1, -1, -1) if ctx.blocks[i].droppable),
            None,
        )
        if idx is None:
            break
        dropped.append(ctx.blocks.pop(idx))
    if not dropped:
        return dropped

    commands: list[str] = []
    for b in dropped:  # newest first
        if b.command:
            short = " ".join(b.command.split())[:70]
            if short not in commands:
                commands.append(short)
        if len(commands) == 5:
            break
    lines = [
        f"[CONTEXT LIMIT HIT, retry {attempt}/{cfg.max_rollbacks}] "
        f"Your newest {len(dropped)} blocks were rolled back and are gone.",
        "Condense your context this turn and do nothing else.",
    ]
    if commands:
        lines.append(
            "These commands already ran and their output is what overflowed; do not re-run "
            "them unchanged. If you need one, make it print far less (head, grep, count):"
        )
        lines.extend(f"  - {c}" for c in commands)
    ctx.rollback_note = "\n".join(lines)
    return dropped
