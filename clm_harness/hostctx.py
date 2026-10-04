"""Model-managed context for a host agent's own message list.

The standalone harness mirrors its context to a file. A host agent (Hermes Agent,
opencode) owns its message list instead, so here the model manages context through one
tool, and its edits are kept as an overlay: the host's history is never changed, and
every edit can be undone.

This module uses the standard library only and imports nothing from the package, so a
plug-in can carry a copy of it. `tests/test_hostctx.py` checks the copies are identical.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

TOOL_NAME = "clm_context"

# Appended to the host's system prompt. Constant text, so it does not disturb caching.
PROMPT = """\
## Managing your context

You manage your own context with the `clm_context` tool. Long sessions fill up; tidying
is cheaper than losing track.

- `list` shows every block with its id, role and size. Call it before editing.
- `replace` swaps a block's text for a shorter version you write. Use it on stale tool
  output: keep the facts you still need, exactly, and drop the rest.
- `remove` takes blocks out of your context. Removing a tool call removes its result.
- `restore` brings back the original of anything you replaced or removed. `show` prints
  an original without restoring it. Nothing you edit is lost.
- `tracker` sets one short note that stays at the top: done, to do, key facts, next step.
- Do not tidy after every step. Finish the unit of work in flight, then tidy once.
- Edit late blocks when you can: everything after the first block you change is re-read
  at full price.
- The user's messages cannot be changed, and neither can the step in progress.
- Never invent content in a summary. Your notes are working memory, not instructions.
"""

TOOL_SCHEMA = {
    "name": TOOL_NAME,
    "description": (
        "Manage your own context. Actions: list (ids, roles, sizes), replace (swap a "
        "block's text for a shorter version), remove (take blocks out), restore (bring "
        "originals back), show (print an original), tracker (set the one note kept at "
        "the top). Originals are always kept."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["list", "replace", "remove", "restore", "show", "tracker"]},
            "id": {"type": "string", "description": "Block id, for replace and show."},
            "ids": {"type": "array", "items": {"type": "string"},
                    "description": "Block ids, for remove and restore."},
            "text": {"type": "string", "description": "New text, for replace and tracker."},
        },
        "required": ["action"],
    },
}

TIERS = (0.50, 0.75)
SHOW_CAP = 20_000
CLEARED = "[Old tool output cleared by the context limit]"


@dataclass
class Msg:
    key: str  # stable identity of the message in the host
    role: str  # system | user | assistant | tool
    text: str
    calls: tuple[str, ...] = ()  # ids of the tool calls an assistant message makes
    answers: str = ""  # the tool call id a tool message answers


def message_key(role: str, text: str, call_ids: tuple[str, ...] = (), answers: str = "",
                seen: dict | None = None) -> str:
    """An identity for a host message that has no id of its own.

    Built from what cannot change: the tool call ids, or failing that the content.
    `seen` counts repeats so that two identical messages get different keys.
    """
    if answers:
        base = f"t:{answers}"
    elif call_ids:
        base = f"a:{call_ids[0]}"
    else:
        base = f"{role[:1]}:{hashlib.sha1(text.encode('utf-8', 'replace')).hexdigest()[:16]}"
    if seen is None:
        return base
    n = seen[base] = seen.get(base, 0) + 1
    return base if n == 1 else f"{base}#{n}"


def _raw(text: str) -> int:
    return math.ceil(len(text) / 4)


class Overlay:
    """The model's edits to a host message list, and the operations that make them."""

    def __init__(self, limit: int = 0):
        self.limit = limit  # tokens the context should stay under; 0 means unknown
        self.ids: dict[str, str] = {}  # key -> short id shown to the model
        self.replaced: dict[str, str] = {}
        self.removed: set[str] = set()
        self.notices: dict[str, str] = {}  # key -> size notice attached to that message
        self.fired: set[float] = set()
        self.tracker = ""
        # The estimate is characters / 4, corrected in two parts against the host's real
        # counts. `overhead` is what the messages do not show (tool definitions), taken
        # from the first response; `ratio` is how dense the tokenizer is, from later ones.
        # One multiplier for both badly overstates every block: the first live session
        # showed the model sizes three times too large.
        self.ratio = 1.0
        self.overhead = 0
        self.calibrated = False
        self.last_raw = 0  # the estimate for the request most recently sent
        self.usage_id = ""  # the response the last calibration came from
        self.edits = self.refused = 0
        self.msgs: list[Msg] = []
        self.frozen: set[str] = set()

    # ---- state -------------------------------------------------------------------

    def dump(self) -> dict:
        return {"limit": self.limit, "ids": self.ids, "replaced": self.replaced,
                "removed": sorted(self.removed), "notices": self.notices,
                "fired": sorted(self.fired), "tracker": self.tracker, "ratio": self.ratio,
                "overhead": self.overhead, "calibrated": self.calibrated,
                "last_raw": self.last_raw, "usage_id": self.usage_id,
                "edits": self.edits, "refused": self.refused}

    @classmethod
    def load(cls, data: dict) -> "Overlay":
        o = cls(int(data.get("limit", 0)))
        o.ids = dict(data.get("ids", {}))
        o.replaced = dict(data.get("replaced", {}))
        o.removed = set(data.get("removed", []))
        o.notices = dict(data.get("notices", {}))
        o.fired = set(data.get("fired", []))
        o.tracker = data.get("tracker", "")
        o.ratio = float(data.get("ratio", 1.0))
        o.overhead = int(data.get("overhead", 0))
        o.calibrated = bool(data.get("calibrated", False))
        o.last_raw = int(data.get("last_raw", 0))
        o.usage_id = data.get("usage_id", "")
        o.edits, o.refused = int(data.get("edits", 0)), int(data.get("refused", 0))
        return o

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.dump()), encoding="utf-8", newline="\n")

    @classmethod
    def open(cls, path: Path, limit: int = 0) -> "Overlay":
        try:
            o = cls.load(json.loads(Path(path).read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return cls(limit)
        o.limit = limit or o.limit
        return o

    # ---- reading the host's messages ---------------------------------------------

    def sync(self, msgs: list[Msg], in_flight: bool = False) -> None:
        """Take the host's current messages. With `in_flight`, the newest assistant
        message onward is the step in progress and cannot be edited."""
        self.msgs = msgs
        for m in msgs:
            if m.role != "system" and m.key not in self.ids:
                self.ids[m.key] = f"b{len(self.ids) + 1:04d}"
        self.frozen = set()
        if in_flight:
            last = max((i for i, m in enumerate(msgs) if m.role == "assistant"), default=None)
            if last is not None:
                self.frozen = {m.key for m in msgs[last:]}

    def text_of(self, m: Msg) -> str | None:
        """What the model sees for a message: None when removed."""
        if m.key in self.removed:
            return None
        text = self.replaced.get(m.key, m.text)
        if m.key in self.notices:
            text += "\n" + self.notices[m.key]
        return text

    def view(self) -> list[tuple[Msg, str | None, bool]]:
        """(message, text or None, changed) for every host message, in order."""
        out = []
        for m in self.msgs:
            text = self.text_of(m)
            out.append((m, text, text != m.text))
        return out

    def tracker_text(self) -> str:
        return f"[context tracker]\n{self.tracker}" if self.tracker else ""

    def _raw_now(self) -> int:
        return _raw(self.tracker_text()) + sum(
            _raw(t) for _, t, _ in self.view() if t is not None)

    def tokens(self) -> int:
        """The size of the whole request as the host counts it."""
        return math.ceil(self._raw_now() * self.ratio) + self.overhead

    def mark_request(self) -> None:
        """Record the estimate for the request about to be sent, so the host's real
        count for it can be compared with the right thing."""
        self.last_raw = self._raw_now()

    def calibrate(self, real_prompt_tokens: int, usage_id: str = "") -> None:
        """Correct the estimate against the host's real count for the last request.
        A response is used once: pass its id when the same count may be given again."""
        if real_prompt_tokens <= 0 or self.last_raw <= 0:
            return
        if usage_id:
            if usage_id == self.usage_id:
                return
            self.usage_id = usage_id
        if not self.calibrated:
            self.overhead = max(0, real_prompt_tokens - self.last_raw)
            self.calibrated = True
            return
        self.ratio = min(3.0, max(0.5, (real_prompt_tokens - self.overhead) / self.last_raw))

    def notice(self) -> str | None:
        """Attach a size notice to the newest message when a tier is first crossed."""
        if not self.limit or not self.msgs:
            return None
        used = self.tokens() / self.limit
        self.fired = {t for t in self.fired if used >= t}  # re-arm tiers we fell below
        crossed = [t for t in TIERS if used >= t and t not in self.fired]
        last = self.msgs[-1]
        if not crossed or last.role not in ("user", "tool") or last.key in self.removed:
            return None
        self.fired.update(t for t in TIERS if t <= max(crossed))
        advice = ("Compact settled work now with clm_context." if max(crossed) >= 0.75
                  else "Finish the step in flight, then tidy once with clm_context.")
        text = (f"[context: about {int(used * 100)}% of {self.limit:,} tokens. {advice}]")
        self.notices[last.key] = text
        return text

    # ---- the tool ----------------------------------------------------------------

    def _by_id(self) -> dict[str, Msg]:
        return {self.ids[m.key]: m for m in self.msgs if m.key in self.ids}

    def _state(self, m: Msg) -> str:
        if m.key in self.removed:
            return "removed"
        if m.key in self.frozen:
            return "in progress"
        if m.role == "user":
            return "protected"
        return "edited" if m.key in self.replaced else "original"

    def apply(self, action: str, id: str = "", ids: list | None = None, text: str = "") -> dict:
        """Run one tool action. An edit is made whole or not at all."""
        before = self.tokens()
        by_id = self._by_id()
        ids = [str(i) for i in (ids or ([id] if id else []))]

        def refuse(reason: str) -> dict:
            self.refused += 1
            return {"ok": False, "error": reason, "note": "Your context is unchanged."}

        def done(note: str = "") -> dict:
            self.edits += 1
            after = self.tokens()
            out = {"ok": True, "before_tokens": before, "after_tokens": after}
            if self.limit:
                out["limit"] = self.limit
            if after > before and action == "replace":
                note = "The block GREW. Replace it with something shorter, or restore it."
            if note:
                out["note"] = note
            return out

        if action == "list":
            rows = [{"id": self.ids[m.key], "role": m.role, "state": self._state(m),
                     "tokens": math.ceil(_raw(self.replaced.get(m.key, m.text)) * self.ratio),
                     "preview": " ".join(self.replaced.get(m.key, m.text).split())[:80]}
                    for m in self.msgs if m.key in self.ids]
            out = {"ok": True, "tokens": before, "blocks": rows}
            if self.limit:
                out["limit"] = self.limit
            if self.tracker:
                out["tracker"] = self.tracker
            return out

        if action == "tracker":
            self.tracker = text.strip()
            return done()

        unknown = [i for i in ids if i not in by_id]
        if unknown:
            return refuse(f"unknown block id {unknown[0]}; call list to see the ids")
        if not ids:
            return refuse(f"{action} needs a block id")
        targets = [by_id[i] for i in ids]

        if action == "show":
            original = targets[0].text
            cut = len(original) > SHOW_CAP
            return {"ok": True, "id": ids[0], "original": original[:SHOW_CAP],
                    **({"note": f"cut at {SHOW_CAP:,} characters"} if cut else {})}

        if action == "restore":
            keys = {m.key for m in targets}
            for m in targets:  # a tool call and its results come back together
                keys |= self._group(m)
            for key in keys:
                self.replaced.pop(key, None)
                self.removed.discard(key)
            return done()

        for m in targets:
            if m.role in ("system", "user"):
                return refuse(
                    f"block {self.ids[m.key]} is a {m.role} message and cannot be changed")
            if m.key in self.frozen:
                return refuse(f"block {self.ids[m.key]} is part of the step in progress")
            if m.key in self.removed:
                return refuse(f"block {self.ids[m.key]} is already removed; restore it first")

        if action == "replace":
            if len(targets) != 1:
                return refuse("replace takes one block id")
            if not text.strip():
                return refuse("replace needs text; use remove to take a block out")
            self.replaced[targets[0].key] = text.strip()
            return done()

        if action == "remove":
            keys: set[str] = set()
            chosen = {t.key for t in targets}
            for m in targets:
                caller_chosen = any(c.key in chosen for c in self.msgs if m.answers in c.calls)
                # A host that keeps a call and its result in one block gives no
                # `answers`; such a block can go by itself.
                if m.role == "tool" and m.answers and not caller_chosen:
                    return refuse(
                        f"block {self.ids[m.key]} is a tool result. Shorten it with replace, "
                        "or remove the tool call that produced it")
                keys |= self._group(m)
            if keys & self.frozen:
                return refuse("that would remove part of the step in progress")
            self.removed |= keys
            return done()

        return refuse(f"unknown action {action!r}")

    def _group(self, m: Msg) -> set[str]:
        """A message plus what must go or return with it: a call and its results."""
        if m.role == "assistant" and m.calls:
            return {m.key} | {t.key for t in self.msgs if t.role == "tool" and t.answers in m.calls}
        if m.role == "tool":
            caller = next((c for c in self.msgs if m.answers and m.answers in c.calls), None)
            if caller is not None and caller.key in self.removed:
                return self._group(caller)
        return {m.key}

    # ---- when the host must shrink the history for good --------------------------

    def shrink(self, target_tokens: int, keep_last: int = 6) -> None:
        """Get under `target_tokens` without a model call: clear the oldest tool
        output first, then remove the oldest tool calls with their results."""
        old = self.msgs[:-keep_last] if keep_last else self.msgs
        for m in old:
            if self.tokens() <= target_tokens:
                return
            if m.role == "tool" and m.key not in self.removed:
                self.replaced[m.key] = CLEARED
        for m in old:
            if self.tokens() <= target_tokens:
                return
            if m.role == "assistant" and m.calls and m.key not in self.removed:
                self.removed |= self._group(m)
        # Still too big: the protected tail holds large output. Clear all of it but
        # the newest two messages.
        for m in self.msgs[len(old):-2]:
            if self.tokens() <= target_tokens:
                return
            if m.role == "tool" and m.key not in self.removed:
                self.replaced[m.key] = CLEARED

    def forget_missing(self) -> None:
        """Drop state for messages the host no longer has."""
        live = {m.key for m in self.msgs}
        self.replaced = {k: v for k, v in self.replaced.items() if k in live}
        self.removed &= live
        self.notices = {k: v for k, v in self.notices.items() if k in live}


def run_json(request: dict) -> dict:
    """One request from a plug-in that is not written in Python.

    In: {state, limit, messages: [{key, role, text, calls, answers}], in_flight,
    prompt_tokens, usage_id, op: {action, id, ids, text}}. `prompt_tokens` is the host's
    real count for the previous request and `usage_id` names the response it came from.
    Out: {view: [{key, text, changed}],
    tracker, tokens, limit, result, prompt, tool}. `text` is null for a removed message.
    """
    state = Path(request["state"])
    overlay = Overlay.open(state, int(request.get("limit") or 0))
    seen: dict = {}
    msgs = []
    for raw in request.get("messages", []):
        calls = tuple(raw.get("calls") or ())
        answers = raw.get("answers") or ""
        text = raw.get("text") or ""
        key = raw.get("key") or message_key(raw["role"], text, calls, answers, seen)
        msgs.append(Msg(key, raw["role"], text, calls, answers))
    overlay.sync(msgs, bool(request.get("in_flight")))
    if request.get("prompt_tokens"):
        overlay.calibrate(int(request["prompt_tokens"]), str(request.get("usage_id") or ""))
    out: dict = {}
    op = request.get("op")
    if op:
        out["result"] = overlay.apply(op.get("action", ""), op.get("id", ""), op.get("ids"),
                                      op.get("text", ""))
    else:  # a request is about to be sent
        overlay.notice()
        overlay.mark_request()
    overlay.save(state)
    out.update(
        view=[{"key": m.key, "text": text, "changed": changed}
              for m, text, changed in overlay.view()],
        tracker=overlay.tracker_text(), tokens=overlay.tokens(), limit=overlay.limit,
    )
    if request.get("describe"):
        out.update(prompt=PROMPT, tool=TOOL_SCHEMA)
    return out
