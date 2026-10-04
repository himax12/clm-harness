from __future__ import annotations

from typing import Callable

from .budget import Estimator, context_tokens
from .config import Config
from .context import Block, Context, render_block
from .session import Session, Usage

CLEARED = "[Old tool output cleared]"
TRIGGER = 0.80  # of the limit
PROTECT = 0.40  # of the budget: the newest tokens whose outputs are never cleared
KEEP_TAIL = 6  # newest blocks left out of summarisation

Summariser = Callable[[str], tuple[str, Usage]]


def make_compactor(summarise: Summariser | None) -> Callable:
    def compactor(ctx, system, est, cfg, session, turn):
        maybe_compact(ctx, system, est, cfg, session, turn, summarise)

    return compactor


def maybe_compact(
    ctx: Context,
    system: str,
    est: Estimator,
    cfg: Config,
    session: Session,
    turn: int,
    summarise: Summariser | None = None,
) -> None:
    """Ordinary harness-driven compaction: clear old outputs, then summarise, then drop.

    The comparison point for the model-managed mode. Runs before each model call.
    """
    trigger = TRIGGER * cfg.limit

    def size() -> int:
        return context_tokens(ctx, system, est)

    def log(stage: str, before: int) -> None:
        session.bump(f"compact_{stage}")
        session.event("compact", turn, stage=stage, tokens_before=before, tokens_after=size())

    before = size()
    if before <= trigger:
        return

    # 1. Clear the bodies of old command outputs, leaving the newest ones alone.
    protect = PROTECT * cfg.budget_tokens
    newer, cleared = 0, False
    for b in reversed(ctx.blocks):
        if newer > protect and b.role == "output" and b.body != CLEARED:
            b.body = CLEARED
            cleared = True
        newer += est.tokens(render_block(b))
    if cleared:
        log("clear", before)
    if size() <= trigger:
        return

    # 2. Replace everything but the newest blocks and the user's messages with a summary.
    head = [b for b in ctx.blocks[:-KEEP_TAIL] if not b.protected]
    if summarise and len(head) >= 2:
        before = size()
        record = "\n\n".join(f"[{b.role}]\n{b.body}" for b in ctx.blocks[:-KEEP_TAIL])
        summary, usage = summarise(f"TASK\n{ctx.pinned}\n\nRECORD\n{record}")
        session.add_usage(usage)
        at = ctx.blocks.index(head[0])
        gone = {b.id for b in head}
        ctx.blocks = [b for b in ctx.blocks if b.id not in gone]
        text = summary.strip() or "(no summary available)"
        note = ctx.add("note", f"[Summary of earlier work]\n{text}")
        ctx.blocks.insert(at, ctx.blocks.pop())
        session.save_block(note)
        log("summarise", before)

    # 3. Last resort: drop the oldest blocks until the context fits.
    before = size()
    dropped = False
    while size() > cfg.limit:
        victim: Block | None = next((b for b in ctx.blocks if not b.protected), None)
        if victim is None:
            break
        ctx.blocks.remove(victim)
        dropped = True
    if dropped:
        log("drop", before)
