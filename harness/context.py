from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Callable

FIRST_LINE = "[[CTX v1]]"
HEADER_RE = re.compile(
    r"^\[\[BLOCK id=([A-Za-z0-9_-]+) role=([a-z]+)(?: tokens=\d+)?\]\]\s*$",
    re.MULTILINE,
)
_HEADER_LIKE = re.compile(r"^\[\[(BLOCK|CTX) ", re.MULTILINE)


class ParseError(Exception):
    pass


def raw_tokens(text: str) -> int:
    """Uncalibrated estimate. Stable from turn to turn, so safe to print in headers."""
    return math.ceil(len(text) / 4)


def _sanitise(body: str) -> str:
    # A body line that looks like a header (e.g. a command printed the context
    # file) would be parsed as a real header after the next edit.
    return _HEADER_LIKE.sub(r"[ [\1 ", body)


@dataclass
class Block:
    id: str
    role: str  # assistant | output | user | input | notice | note
    body: str
    seq: int
    command: str | None = None  # assistant blocks only; survives edits to the body

    @property
    def protected(self) -> bool:
        """The model may not change or remove it."""
        return self.role == "user"

    @property
    def droppable(self) -> bool:
        """Rollback may discard it. Task input is editable by the model but never
        dropped by the harness, since dropping it would silently lose part of the task."""
        return self.role not in ("user", "input")


class Context:
    def __init__(self, pinned: str):
        self.pinned = pinned  # the task; never in the file
        self.rollback_note: str | None = None  # never in the file
        self.blocks: list[Block] = []
        self._seq = 0

    def add(self, role: str, body: str, command: str | None = None) -> Block:
        self._seq += 1
        block = Block(f"b{self._seq:04d}", role, _sanitise(body.strip()), self._seq, command)
        self.blocks.append(block)
        return block


def render_block(b: Block) -> str:
    return f"[[BLOCK id={b.id} role={b.role} tokens={raw_tokens(b.body)}]]\n{b.body}"


def render_blocks(blocks: list[Block]) -> str:
    return FIRST_LINE + "\n" + "\n\n".join(render_block(b) for b in blocks) + "\n"


def render(ctx: Context) -> str:
    return render_blocks(ctx.blocks)


def parse(text: str) -> list[tuple[str, str, str]]:
    """Return (id, role, body) per block, in file order."""
    text = text.replace("\r\n", "\n")
    first, _, rest = text.partition("\n")
    if first.rstrip() != FIRST_LINE:
        raise ParseError(f"line 1 was changed; it must stay exactly {FIRST_LINE}")
    matches = list(HEADER_RE.finditer(rest))
    if not matches:
        raise ParseError(
            "no block headers found; replacing the whole context with plain text is not allowed"
        )
    if rest[: matches[0].start()].strip():
        raise ParseError("text found before the first block header")
    out = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(rest)
        out.append((m.group(1), m.group(2), rest[m.end() : end].strip()))
    return out


@dataclass
class EditResult:
    status: str  # "unchanged" | "applied" | "refused"
    reason: str
    before_tokens: int
    after_tokens: int
    first_changed: int | None = None
    removed_ids: list[str] = field(default_factory=list)


def apply_edit(
    ctx: Context,
    rendered: str,
    file_text: str,
    limit: int,
    count: Callable[[list[Block]], int],
) -> EditResult:
    """Validate the edited file against the context and commit it, or refuse it whole.

    `count` returns the full context size (overhead included) for a block list.
    Nothing in `ctx` is mutated unless the result is "applied".
    """
    file_text = file_text.replace("\r\n", "\n")
    before = count(ctx.blocks)
    if file_text.strip() == rendered.strip():
        return EditResult("unchanged", "", before, before)

    def refuse(reason: str) -> EditResult:
        return EditResult("refused", reason, before, before)

    try:
        parsed = parse(file_text)
    except ParseError as e:
        return refuse(str(e))

    by_id = {b.id: b for b in ctx.blocks}
    seen: set[str] = set()
    candidate: list[Block] = []
    seq = ctx._seq
    for bid, _role, body in parsed:  # the role written in the header is ignored
        if bid in seen:
            return refuse(f"duplicate block id {bid}")
        seen.add(bid)
        if bid.startswith("new-"):
            if body:
                seq += 1
                candidate.append(Block(f"b{seq:04d}", "note", _sanitise(body), seq))
        elif bid in by_id:
            old = by_id[bid]
            if old.protected and body != old.body:
                return refuse(f"block {bid} is a user message and cannot be changed")
            if body:  # an emptied block is dropped
                candidate.append(Block(old.id, old.role, _sanitise(body), old.seq, old.command))
        else:
            return refuse(f"unknown block id {bid}; use an existing id, or new-<name> for a note")
    for b in ctx.blocks:
        if b.protected and b.id not in seen:
            return refuse(f"block {b.id} is a user message and cannot be removed")

    same = len(candidate) == len(ctx.blocks) and all(
        c.id == o.id and c.body == o.body for c, o in zip(candidate, ctx.blocks)
    )
    if same:
        return EditResult("unchanged", "", before, before)

    after = count(candidate)
    if after > limit and after >= before:
        return refuse(
            f"the result is {after:,} tokens, over the {limit:,} limit, and no smaller than before"
        )

    first_changed = next(
        (
            i
            for i, (c, o) in enumerate(zip(candidate, ctx.blocks))
            if c.id != o.id or c.body != o.body
        ),
        min(len(candidate), len(ctx.blocks)),
    )
    kept = {c.id for c in candidate}
    removed = [b.id for b in ctx.blocks if b.id not in kept]
    ctx.blocks = candidate
    ctx._seq = seq
    return EditResult("applied", "", before, after, first_changed, removed)


def receipt(edit: EditResult | None, n_blocks: int, limit: int, touched: bool) -> str:
    """The line appended to a command result telling the model what its edit did."""
    if edit is None:
        return ""
    if edit.status == "refused":
        return f"[context edit REFUSED: {edit.reason}. Your context is unchanged.]"
    if edit.status == "applied":
        change = f"{edit.before_tokens:,} -> {edit.after_tokens:,} tokens"
        if edit.after_tokens > limit:
            return f"[context edit applied: {change}, still over the limit. Compact further now.]"
        if edit.after_tokens > edit.before_tokens:
            return (
                f"[context edit applied but it GREW: {change}. If you meant to condense, "
                "you duplicated content instead of replacing it.]"
            )
        return f"[context edit applied: {change}, {n_blocks} blocks]"
    if touched:
        return (
            "[context file unchanged: your edit matched nothing. "
            "Headers look like [[BLOCK id=b0007 role=output tokens=N]].]"
        )
    return ""
