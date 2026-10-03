from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from harness.context import raw_tokens

READY = "READY_FOR_NEXT_OP"
ALL_DELIVERED = "ALL OPERATIONS DELIVERED. Reply with DONE and no command."
ANSWER_RE = re.compile(r"<<<ANSWER\s+(\S+?)>>>(.*?)<<<ANSWER END>>>", re.DOTALL)

PROTOCOL = f"""\
The work arrives as a stream of operations, one at a time, each as a new block in your context.
After you have handled an operation, release the next one by running exactly: echo {READY}
The stream is far larger than your context can hold, so store whatever you will need later
somewhere that survives (for example in files).
When an operation asks a question, put the answer in your reply text in exactly this form,
before releasing the next operation:
<<<ANSWER id>>> value <<<ANSWER END>>>
"""


@dataclass
class Op:
    text: str
    answer_id: str | None = None  # set on operations that ask a question
    answer: str | None = None


class StreamDriver:
    """Delivers operations one at a time; the agent releases the next with the READY line."""

    def __init__(self, ops: list[Op]):
        self.ops = list(ops)
        self.next = 0
        self.closed = False

    def start(self) -> str | None:
        return self._take()

    def after_command(self, command: str, observation: str) -> str | None:
        if READY not in (line.strip() for line in observation.splitlines()):
            return None
        return self._take()

    def _take(self) -> str | None:
        if self.next < len(self.ops):
            self.next += 1
            return self.ops[self.next - 1].text
        if not self.closed:
            self.closed = True
            return ALL_DELIVERED
        return None


def _norm(s: str) -> str:
    return " ".join(s.split())


def extract_answers(transcript: Path) -> dict[str, str]:
    """Answers the agent gave, by id. A later answer for the same id replaces an earlier one."""
    answers: dict[str, str] = {}
    for line in Path(transcript).read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if e["type"] != "reply":
            continue
        for source in (e.get("text") or "", e.get("command") or ""):
            for answer_id, value in ANSWER_RE.findall(source):
                answers[answer_id] = _norm(value)
    return answers


def score(ops: list[Op], transcript: Path) -> float:
    expected = {op.answer_id: _norm(op.answer) for op in ops if op.answer_id}
    given = extract_answers(transcript)
    correct = sum(1 for k, v in expected.items() if given.get(k) == v)
    return correct / len(expected) if expected else 0.0


def total_tokens(ops: list[Op]) -> int:
    return sum(raw_tokens(op.text) for op in ops)


def check_sizing(ops: list[Op], limit: int) -> None:
    """Each operation must fit in a fifth of the usable context, with a 10% margin."""
    cap = 0.2 * limit * 0.9
    worst = max(raw_tokens(op.text) for op in ops)
    if worst > cap:
        raise ValueError(f"an operation is {worst} tokens; the cap is {int(cap)}")


def sized_for(generate: Callable[[int, int], list[Op]], seed: int, pressure: float,
              budget: int) -> list[Op]:
    """The smallest stream whose total input is at least pressure x the context budget."""
    batches = 1
    while True:
        ops = generate(seed, batches)
        if total_tokens(ops) >= pressure * budget:
            return ops
        batches += 1
