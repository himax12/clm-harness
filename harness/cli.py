from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .session import undo


def _session_dir(arg: str, workdir: Path) -> Path:
    """Accept a path to a session directory, or a session id under workdir/.ctx/sessions."""
    p = Path(arg)
    if p.is_dir():
        return p
    p = workdir / ".ctx" / "sessions" / arg
    if p.is_dir():
        return p
    raise SystemExit(f"session not found: {arg}")


def cmd_log(args: argparse.Namespace) -> int:
    path = _session_dir(args.session, Path(args.dir)) / "transcript.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        turn, kind = e["turn"], e["type"]
        if kind == "start":
            print(f"task: {e['task'][:100]}  (mode={e['mode']}, limit={e['limit']:,})")
        elif kind == "reply":
            command = " ".join((e.get("command") or "(no command)").split())[:60]
            print(f"{turn:>4}  ctx={e['context_tokens']:>7,}  $ {command}")
        elif kind == "edit_applied":
            print(f"      edit applied: {e['before_tokens']:,} -> {e['after_tokens']:,} tokens "
                  f"(re-read {e['reread_tokens']:,})")
        elif kind == "edit_refused":
            print(f"      edit REFUSED: {e['reason']}")
        elif kind == "rollback":
            print(f"{turn:>4}  rollback: dropped {len(e['dropped'])} blocks, "
                  f"{e['tokens_before']:,} -> {e['tokens_after']:,}")
        elif kind == "notice":
            print(f"      notice: {e['text'][:80]}")
        elif kind == "finish":
            print(f"finished: {e['status']}")
    return 0


def cmd_undo(args: argparse.Namespace) -> int:
    turn = undo(_session_dir(args.session, Path(args.dir)))
    print(f"restored the context from before the edit at turn {turn}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    print("`harness run` needs the live model call, which is Phase 2 and not built yet.",
          file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="harness",
        description="A bash-only coding agent whose model manages its own context file.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="run a task (Phase 2)")
    p.add_argument("task")
    p.add_argument("--dir", default=".")
    p.add_argument("--mode", choices=("clm", "baseline"), default="clm")
    p.add_argument("--budget", type=int)
    p.add_argument("--confirm", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("log", help="print a turn-by-turn summary of a session")
    p.add_argument("session")
    p.add_argument("--dir", default=".")
    p.set_defaults(func=cmd_log)

    p = sub.add_parser("undo", help="restore the context from before the last accepted edit")
    p.add_argument("session")
    p.add_argument("--dir", default=".")
    p.set_defaults(func=cmd_undo)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
