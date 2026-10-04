"""clm: a context engine for Hermes Agent in which the model manages its own context.

The model gets one tool, `clm_context`, to list, shorten, remove and restore the blocks
of its context. Its edits are an overlay applied to each request: Hermes's stored
history is not changed, so every edit can be undone. When the context still reaches the
host's threshold, the engine shrinks the history without a model call.

Install: copy this folder to `$HERMES_HOME/plugins/clm/` and set `context.engine: clm`
in config.yaml. Part of https://github.com/himax12/clm-harness (MIT).
"""
from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.context_engine import ContextEngine

try:
    from .hostctx import PROMPT, TOOL_NAME, TOOL_SCHEMA, Msg, Overlay, message_key
except ImportError:  # loaded without a package context
    import importlib.util as _util

    _spec = _util.spec_from_file_location("_clm_hostctx", Path(__file__).with_name("hostctx.py"))
    _mod = _util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    PROMPT, TOOL_NAME, TOOL_SCHEMA = _mod.PROMPT, _mod.TOOL_NAME, _mod.TOOL_SCHEMA
    Msg, Overlay, message_key = _mod.Msg, _mod.Overlay, _mod.message_key

logger = logging.getLogger(__name__)


def _text(content: Any) -> str:
    """The text of an OpenAI-format message content: a string, or a list of parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content
                       if isinstance(p, dict) and p.get("type") == "text")
    return ""


def _with_text(message: Dict[str, Any], text: str) -> Dict[str, Any]:
    """A copy of the message with its text replaced; parts that are not text are kept."""
    out = dict(message)
    content = message.get("content")
    if isinstance(content, list):
        other = [p for p in content if not (isinstance(p, dict) and p.get("type") == "text")]
        out["content"] = [*other, {"type": "text", "text": text}]
    else:
        out["content"] = text
    return out


def to_msgs(messages: List[Dict[str, Any]]) -> List[Msg]:
    seen: Dict[str, int] = {}
    out = []
    for m in messages:
        role = m.get("role", "")
        text = _text(m.get("content"))
        calls = tuple(c.get("id", "") for c in (m.get("tool_calls") or []) if isinstance(c, dict))
        answers = m.get("tool_call_id", "") if role == "tool" else ""
        # Keys come from call ids and content, never from Hermes's message_uid: the
        # request copy handed to select_context has that field stripped.
        out.append(Msg(message_key(role, text, calls, answers, seen), role, text, calls, answers))
    return out


class CLMEngine(ContextEngine):
    """Model-managed context. See the module docstring."""

    emit_automatic_compaction_status = True

    def __init__(self) -> None:
        self.overlay = Overlay()
        self._state: Optional[Path] = None

    @property
    def name(self) -> str:
        return "clm"

    # ---- session -----------------------------------------------------------------

    def on_session_start(self, session_id: str, **kwargs: Any) -> None:
        home = Path(kwargs.get("hermes_home") or Path.home() / ".hermes")
        self._state = home / "clm" / f"{session_id}.json"
        self.overlay = Overlay.open(self._state, self.threshold_tokens)

    def on_session_reset(self) -> None:
        super().on_session_reset()
        self.overlay = Overlay(self.threshold_tokens)

    def update_model(self, model: str, context_length: int, base_url: str = "",
                     api_key: str = "", provider: str = "", api_mode: str = "") -> None:
        super().update_model(model, context_length, base_url, api_key, provider, api_mode)
        self.overlay.limit = self.threshold_tokens

    def _save(self) -> None:
        if self._state is not None:
            try:
                self.overlay.save(self._state)
            except OSError:
                logger.warning("clm: could not save state to %s", self._state, exc_info=True)

    # ---- usage and the host's threshold ------------------------------------------

    def update_from_response(self, usage: Dict[str, Any]) -> None:
        self.last_prompt_tokens = int(usage.get("prompt_tokens") or 0)
        self.last_completion_tokens = int(usage.get("completion_tokens") or 0)
        self.last_total_tokens = int(usage.get("total_tokens") or 0)
        self.overlay.calibrate(self.last_prompt_tokens)

    def should_compress(self, prompt_tokens: int = None) -> bool:
        tokens = prompt_tokens if prompt_tokens is not None else self.last_prompt_tokens
        return bool(self.threshold_tokens) and tokens >= self.threshold_tokens

    def compress(self, messages: List[Dict[str, Any]], current_tokens: Optional[int] = None,
                 focus_topic: Optional[str] = None, force: bool = False,
                 memory_context: str = "") -> List[Dict[str, Any]]:
        """The model did not keep the context under the threshold. Make its edits
        permanent, then clear old tool output and drop old tool calls until it fits.
        No model call is made."""
        self.overlay.sync(to_msgs(messages))
        target = int((self.threshold_tokens or self.overlay.tokens()) * 0.6)
        self.overlay.shrink(target, keep_last=self.protect_last_n)
        out = self._render(messages, guide=False)
        # The edits are now part of the stored history; the overlay starts again.
        self.overlay.sync(to_msgs(out))
        self.overlay.replaced.clear()
        self.overlay.forget_missing()
        self.compression_count += 1
        self.last_prompt_tokens = -1  # the host's "compression just ran" marker
        self._save()
        return out

    # ---- every request -----------------------------------------------------------

    def select_context(self, request_messages: List[Dict[str, Any]], *,
                       conversation_messages: List[Dict[str, Any]] = None,
                       incoming_message: Dict[str, Any] = None,
                       budget_tokens: int = 0) -> List[Dict[str, Any]]:
        self.overlay.sync(to_msgs(request_messages))
        self.overlay.notice()
        self._save()
        return self._render(request_messages, guide=True)

    def _render(self, messages: List[Dict[str, Any]], guide: bool) -> List[Dict[str, Any]]:
        """The host's messages with the overlay applied. Unchanged messages are returned
        as the same objects, so an untouched prefix stays byte-identical for caching."""
        out: List[Dict[str, Any]] = []
        tracker = self.overlay.tracker_text() if guide else ""
        guided = not guide
        # The overlay was synced from this same list, so the two are the same length.
        for message, (m, text, changed) in zip(messages, self.overlay.view(), strict=True):
            if text is None:
                continue
            if m.role == "system" and not guided:
                text, changed, guided = text.rstrip() + "\n\n" + PROMPT, True, True
            elif m.role == "user" and tracker:
                text, changed, tracker = text + "\n\n" + tracker, True, ""
            out.append(_with_text(message, text) if changed else message)
        return out

    # ---- the tool ----------------------------------------------------------------

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return [copy.deepcopy(TOOL_SCHEMA)]

    def handle_tool_call(self, name: str, args: Dict[str, Any], **kwargs: Any) -> str:
        if name != TOOL_NAME:
            return json.dumps({"error": f"Unknown context engine tool: {name}"})
        args = args if isinstance(args, dict) else {}
        # The overlay still holds the request the model just saw (select_context ran
        # before this reply), so the ids are the ones `list` showed it, and the step in
        # progress is not among them.
        result = self.overlay.apply(str(args.get("action", "")), str(args.get("id") or ""),
                                    args.get("ids"), str(args.get("text") or ""))
        self._save()
        return json.dumps(result, ensure_ascii=False)

    def get_status(self) -> Dict[str, Any]:
        status = super().get_status()
        status.update(clm_edits=self.overlay.edits, clm_refused=self.overlay.refused,
                      clm_removed=len(self.overlay.removed),
                      clm_replaced=len(self.overlay.replaced))
        return status


def register(ctx: Any) -> None:
    ctx.register_context_engine(CLMEngine())
