from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .env import load_dotenv
from .redact import dotenv_files
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


def _claude(cfg):
    from .llm import ClaudeModel  # imported late so `log` and `undo` work without credentials

    return ClaudeModel(cfg)


def cmd_run(args: argparse.Namespace) -> int:
    from .baseline import make_compactor
    from .config import Config
    from .loop import run

    overrides = {"mode": args.mode, "confirm": args.confirm, "allow_push": args.allow_push,
                 "env_passthrough": tuple(args.pass_env or ())}
    if args.budget:
        overrides["budget_tokens"] = args.budget
    if args.max_steps:
        overrides["max_steps"] = args.max_steps
    if args.max_cost:
        overrides["max_cost_usd"] = args.max_cost
    cfg = Config(**overrides)
    try:
        model = _claude(cfg)
    except Exception as e:
        print(f"could not create the Claude client: {e}", file=sys.stderr)
        print("Set ANTHROPIC_API_KEY and retry.", file=sys.stderr)
        return 2
    for path in dotenv_files(Path(args.dir)):
        print(f"warning: {path} holds secrets the agent could read. Its values are redacted "
              "from command output, but a command can still open the file. Use --confirm, or "
              "work in a folder without it.", file=sys.stderr)
    compactor = make_compactor(model.summarise) if cfg.mode == "baseline" else None
    result = run(args.task, Path(args.dir), cfg, model, compactor=compactor)
    print(result.answer)
    if "authentication method" in result.answer:
        print("No Anthropic credential found. Put ANTHROPIC_API_KEY in the project's .env file "
              "(see .env.example) or in your environment, then retry.", file=sys.stderr)
    print(f"[{result.status}] ${result.usage.cost():.4f}  session: {result.session_dir}",
          file=sys.stderr)
    return 0 if result.status == "finished" else 1


def cmd_doctor(args: argparse.Namespace) -> int:
    """Check that a run can start: shell, scripting tool, credential. Spends nothing."""
    import os
    import tempfile

    from .config import Config
    from .redact import removed_names
    from .shell import Shell, find_bash

    ok = True

    def report(good: bool, label: str, detail: str) -> None:
        nonlocal ok
        ok = ok and good
        print(f"{'ok  ' if good else 'FAIL'}  {label}: {detail}")

    cfg = Config()
    report(sys.version_info >= (3, 12), "python", sys.version.split()[0])
    try:
        bash = find_bash()
        report(True, "bash", bash)
        with tempfile.TemporaryDirectory() as tmp:
            hint = Shell(Path(tmp), Path(tmp) / "session", cfg).scripting_hint()
        report(True, "scripting tool for context edits", hint.replace("`", ""))
    except Exception as e:
        report(False, "bash", str(e))

    source = next((n for n in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN") if os.environ.get(n)),
                  None)
    report(source is not None, "credential", f"found in {source}" if source
           else "not set; put ANTHROPIC_API_KEY in .env (see .env.example)")
    if source and not args.offline:
        try:
            import anthropic

            # Token counting validates the key and the model id and costs nothing.
            anthropic.Anthropic().messages.count_tokens(
                model=cfg.model, messages=[{"role": "user", "content": "ping"}])
            report(True, "API", f"key accepted; model {cfg.model} available")
        except Exception as e:
            report(False, "API", f"{type(e).__name__}: {str(e)[:160]}")

    removed = removed_names()
    print(f"info  {len(removed)} secret-looking environment variables are hidden from the "
          "agent's commands" + (f": {', '.join(removed)}" if removed else ""))
    for path in dotenv_files(Path(args.dir)):
        print(f"warn  {path} is readable by the agent if you run it in this folder")
    return 0 if ok else 1


def cmd_bench(args: argparse.Namespace) -> int:
    from bench.run import report, run_matrix

    out = Path(args.out)
    run_matrix(
        tasks=args.tasks.split(","), modes=args.modes.split(","),
        seeds=[int(s) for s in args.seeds.split(",")], pressure=args.pressure,
        ceiling_usd=args.ceiling, out_dir=out, make_model=_claude,
        max_cost_per_run=args.max_cost,
    )
    print(report(out / "results.csv"))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from bench.run import report

    print(report(Path(args.csv)))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="harness",
        description="A bash-only coding agent whose model manages its own context file.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser(
        "run", help="run a task with Claude",
        epilog="The agent runs shell commands unattended with your permissions. A short list "
               "of destructive commands is refused, but this is not a sandbox. Read SAFETY.md "
               "before pointing it at anything you care about.",
    )
    p.add_argument("task")
    p.add_argument("--dir", default=".", help="directory to work in")
    p.add_argument("--mode", choices=("clm", "baseline"), default="clm")
    p.add_argument("--budget", type=int, help="context budget in tokens (default 32000)")
    p.add_argument("--max-steps", type=int)
    p.add_argument("--max-cost", type=float, help="stop the run at this many dollars")
    p.add_argument("--confirm", action="store_true", help="approve each command first")
    p.add_argument("--allow-push", action="store_true", help="let the agent run `git push`")
    p.add_argument("--pass-env", action="append", metavar="NAME",
                   help="let the agent's commands see this secret-looking variable (repeatable)")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("doctor", help="check the shell and the API credential; spends nothing")
    p.add_argument("--dir", default=".", help="folder you intend to run in")
    p.add_argument("--offline", action="store_true", help="skip the API check")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("bench", help="run the benchmark matrix")
    p.add_argument("--tasks", default="kv,ledger")
    p.add_argument("--modes", default="clm,baseline")
    p.add_argument("--seeds", default="1,2,3")
    p.add_argument("--pressure", type=float, default=3.0,
                   help="total input as a multiple of the context budget")
    p.add_argument("--ceiling", type=float, required=True,
                   help="total dollars the whole matrix may spend")
    p.add_argument("--max-cost", type=float, default=8.0, help="dollar cap per run")
    p.add_argument("--out", default="bench_out")
    p.set_defaults(func=cmd_bench)

    p = sub.add_parser("report", help="summarise a benchmark results.csv")
    p.add_argument("csv")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("log", help="print a turn-by-turn summary of a session")
    p.add_argument("session")
    p.add_argument("--dir", default=".")
    p.set_defaults(func=cmd_log)

    p = sub.add_parser("undo", help="restore the context from before the last accepted edit")
    p.add_argument("session")
    p.add_argument("--dir", default=".")
    p.set_defaults(func=cmd_undo)

    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # the model's answers are not always cp1252
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    load_dotenv()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
