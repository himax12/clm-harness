from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

from .env import load_dotenv
from .redact import dotenv_files
from .session import undo


_BASH_HINT = {
    "Windows": "Install it with `winget install Git.Git`, or use --sandbox docker.",
}
_DOCKER_HINT = {
    "Windows": "Install Docker Desktop: `winget install Docker.DockerDesktop`.",
    "Darwin": "Install Docker Desktop: `brew install --cask docker`.",
    "Linux": "Install Docker Engine: https://docs.docker.com/engine/install/",
}


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
            failed = e["status"] != "finished" and e.get("answer")
            detail = f" ({e['answer']})" if failed else ""
            print(f"finished: {e['status']}{detail}")
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
    from .config import TESTED_MODELS, Config, prices_for
    from .loop import run

    if args.task_file:
        task = (sys.stdin.read() if args.task_file == "-"
                else Path(args.task_file).read_text(encoding="utf-8")).strip()
    else:
        task = (args.task or "").strip()
    if not task:
        print("no task given: pass it as an argument, or use --task-file PATH (or - for stdin)",
              file=sys.stderr)
        return 2

    overrides = {"mode": args.mode, "confirm": args.confirm, "allow_push": args.allow_push,
                 "env_passthrough": tuple(args.pass_env or ()), "sandbox": args.sandbox,
                 "sandbox_network": args.allow_net}
    for flag, field in (("budget", "budget_tokens"), ("max_steps", "max_steps"),
                        ("max_cost", "max_cost_usd"), ("model", "model"), ("effort", "effort"),
                        ("timeout", "command_timeout"), ("sandbox_image", "sandbox_image")):
        if getattr(args, flag) is not None:
            overrides[field] = getattr(args, flag)
    try:
        cfg = Config(**overrides)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    if cfg.model not in TESTED_MODELS:
        known = prices_for(cfg.model)[1]
        print(f"warning: {cfg.model} is untested; the request was built for "
              f"{', '.join(TESTED_MODELS)} and may be rejected."
              + ("" if known else " Its prices are unknown, so costs are shown at Opus 5.5 rates."),
              file=sys.stderr)
    try:
        model = _claude(cfg)
    except Exception as e:
        print(f"could not create the Claude client: {e}", file=sys.stderr)
        print("Set ANTHROPIC_API_KEY and retry.", file=sys.stderr)
        return 2
    if cfg.sandbox == "docker":
        from .sandbox import docker_status

        usable, detail = docker_status()
        if not usable:
            print(f"the sandbox cannot start: {detail}", file=sys.stderr)
            return 2
    else:
        from .shell import find_bash

        try:
            find_bash()
        except RuntimeError as e:
            print(f"{e} {_BASH_HINT.get(platform.system(), '')}".strip(), file=sys.stderr)
            return 2
        for path in dotenv_files(Path(args.dir)):
            print(f"warning: {path} holds secrets the agent could read. Its values are redacted "
                  "from command output, but a command can still open the file. Use --confirm, "
                  "--sandbox docker, or work in a folder without it.", file=sys.stderr)
    compactor = make_compactor(model.summarise) if cfg.mode == "baseline" else None
    progress = None if args.quiet else (lambda line: print(line, file=sys.stderr, flush=True))
    result = run(task, Path(args.dir), cfg, model, compactor=compactor, progress=progress)
    if args.json:
        print(json.dumps({"status": result.status, "answer": result.answer,
                          "dollars": round(result.dollars, 4),
                          "session_dir": str(result.session_dir)}, ensure_ascii=False))
    else:
        print(result.answer)
    if "authentication method" in result.answer:
        print("No Anthropic credential found. Put ANTHROPIC_API_KEY in the project's .env file "
              "(see .env.example) or in your environment, then retry.", file=sys.stderr)
    print(f"[{result.status}] ${result.dollars:.4f}  session: {result.session_dir}",
          file=sys.stderr)
    return 0 if result.status == "finished" else 1


def cmd_sessions(args: argparse.Namespace) -> int:
    root = Path(args.dir) / ".ctx" / "sessions"
    dirs = sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    if not dirs:
        print(f"no sessions under {root}")
        return 0
    for d in dirs:
        status, dollars, task = "unfinished", "", ""
        usage = d / "usage.json"
        if usage.exists():
            data = json.loads(usage.read_text(encoding="utf-8"))
            status, dollars = data.get("status", "?"), f"${data.get('dollars', 0):.2f}"
        transcript = d / "transcript.jsonl"
        if transcript.exists():
            with transcript.open(encoding="utf-8") as f:
                first = f.readline()
            if first:
                task = " ".join(json.loads(first).get("task", "").split())[:60]
        print(f"{d.name}  {status:<17} {dollars:>7}  {task}")
    return 0


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

    from .env import user_env_file
    from .sandbox import docker_status

    cfg = Config()
    docker_ok, docker_detail = docker_status()
    print(f"info  system: {platform.system()} {platform.release()} ({platform.machine()})")
    report(sys.version_info >= (3, 10), "python", sys.version.split()[0])
    try:
        bash = find_bash()
        report(True, "bash", bash)
        with tempfile.TemporaryDirectory() as tmp:
            hint = Shell(Path(tmp), Path(tmp) / "session", cfg).scripting_hint()
        report(True, "scripting tool for context edits", hint.replace("`", ""))
    except Exception as e:
        if docker_ok:
            # In the sandbox the commands run in the container; the host needs no bash.
            print(f"info  bash: not found on this machine ({e}) Runs need --sandbox docker.")
        else:
            report(False, "bash", f"{e} {_BASH_HINT.get(platform.system(), '')}".strip())

    source = next((n for n in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN") if os.environ.get(n)),
                  None)
    report(source is not None, "credential", f"found in {source}" if source
           else f"not set; run `harness setup`, or put ANTHROPIC_API_KEY in {user_env_file()}")
    if source and not args.offline:
        try:
            from .llm import check_credential  # the only module that imports the SDK

            check_credential(cfg.model)
            report(True, "API", f"key accepted; model {cfg.model} available")
        except Exception as e:
            report(False, "API", f"{type(e).__name__}: {str(e)[:160]}")

    removed = removed_names()
    print(f"info  {len(removed)} secret-looking environment variables are hidden from the "
          "agent's commands" + (f": {', '.join(removed)}" if removed else ""))
    for path in dotenv_files(Path(args.dir)):
        print(f"warn  {path} is readable by the agent if you run it in this folder "
              "without --sandbox docker")
    if docker_ok:
        print(f"info  sandbox: {docker_detail}")
    else:
        print(f"info  sandbox: {docker_detail}; --sandbox docker will not work. "
              + _DOCKER_HINT.get(platform.system(), ""))
    return 0 if ok else 1


def cmd_setup(args: argparse.Namespace) -> int:
    """Save the API key where an installed harness will find it."""
    import getpass

    from .env import save_user_key

    if args.key_stdin or not sys.stdin.isatty():
        key = sys.stdin.readline().strip()
    else:
        print("Paste your Anthropic API key (https://console.anthropic.com/settings/keys).")
        key = getpass.getpass("API key (input is hidden): ").strip()
    if not key:
        print("no key given; nothing was saved", file=sys.stderr)
        return 2
    if not args.offline:
        import os

        from .config import Config

        previous = os.environ.get("ANTHROPIC_API_KEY")
        os.environ["ANTHROPIC_API_KEY"] = key
        try:
            from .llm import check_credential

            check_credential(Config().model)  # free: counts tokens only
        except Exception as e:
            print(f"the key was not accepted: {type(e).__name__}: {str(e)[:160]}", file=sys.stderr)
            print("Nothing was saved. Use --offline to save it without checking.", file=sys.stderr)
            return 1
        finally:
            if previous is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = previous
    path = save_user_key("ANTHROPIC_API_KEY", key)
    print(f"saved to {path}" + ("" if args.offline else " (the key was accepted)"))
    print("Next: harness doctor")
    return 0


def cmd_hostctx(args: argparse.Namespace) -> int:
    """For plug-ins in other languages: one JSON request on stdin, one JSON reply on stdout."""
    from .hostctx import run_json

    try:
        reply = run_json(json.loads(sys.stdin.read()))
    except (ValueError, KeyError, TypeError) as e:
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}))
        return 2
    print(json.dumps(reply, ensure_ascii=False))
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    """Serve the Model Context Protocol on stdin and stdout until stdin closes."""
    from .mcp import serve

    serve(sys.stdin.buffer, sys.stdout.buffer)
    return 0


def cmd_bench(args: argparse.Namespace) -> int:
    from clm_harness.bench.run import report, run_matrix

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
    from clm_harness.bench.run import report

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
        epilog="Without --sandbox docker the agent runs shell commands unattended with your "
               "permissions. A short list of destructive commands is refused, but that is not "
               "a sandbox. Read SAFETY.md before pointing it at anything you care about.",
    )
    p.add_argument("task", nargs="?", help="what to do (or use --task-file)")
    p.add_argument("--task-file", metavar="PATH", help="read the task from a file, or - for stdin")
    p.add_argument("--dir", default=".", help="directory to work in")
    p.add_argument("--mode", choices=("clm", "baseline"), default="clm",
                   help="clm: the model edits its own context; baseline: ordinary compaction")
    p.add_argument("--model", help="model id (default claude-opus-5-5, the only one tested)")
    p.add_argument("--effort", choices=("low", "medium", "high", "xhigh", "max"),
                   help="reasoning effort (default medium)")
    p.add_argument("--budget", type=int, help="context budget in tokens (default 32000)")
    p.add_argument("--timeout", type=int, help="seconds before a command is killed (default 120)")
    p.add_argument("--max-steps", type=int, help="commands the agent may run (default 64)")
    p.add_argument("--max-cost", type=float, help="stop the run at this many dollars (default 5)")
    p.add_argument("--quiet", action="store_true", help="no per-turn progress lines")
    p.add_argument("--json", action="store_true",
                   help="print one JSON object: status, answer, dollars, session_dir")
    p.add_argument("--confirm", action="store_true", help="approve each command first")
    p.add_argument("--allow-push", action="store_true", help="let the agent run `git push`")
    p.add_argument("--pass-env", action="append", metavar="NAME",
                   help="let the agent's commands see this secret-looking variable (repeatable)")
    p.add_argument("--sandbox", choices=("none", "docker"), default="none",
                   help="docker: run the agent's commands in a container that sees only --dir")
    p.add_argument("--sandbox-image", metavar="IMAGE",
                   help="container image to use (default: a small one built on first use)")
    p.add_argument("--allow-net", action="store_true",
                   help="give the sandbox network access (off by default)")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("doctor", help="check the shell and the API credential; spends nothing")
    p.add_argument("--dir", default=".", help="folder you intend to run in")
    p.add_argument("--offline", action="store_true", help="skip the API check")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("setup", help="save your API key for this user; spends nothing")
    p.add_argument("--key-stdin", action="store_true", help="read the key from standard input")
    p.add_argument("--offline", action="store_true", help="save the key without checking it")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("hostctx", help="for host-agent plug-ins: JSON in on stdin, JSON out")
    p.set_defaults(func=cmd_hostctx)

    p = sub.add_parser("mcp", help="run as an MCP server, so another agent can hand it tasks")
    p.set_defaults(func=cmd_mcp)

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

    p = sub.add_parser("sessions", help="list the sessions recorded in a folder")
    p.add_argument("--dir", default=".")
    p.set_defaults(func=cmd_sessions)

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
