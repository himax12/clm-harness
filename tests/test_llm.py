from types import SimpleNamespace as NS

import anthropic
import httpx2 as httpx
import pytest

from harness import llm
from harness.config import Config
from harness.llm import ClaudeModel, anchor_indices, build_content, parse_response

from conftest import make_ctx


def response(content, stop_reason="tool_use", model="claude-opus-5-5", **usage):
    usage = {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 0,
             "cache_creation_input_tokens": 0, **usage}
    return NS(content=content, stop_reason=stop_reason, model=model, usage=NS(**usage))


def text(t):
    return NS(type="text", text=t)


def tool(**args):
    return NS(type="tool_use", name="bash", input=args)


class FakeClient:
    """Stands in for anthropic.Anthropic: records request kwargs, replays responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = NS(messages=NS(stream=self._stream))

    def _stream(self, **kwargs):
        self.requests.append(kwargs)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return NS(__enter__=lambda *_: NS(get_final_message=lambda: item),
                  __exit__=lambda *_: False)


class _Ctx:
    """SimpleNamespace cannot be a context manager (dunder lookup is on the type)."""

    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return NS(get_final_message=lambda: self.message)

    def __exit__(self, *exc):
        return False


def client(responses):
    c = FakeClient(responses)

    def stream(**kwargs):
        c.requests.append(kwargs)
        item = c.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return _Ctx(item)

    c.beta = NS(messages=NS(stream=stream))
    return c


# --- request building ---------------------------------------------------------


@pytest.mark.parametrize("n, expected", [(0, []), (5, []), (11, []), (12, [10]), (25, [10, 20]),
                                         (35, [20, 30]), (32, [20, 30]), (31, [10, 20])])
def test_anchor_positions_are_fixed_multiples_of_ten(n, expected):
    assert anchor_indices(n) == expected


def test_content_is_one_text_block_per_context_block():
    ctx = make_ctx(("assistant", "$ ls"), ("output", "a.txt"))
    content = build_content(ctx)
    assert [c["type"] for c in content] == ["text"] * 4
    assert content[0]["text"].startswith("TASK\nthe task")
    assert content[1]["text"] == "[[CTX v1]]\n"
    assert content[2]["text"].startswith("[[BLOCK id=b0001 role=assistant")
    assert "a.txt" in content[3]["text"]


def test_the_model_sees_the_same_text_as_the_file():
    from harness.context import render

    ctx = make_ctx(("assistant", "$ ls"), ("output", "a.txt"), ("note", "tracker"))
    joined = "".join(c["text"] for c in build_content(ctx)[1:])
    assert joined.strip() == render(ctx).strip()


def test_cache_markers_sit_on_the_task_and_the_anchors():
    ctx = make_ctx(*[("output", f"o{i}") for i in range(35)])
    content = build_content(ctx)
    marked = [i for i, c in enumerate(content) if "cache_control" in c]
    assert marked == [0, 2 + 20, 2 + 30]  # task, then blocks 20 and 30 (offset by 2)
    assert len(marked) <= 3  # the fourth marker is the automatic one on the last block


def test_rollback_note_goes_after_the_cached_task_block():
    ctx = make_ctx(("output", "x"))
    ctx.rollback_note = "rolled back"
    content = build_content(ctx)
    assert "cache_control" in content[0] and content[1]["text"].startswith("rolled back")
    assert "cache_control" not in content[1]


def test_unedited_prefix_is_byte_identical_across_turns():
    ctx = make_ctx(*[("output", f"o{i}") for i in range(14)])
    before = [c["text"] for c in build_content(ctx)]
    ctx.add("assistant", "$ next")
    ctx.add("output", "more")
    after = [c["text"] for c in build_content(ctx)]
    assert after[: len(before)] == before


def test_request_parameters():
    c = client([response([text("hi")], stop_reason="end_turn")])
    ClaudeModel(Config(), client=c).reply("SYSTEM", make_ctx(("output", "x")))
    (req,) = c.requests
    assert req["model"] == "claude-opus-5-5" and req["max_tokens"] == 16_000
    assert req["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert req["output_config"] == {"effort": "medium"}
    assert req["tools"] == [{"type": "bash_20250124", "name": "bash"}]
    assert req["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}
    assert req["betas"] == ["server-side-fallback-2026-07-01"] and req["fallbacks"] == "default"
    assert req["cache_control"] == {"type": "ephemeral"}
    assert req["system"] == [{"type": "text", "text": "SYSTEM"}]
    assert len(req["messages"]) == 1 and req["messages"][0]["role"] == "user"
    assert "temperature" not in req  # rejected by this model


# --- response parsing ---------------------------------------------------------


def test_command_text_and_reasoning_are_extracted():
    r = parse_response(response([
        NS(type="thinking", thinking="look around first"),
        text("Listing."),
        tool(command="ls -la"),
    ]))
    assert (r.command, r.text, r.thinking) == ("ls -la", "Listing.", "look around first")
    assert r.stop_reason == "tool_use" and r.served_by == "claude-opus-5-5"


def test_empty_and_interrupted_thinking_is_dropped():
    r = parse_response(response([
        NS(type="thinking", thinking=""),
        NS(type="thinking", thinking=llm.INTERRUPTED),
        NS(type="thinking", thinking="real"),
        tool(command="ls"),
    ]))
    assert r.thinking == "real"


def test_only_the_first_tool_call_is_kept():
    r = parse_response(response([tool(command="first"), tool(command="second")]))
    assert r.command == "first"


def test_restart_is_recognised():
    r = parse_response(response([tool(restart=True)]))
    assert r.restart and r.command is None


@pytest.mark.parametrize("args", [{}, {"command": 5}, {"command": "  "}, {"cmd": "ls"}])
def test_invalid_tool_input_is_flagged(args):
    r = parse_response(response([tool(**args)]))
    assert r.stop_reason == "invalid_tool" and r.command is None


def test_reply_without_a_command_is_a_final_answer():
    r = parse_response(response([text("All done.")], stop_reason="end_turn"))
    assert r.command is None and r.stop_reason == "end_turn" and r.text == "All done."


def test_refusal_and_unknown_blocks():
    r = parse_response(response([NS(type="fallback")], stop_reason="refusal"))
    assert r.stop_reason == "refusal" and r.text == ""


def test_usage_buckets_and_fallback_model():
    r = parse_response(response([text("x")], stop_reason="end_turn", model="claude-opus-5",
                                input_tokens=100, output_tokens=20,
                                cache_read_input_tokens=900, cache_creation_input_tokens=None))
    u = r.usage
    assert (u.input, u.output, u.cache_read, u.cache_write) == (100, 20, 900, 0)
    assert u.prompt_total == 1000 and r.served_by == "claude-opus-5"


# --- errors -------------------------------------------------------------------


def _status_error(cls, status):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx.Response(status, request=req), body=None)


def test_server_errors_are_retried(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    c = client([_status_error(anthropic.InternalServerError, 500),
                _status_error(anthropic.RateLimitError, 429),
                response([text("ok")], stop_reason="end_turn")])
    assert ClaudeModel(Config(), client=c).reply("S", make_ctx()).text == "ok"
    assert len(c.requests) == 3


def test_client_errors_are_not_retried(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    c = client([_status_error(anthropic.BadRequestError, 400), response([text("never")])])
    with pytest.raises(anthropic.BadRequestError):
        ClaudeModel(Config(), client=c).reply("S", make_ctx())
    assert len(c.requests) == 1


def test_persistent_failure_raises_after_the_retries(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    c = client([_status_error(anthropic.InternalServerError, 503)] * 4)
    with pytest.raises(anthropic.InternalServerError):
        ClaudeModel(Config(), client=c).reply("S", make_ctx())
    assert len(c.requests) == 4


def test_summarise_sends_no_tools():
    c = client([response([text("the summary")], stop_reason="end_turn", output_tokens=50)])
    summary, usage = ClaudeModel(Config(), client=c).summarise("RECORD ...")
    assert summary == "the summary" and usage.output == 50
    assert "tools" not in c.requests[0] and "handoff summary" in c.requests[0]["system"][0]["text"]
