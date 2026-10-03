from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from . import safety
from .budget import Estimator, Nudger, context_tokens, raw_context, rollback
from .config import Config
from .context import Context, apply_edit, receipt, render, render_block
from .session import Session, Usage
from .shell import Shell, cap_to_room, format_observation

PROMPTS = Path(__file__).parent / "prompts"


@dataclass
class ModelReply:
    text: str = ""
    thinking: str = ""
    command: str | None = None
    restart: bool = False
    stop_reason: str = "end_turn"  # tool_use | end_turn | max_tokens | refusal | invalid_tool
    usage: Usage = field(default_factory=Usage)
    served_by: str = ""


class Model(Protocol):
    def reply(self, system: str, ctx: Context) -> ModelReply: ...


class TaskDriver(Protocol):
    """Feeds a task to the agent one operation at a time (used by the benchmark)."""

    def start(self) -> str | None: ...

    def after_command(self, command: str, observation: str) -> str | None: ...


@dataclass
class RunResult:
    status: str  # finished | step_limit | call_limit | cost_limit | time_limit
    #              | context_exhausted | refusal | error
    answer: str
    usage: Usage
    session_dir: Path


class ScriptedModel:
    """Replays fixed replies, for tests. An item may be a ModelReply or a function of
    (system, ctx) returning one."""

    def __init__(self, replies: list):
        self.replies = list(replies)
        self.seen: list[str] = []

    def reply(self, system: str, ctx: Context) -> ModelReply:
        self.seen.append(render(ctx))
        if not self.replies:
            return ModelReply(text="done")
        item = self.replies.pop(0)
        return item(system, ctx) if callable(item) else item


def run_command(command: str) -> ModelReply:
    return ModelReply(command=command, stop_reason="tool_use")


def load_system(cfg: Config, scripting: str = "`python3` and `re.sub`") -> str:
    text = (PROMPTS / "system.md").read_text(encoding="utf-8")
    if os.name == "nt":
        # Observed live: the model wrote notes to /tmp from bash, then could not open
        # them from Python, because native Windows programs do not see Git Bash's paths.
        text += (
            "- This is Git Bash on Windows. `python` and other native Windows programs do not "
            "understand Git Bash paths such as `/tmp/x` or `/c/Users/...` written inside a "
            "script. Use relative paths, or pass a path as a command-line argument or an "
            "environment variable, which are converted for you. Keep scratch files in the "
            "working directory, not in `/tmp`.\n"
        )
    if cfg.mode == "clm":
        guide = (PROMPTS / "context.md").read_text(encoding="utf-8")
        text += "\n" + guide.replace("{limit}", f"{cfg.limit:,}").replace("{scripting}", scripting)
    return text


def run(
    task: str,
    workdir: Path,
    cfg: Config,
    model: Model,
    driver: TaskDriver | None = None,
    compactor: Callable | None = None,
) -> RunResult:
    workdir = Path(workdir).resolve()
    session = Session(workdir, cfg)
    shell = Shell(workdir, session.dir, cfg)
    est = Estimator()
    nudger = Nudger()
    system = load_system(cfg, shell.scripting_hint() if cfg.mode == "clm" else "")
    ctx = Context(pinned=task)
    outputs_dir = session.dir / "outputs"

    def size() -> int:
        return context_tokens(ctx, system, est)

    def add(role: str, body: str, command: str | None = None):
        block = ctx.add(role, body, command)
        session.save_block(block)
        return block

    session.event("start", 0, task=task, mode=cfg.mode, model=cfg.model, limit=cfg.limit)
    if driver and (first := driver.start()):
        add("input", first)

    step = calls = turn = 0
    free_in_row = refused_in_row = truncated_in_row = 0
    rollbacks_in_row = rollbacks_total = 0
    recent_outputs: list[int] = []
    started = time.monotonic()
    status, answer = "error", ""

    while True:
        if step >= cfg.max_steps:
            status = "step_limit"
            break
        if calls >= cfg.lm_call_cap:
            status = "call_limit"
            break
        if session.usage.cost() >= cfg.max_cost_usd:
            status = "cost_limit"
            break
        if time.monotonic() - started >= cfg.max_wall_seconds:
            status = "time_limit"
            break
        turn += 1

        if compactor:
            compactor(ctx, system, est, cfg, session, turn)

        tokens = size()
        if tokens > cfg.limit:
            rollbacks_total += 1
            rollbacks_in_row += 1
            if rollbacks_total > cfg.max_rollbacks:
                status = "context_exhausted"
                break
            dropped = rollback(ctx, system, est, cfg, rollbacks_in_row, rollbacks_total)
            if not dropped:
                status = "context_exhausted"
                break
            session.bump("rollbacks")
            session.event(
                "rollback", turn, dropped=[b.id for b in dropped], tokens_before=tokens,
                tokens_after=size(),
            )
            continue

        rendered = ""
        if cfg.mode == "clm":
            notice = nudger.decide(tokens, recent_outputs, cfg)
            if notice:
                nb = add("notice", notice)
                session.event("notice", turn, id=nb.id, text=notice)
            rendered = render(ctx)
            session.ctx_path.write_text(rendered, encoding="utf-8", newline="\n")

        raw_request = raw_context(ctx, system)
        try:
            reply = model.reply(system, ctx)
        except Exception as e:  # an API failure must still leave a finished session on disk
            answer = f"model call failed: {type(e).__name__}: {e}"
            break
        calls += 1
        session.bump("model_calls")
        session.add_usage(reply.usage)
        est.calibrate(reply.usage.prompt_total, raw_request)
        session.event(
            "reply", turn, text=reply.text, thinking=reply.thinking, command=reply.command,
            restart=reply.restart, stop_reason=reply.stop_reason, served_by=reply.served_by,
            usage=vars(reply.usage), context_tokens=tokens,
        )

        if reply.stop_reason == "refusal":
            status = "refusal"
            break
        if reply.stop_reason == "max_tokens":
            # A cut-off reply can carry a truncated command that still parses. Never run it.
            truncated_in_row += 1
            if truncated_in_row > 2:
                answer = "the reply was cut off at the output limit three times in a row"
                break
            nb = add(
                "notice",
                "Your last reply was cut off at the output limit and its command was not run. "
                "Reply more briefly.",
            )
            session.event("notice", turn, id=nb.id, text=nb.body)
            continue
        if reply.stop_reason == "invalid_tool":
            truncated_in_row += 1
            if truncated_in_row > 2:
                answer = "the bash call had invalid input three times in a row"
                break
            nb = add("notice", "Your bash call had invalid input. Call bash with a `command` string.")
            session.event("notice", turn, id=nb.id, text=nb.body)
            continue
        truncated_in_row = 0
        if reply.stop_reason not in ("tool_use", "end_turn"):
            answer = f"unexpected stop reason: {reply.stop_reason}"
            break
        if reply.command is None and not reply.restart:
            status, answer = "finished", reply.text
            break

        command = reply.command or ""
        name = f"turn-{turn:04d}"
        quiet = False
        if reply.restart:
            shell.reset()
            observation = "(shell state reset)"
        elif reason := safety.blocked(command):
            observation = f"[command blocked: {reason}]"
            session.bump("blocked")
        elif cfg.confirm and not safety.confirm(command):
            observation = "[command declined by user]"
        else:
            result = shell.run(command)
            quiet = result.exit_code == 0 and not result.output.strip()
            observation = format_observation(result, name, outputs_dir, cfg)
            session.event(
                "command", turn, command=command, exit_code=result.exit_code,
                timed_out=result.timed_out, seconds=round(result.seconds, 2),
                chars=len(result.output),
            )

        # Apply the edit before this turn's own blocks are appended, so the model
        # can never edit the command it is currently running.
        edit = None
        if cfg.mode == "clm":
            try:
                file_text = session.ctx_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                file_text = rendered  # a missing file counts as no edit
            before_blocks = list(ctx.blocks)
            known = {b.id for b in before_blocks}
            edit = apply_edit(
                ctx, rendered, file_text, cfg.limit,
                lambda blocks: context_tokens(ctx, system, est, blocks),
            )
            if edit.status == "applied":
                session.snapshot(turn, before_blocks)
                for b in ctx.blocks:
                    if b.id not in known:
                        session.save_block(b)
                reread = est.scale(
                    sum(len(render_block(b)) for b in ctx.blocks[edit.first_changed :]) // 4
                )
                session.bump("edits_applied")
                if edit.after_tokens > edit.before_tokens:
                    session.bump("edits_grew")
                session.bump("reread_tokens", reread)
                session.event(
                    "edit_applied", turn, before_tokens=edit.before_tokens,
                    after_tokens=edit.after_tokens, first_changed=edit.first_changed,
                    removed_ids=edit.removed_ids, reread_tokens=reread,
                )
                refused_in_row = 0
                rollbacks_in_row = 0
            elif edit.status == "refused":
                session.bump("edits_refused")
                session.event("edit_refused", turn, reason=edit.reason)
                refused_in_row += 1

        parts = [p for p in (reply.thinking.strip(), reply.text.strip()) if p]
        parts.append("$ (restart shell)" if reply.restart else f"$ {command}")
        add("assistant", "\n".join(parts), command=command or None)

        room = cfg.limit - size() - 64
        body = cap_to_room(observation, room, est, name, outputs_dir)
        note = receipt(edit, len(ctx.blocks), cfg.limit, touched="CTX" in command)
        if note:
            body += "\n" + note
        out = ctx.add("output", body)
        total = size()
        over = " OVER the limit; compact now" if total > cfg.limit else ""
        out.body += f"\n[context: {total:,} / {cfg.limit:,} tokens{over}]"
        session.save_block(out)
        session.event("output", turn, id=out.id, context_tokens=total)
        recent_outputs.append(est.tokens(out.body))

        free = edit is not None and edit.status == "applied" and quiet
        if free and free_in_row < cfg.max_free_edits_in_row:
            free_in_row += 1
            session.bump("free_turns")
        else:
            step += 1
            free_in_row = 0
            session.bump("steps")

        if refused_in_row >= cfg.max_refused_edits_in_row:
            nb = add(
                "notice",
                "Three context edits in a row were refused. Stop editing and continue the task.",
            )
            session.event("notice", turn, id=nb.id, text=nb.body)
            refused_in_row = 0

        if driver and (nxt := driver.after_command(command, observation)):
            add("input", nxt)

    session.event("finish", turn, status=status, answer=answer)
    session.write_usage(status)
    return RunResult(status, answer, session.usage, session.dir)
