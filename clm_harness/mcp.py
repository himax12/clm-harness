"""An MCP server that lets another agent hand a task to this harness.

`harness mcp` speaks the Model Context Protocol over stdin and stdout: one JSON-RPC
message per line. It offers one tool, `run_task`. The calling agent keeps its own
context; the task it hands over runs here, with the harness managing context for it.

Written against the protocol directly, so the package needs no MCP dependency.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Callable

PROTOCOL = "2025-06-18"
KNOWN_PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18")
# The calling agent chooses the cost limit for a task, up to this. Raise it with the
# CLM_HARNESS_MCP_MAX_COST environment variable.
DEFAULT_COST, COST_CEILING = 1.0, 2.0

RUN_TASK = {
    "name": "run_task",
    "description": (
        "Hand a self-contained coding or research task to clm-harness, a separate agent "
        "that works in one folder with shell commands and manages its own context, so a "
        "long task does not fill yours. It cannot see this conversation: put everything "
        "it needs in `task`. It is billed to the user's Anthropic API key. Returns the "
        "agent's final answer, its status and its cost."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "task": {"type": "string",
                     "description": "What to do, with all the context needed to do it."},
            "dir": {"type": "string", "description": "Absolute path of the folder to work in."},
            "sandbox": {"type": "boolean", "default": True,
                        "description": "Run the commands in a Docker container that sees only "
                                       "`dir` and has no network. Turn off only if the user "
                                       "agrees."},
            "allow_net": {"type": "boolean", "default": False,
                          "description": "Give the sandbox network access."},
            "max_cost": {"type": "number", "default": DEFAULT_COST,
                         "description": "Stop the task at this many dollars."},
            "max_steps": {"type": "integer", "default": 64},
        },
        "required": ["task", "dir"],
    },
}


def run_task(args: dict) -> dict:
    """Run one task with the real model. Returns a plain dict for the caller."""
    from .cli import _claude
    from .config import Config
    from .loop import run

    task = str(args.get("task") or "").strip()
    workdir = Path(str(args.get("dir") or ""))
    if not task:
        raise ValueError("`task` is empty")
    if not workdir.is_absolute() or not workdir.is_dir():
        raise ValueError(f"`dir` must be an existing absolute folder, not {str(workdir)!r}")
    ceiling = float(os.environ.get("CLM_HARNESS_MCP_MAX_COST") or COST_CEILING)
    sandbox = args.get("sandbox", True) is not False
    cfg = Config(
        sandbox="docker" if sandbox else "none",
        sandbox_network=bool(args.get("allow_net", False)),
        max_cost_usd=min(float(args.get("max_cost") or DEFAULT_COST), ceiling),
        max_steps=int(args.get("max_steps") or 64),
    )
    if sandbox:
        from .sandbox import docker_status

        usable, detail = docker_status()
        if not usable:
            raise RuntimeError(
                f"the sandbox cannot start: {detail}. Ask the user whether to run without it "
                "(sandbox=false), which runs commands with their permissions.")
    # Progress goes to stderr: stdout carries the protocol and nothing else.
    result = run(task, workdir, cfg, _claude(cfg),
                 progress=lambda line: print(line, file=sys.stderr, flush=True))
    return {"status": result.status, "answer": result.answer,
            "dollars": round(result.dollars, 4), "session_dir": str(result.session_dir)}


def handle(message: dict, runner: Callable[[dict], dict] = run_task) -> dict | None:
    """Answer one JSON-RPC message. Notifications get no answer."""
    method, mid = message.get("method"), message.get("id")

    def reply(result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def error(code: int, text: str) -> dict:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": text}}

    if mid is None:  # a notification, such as notifications/initialized
        return None
    if method == "initialize":
        asked = (message.get("params") or {}).get("protocolVersion")
        return reply({
            "protocolVersion": asked if asked in KNOWN_PROTOCOLS else PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "clm-harness", "version": _version()},
        })
    if method == "ping":
        return reply({})
    if method == "tools/list":
        return reply({"tools": [RUN_TASK]})
    if method == "tools/call":
        params = message.get("params") or {}
        if params.get("name") != RUN_TASK["name"]:
            return error(-32602, f"unknown tool {params.get('name')!r}")
        try:
            out = runner(params.get("arguments") or {})
        except Exception as e:  # a failed task is a tool result, not a protocol error
            return reply({"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}],
                          "isError": True})
        return reply({
            "content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}],
            "isError": out.get("status") != "finished",
        })
    return error(-32601, f"method not found: {method}")


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("clm-harness")
    except Exception:
        return "0"


def serve(stdin, stdout, runner: Callable[[dict], dict] = run_task) -> None:
    """Read messages from a binary stream until it closes; write answers to another."""
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            answer = {"jsonrpc": "2.0", "id": None,
                      "error": {"code": -32700, "message": "parse error"}}
        else:
            answer = handle(message, runner) if isinstance(message, dict) else None
        if answer is not None:
            stdout.write(json.dumps(answer, ensure_ascii=False).encode("utf-8") + b"\n")
            stdout.flush()
