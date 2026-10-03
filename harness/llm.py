from __future__ import annotations

import time

import anthropic

from .config import Config
from .context import FIRST_LINE, Context, render_block
from .loop import PROMPTS, ModelReply
from .session import Usage

EPHEMERAL = {"type": "ephemeral"}
BASH_TOOL = {"type": "bash_20250124", "name": "bash"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
INTERRUPTED = "This part of the response was interrupted before it finished."
RETRY_DELAYS = (5, 15, 30)


def anchor_indices(n_blocks: int) -> list[int]:
    """Where the two interior cache markers go: the two highest multiples of 10 that
    are at most n - 2.

    Fixed positions, not fractions of n: a marker that moves every turn is never
    found again by a later request.
    """
    return list(range(10, n_blocks - 1, 10))[-2:]


def build_content(ctx: Context) -> list[dict]:
    """The single user message: the pinned task, then the context file block by block.

    One text block per context block, so that an edit only invalidates the prompt
    cache from the edited block onward.
    """
    content = [{"type": "text", "text": f"TASK\n{ctx.pinned}\n\n", "cache_control": EPHEMERAL}]
    if ctx.rollback_note:
        content.append({"type": "text", "text": ctx.rollback_note + "\n\n"})
    content.append({"type": "text", "text": FIRST_LINE + "\n"})
    start = len(content)
    for b in ctx.blocks:
        content.append({"type": "text", "text": render_block(b) + "\n\n"})
    for i in anchor_indices(len(ctx.blocks)):
        content[start + i]["cache_control"] = EPHEMERAL
    return content


def _usage(response) -> Usage:
    u = response.usage
    return Usage(
        input=u.input_tokens or 0,
        output=u.output_tokens or 0,
        cache_read=getattr(u, "cache_read_input_tokens", 0) or 0,
        cache_write=getattr(u, "cache_creation_input_tokens", 0) or 0,
    )


def parse_response(response) -> ModelReply:
    texts, thoughts, tool_uses = [], [], []
    for block in response.content:
        kind = getattr(block, "type", "")
        if kind == "text":
            texts.append(block.text)
        elif kind == "thinking":
            thought = (getattr(block, "thinking", "") or "").strip()
            if thought and thought != INTERRUPTED:
                thoughts.append(thought)
        elif kind == "tool_use":
            tool_uses.append(block)

    reply = ModelReply(
        text="".join(texts).strip(),
        thinking="\n".join(thoughts),
        stop_reason=response.stop_reason or "",
        usage=_usage(response),
        served_by=getattr(response, "model", "") or "",
    )
    if reply.stop_reason == "stop_sequence":
        reply.stop_reason = "end_turn"
    if tool_uses and reply.stop_reason in ("tool_use", "max_tokens"):
        args = tool_uses[0].input  # only the first call; the mirror is rewritten between commands
        if isinstance(args, dict) and args.get("restart") is True:
            reply.restart = True
        elif isinstance(args, dict) and isinstance(args.get("command"), str) and args["command"].strip():
            reply.command = args["command"]
        elif reply.stop_reason == "tool_use":
            reply.stop_reason = "invalid_tool"
    return reply


class ClaudeModel:
    def __init__(self, cfg: Config, client=None):
        self.cfg = cfg
        self.client = client or anthropic.Anthropic()

    def _request(self, **kwargs):
        """One streamed request. Retries rate limits, server errors and dropped connections
        beyond the SDK's own two retries; any other API error is raised at once."""
        for attempt in range(len(RETRY_DELAYS) + 1):
            try:
                with self.client.beta.messages.stream(**kwargs) as stream:
                    return stream.get_final_message()
            except anthropic.RateLimitError as e:
                last = e
            except anthropic.APIStatusError as e:
                if e.status_code < 500:
                    raise
                last = e
            except anthropic.APIConnectionError as e:
                last = e
            if attempt < len(RETRY_DELAYS):
                time.sleep(RETRY_DELAYS[attempt])
        raise last

    def _base(self, system: str) -> dict:
        return dict(
            model=self.cfg.model,
            max_tokens=self.cfg.max_tokens,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            thinking={"type": "adaptive", "display": "summarized"},
            output_config={"effort": self.cfg.effort},
            system=[{"type": "text", "text": system}],
        )

    def reply(self, system: str, ctx: Context) -> ModelReply:
        response = self._request(
            **self._base(system),
            cache_control=EPHEMERAL,
            tools=[BASH_TOOL],
            tool_choice={"type": "auto", "disable_parallel_tool_use": True},
            messages=[{"role": "user", "content": build_content(ctx)}],
        )
        return parse_response(response)

    def summarise(self, transcript: str) -> tuple[str, Usage]:
        """One tool-less call that turns earlier work into a handoff summary (baseline mode)."""
        system = (PROMPTS / "summarise.md").read_text(encoding="utf-8")
        response = self._request(
            **self._base(system),
            messages=[{"role": "user", "content": transcript}],
        )
        reply = parse_response(response)
        return reply.text, reply.usage
