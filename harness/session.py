from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import PRICES, Config
from .context import Block, parse, render_blocks


@dataclass
class Usage:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0

    @property
    def prompt_total(self) -> int:
        return self.input + self.cache_read + self.cache_write

    def cost(self) -> float:
        return (
            self.input * PRICES["input"]
            + self.output * PRICES["output"]
            + self.cache_read * PRICES["cache_read"]
            + self.cache_write * PRICES["cache_write"]
        ) / 1_000_000

    def add(self, other: "Usage") -> None:
        self.input += other.input
        self.output += other.output
        self.cache_read += other.cache_read
        self.cache_write += other.cache_write


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _append_event(path: Path, type: str, turn: int, fields: dict) -> None:
    line = json.dumps({"ts": _now(), "turn": turn, "type": type, **fields}, ensure_ascii=False)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(line + "\n")


class Session:
    """On-disk record of one run. Nothing written here is ever modified or deleted."""

    def __init__(self, workdir: Path, cfg: Config):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        self.id = f"{stamp}-{secrets.token_hex(2)}"
        self.dir = Path(workdir) / ".ctx" / "sessions" / self.id
        for sub in ("blocks", "outputs", "snapshots", "state"):
            (self.dir / sub).mkdir(parents=True, exist_ok=True)
        self.ctx_path = self.dir / "LIVE_CTX.md"
        self.transcript = self.dir / "transcript.jsonl"
        self.usage = Usage()
        self.stats: dict[str, int] = {}

    def event(self, type: str, turn: int, **fields) -> None:
        _append_event(self.transcript, type, turn, fields)

    def bump(self, name: str, n: int = 1) -> None:
        self.stats[name] = self.stats.get(name, 0) + n

    def save_block(self, b: Block) -> None:
        """Keep the original body of a block. Written once, so later edits never touch it."""
        path = self.dir / "blocks" / f"{b.id}.txt"
        if not path.exists():
            path.write_text(b.body, encoding="utf-8", newline="\n")

    def snapshot(self, turn: int, blocks_before: list[Block]) -> None:
        path = self.dir / "snapshots" / f"turn-{turn:04d}.json"
        data = {"turn": turn, "blocks": [asdict(b) for b in blocks_before]}
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8", newline="\n")

    def add_usage(self, usage: Usage) -> None:
        self.usage.add(usage)

    def write_usage(self, status: str) -> None:
        data = {
            "status": status,
            "dollars": round(self.usage.cost(), 6),
            "tokens": asdict(self.usage),
            **self.stats,
        }
        (self.dir / "usage.json").write_text(
            json.dumps(data, indent=2), encoding="utf-8", newline="\n"
        )


def undo(session_dir: Path) -> int:
    """Restore the context file to how it was before the last accepted edit.

    Blocks created after that edit are kept. Returns the turn that was undone.
    """
    session_dir = Path(session_dir)
    snapshots = sorted((session_dir / "snapshots").glob("turn-*.json"))
    if not snapshots:
        raise FileNotFoundError("no accepted edit to undo in this session")
    data = json.loads(snapshots[-1].read_text(encoding="utf-8"))
    restored = [Block(**b) for b in data["blocks"]]
    last_seq = max((b.seq for b in restored), default=0)

    ctx_path = session_dir / "LIVE_CTX.md"
    if ctx_path.exists():
        for bid, role, body in parse(ctx_path.read_text(encoding="utf-8")):
            seq = int(bid[1:]) if bid[1:].isdigit() else 0
            if seq > last_seq:
                restored.append(Block(bid, role, body, seq))
    ctx_path.write_text(render_blocks(restored), encoding="utf-8", newline="\n")
    _append_event(session_dir / "transcript.jsonl", "undo", data["turn"], {"blocks": len(restored)})
    return data["turn"]
