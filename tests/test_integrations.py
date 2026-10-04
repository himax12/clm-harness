"""The plug-ins in integrations/. Hermes Agent itself is not needed here: a stand-in
for its base class is used. `integrations/hermes/check.py` runs the same plug-in
through Hermes's real loader, and `integrations/opencode/check.mjs` does the same for
opencode; CI runs both."""
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HERMES = ROOT / "integrations" / "hermes" / "clm"


def test_the_plugins_copy_of_the_core_is_identical():
    core = (ROOT / "clm_harness" / "hostctx.py").read_bytes()
    assert (HERMES / "hostctx.py").read_bytes() == core, (
        "run: cp clm_harness/hostctx.py integrations/hermes/clm/hostctx.py")


def test_the_core_imports_nothing_from_the_package():
    source = (ROOT / "clm_harness" / "hostctx.py").read_text(encoding="utf-8")
    assert "from ." not in source and "import clm_harness" not in source


@pytest.fixture
def engine(tmp_path, monkeypatch):
    """The Hermes plug-in, loaded as Hermes would load it, on a stand-in base class."""

    class ContextEngine:  # the parts of Hermes's base class the plug-in relies on
        last_prompt_tokens = last_completion_tokens = last_total_tokens = 0
        threshold_tokens = context_length = compression_count = 0
        threshold_percent, protect_last_n = 0.75, 6

        def update_model(self, model, context_length, *args, **kwargs):
            self.context_length = context_length
            self.threshold_tokens = int(context_length * self.threshold_percent)

        def on_session_reset(self):
            self.last_prompt_tokens = self.compression_count = 0

        def get_status(self):
            return {"threshold_tokens": self.threshold_tokens}

    agent = types.ModuleType("agent")
    stub = types.ModuleType("agent.context_engine")
    stub.ContextEngine = ContextEngine
    monkeypatch.setitem(sys.modules, "agent", agent)
    monkeypatch.setitem(sys.modules, "agent.context_engine", stub)
    spec = importlib.util.spec_from_file_location(
        "_test_clm_plugin", HERMES / "__init__.py", submodule_search_locations=[str(HERMES)])
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "_test_clm_plugin", module)
    spec.loader.exec_module(module)

    collected = []
    module.register(types.SimpleNamespace(register_context_engine=collected.append))
    [eng] = collected
    eng.update_model("m", 20_000)
    eng.on_session_start("s1", hermes_home=str(tmp_path))
    return eng


def request() -> list[dict]:
    return [
        {"role": "system", "content": "You are Hermes."},
        {"role": "user", "content": [{"type": "text", "text": "Find the bug."}]},
        {"role": "assistant", "content": "Reading.", "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "terminal", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "code\n" * 4000},
        {"role": "assistant", "content": "Line 3."},
        {"role": "user", "content": "Fix it."},
    ]


def call(engine, **args) -> dict:
    return json.loads(engine.handle_tool_call("clm_context", args))


def test_hermes_first_request_only_gains_the_guide(engine):
    messages = request()
    frozen = json.dumps(messages)
    sent = engine.select_context(messages, budget_tokens=20_000)
    assert json.dumps(messages) == frozen  # the host's list was not touched
    assert sent[0]["content"].startswith("You are Hermes.") and "clm_context" in sent[0]["content"]
    assert all(a is b for a, b in zip(sent[1:], messages[1:], strict=True))  # same objects
    assert engine.get_tool_schemas()[0]["name"] == "clm_context"


def test_hermes_edits_apply_to_the_next_request_and_survive_a_restart(engine, tmp_path):
    messages = request()
    engine.select_context(messages)
    blocks = call(engine, action="list")["blocks"]
    tool_id = next(b["id"] for b in blocks if b["role"] == "tool")
    assert not call(engine, action="remove", ids=[blocks[0]["id"]])["ok"]  # the user's
    assert call(engine, action="replace", id=tool_id, text="bug on line 3")["ok"]
    assert call(engine, action="tracker", text="next: fix")["ok"]

    sent = engine.select_context(messages)
    assert sent[3]["content"] == "bug on line 3" and sent[3]["tool_call_id"] == "call_1"
    # A user message given as a list of parts keeps that shape and gains the tracker.
    assert sent[1]["content"][-1]["text"].endswith("[context tracker]\nnext: fix")
    assert messages[3]["content"].startswith("code")  # stored history untouched
    assert (tmp_path / "clm" / "s1.json").exists()

    engine.on_session_start("s1", hermes_home=str(tmp_path))  # as after a restart
    assert engine.select_context(messages)[3]["content"] == "bug on line 3"
    assert engine.get_status()["clm_edits"] == 2 and engine.get_status()["clm_refused"] == 1


def test_hermes_compress_keeps_calls_paired_and_users_intact(engine):
    big = request()[:5]
    for n in range(2, 12):
        big += [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": f"call_{n}", "type": "function", "function": {"name": "t", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": f"call_{n}", "content": "output " * 4000},
        ]
    big.append({"role": "user", "content": "Carry on."})
    assert engine.should_compress(50_000) and not engine.should_compress(100)
    out = engine.compress(big, current_tokens=50_000)
    calls = {c["id"] for m in out for c in m.get("tool_calls") or []}
    assert calls == {m["tool_call_id"] for m in out if m["role"] == "tool"}
    assert [m for m in out if m["role"] == "user"] == [m for m in big if m["role"] == "user"]
    assert sum(len(str(m["content"])) for m in out) // 4 < engine.threshold_tokens
    assert engine.compression_count == 1 and "clm_context" not in str(out[0]["content"])


def test_hermes_ignores_other_tools_and_bad_arguments(engine):
    engine.select_context(request())
    assert "error" in json.loads(engine.handle_tool_call("something_else", {}))
    assert not json.loads(engine.handle_tool_call("clm_context", None))["ok"]
