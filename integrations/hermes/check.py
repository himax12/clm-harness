"""Loads the clm plug-in through Hermes Agent's real loader and drives it with a
synthetic session. No model call is made."""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERMES_SRC = sys.argv[1]
PLUGIN = Path(sys.argv[2])

home = Path(tempfile.mkdtemp(prefix="hermes-home-"))
os.environ["HERMES_HOME"] = str(home)
(home / "plugins").mkdir()
shutil.copytree(PLUGIN, home / "plugins" / "clm")
sys.path.insert(0, HERMES_SRC)

import plugins.context_engine as loader  # noqa: E402
from agent.context_engine import ContextEngine  # noqa: E402

print("discovered:", loader.discover_context_engines())
engine = loader.load_context_engine("clm")
assert isinstance(engine, ContextEngine), engine
assert engine.name == "clm"
print("loaded:", type(engine).__name__, "from", type(engine).__module__)

from agent.memory_manager import normalize_tool_schema  # noqa: E402

schemas = [normalize_tool_schema(s) for s in engine.get_tool_schemas()]
assert schemas and schemas[0]["name"] == "clm_context", schemas
print("tool schema accepted by Hermes:", schemas[0]["name"])

engine = engine.clone_for_agent()
engine.update_model("test-model", 20_000)
engine.on_session_start("sess-1", hermes_home=str(home), platform="cli", model="test-model")
print("threshold:", engine.threshold_tokens, "limit in overlay:", engine.overlay.limit)

request = [
    {"role": "system", "content": "You are Hermes."},
    {"role": "user", "content": "Find the bug in app.py."},
    {"role": "assistant", "content": "Reading the file.",
     "tool_calls": [{"id": "call_1", "type": "function",
                     "function": {"name": "terminal", "arguments": "{\"command\": \"cat app.py\"}"}}]},
    {"role": "tool", "tool_call_id": "call_1", "content": "line of code\n" * 3000},
    {"role": "assistant", "content": "The bug is on line 3."},
    {"role": "user", "content": "Now fix it."},
]
before = json.dumps(request)
selected = engine.select_context(request, conversation_messages=request, budget_tokens=20_000)
assert json.dumps(request) == before, "the engine changed the host's request list in place"
assert len(selected) == len(request)
assert "clm_context" in selected[0]["content"] and selected[0]["content"].startswith("You are Hermes.")
assert selected[2] is request[2] and selected[3] is request[3], "untouched messages must be the same objects"
print("select_context: guide added to the system prompt; other messages untouched")

engine.update_from_response({"prompt_tokens": 12_000, "completion_tokens": 50, "total_tokens": 12_050})
listing = json.loads(engine.handle_tool_call("clm_context", {"action": "list"}))
print("list:", [(b["id"], b["role"], b["state"], b["tokens"]) for b in listing["blocks"]])
tool_id = next(b["id"] for b in listing["blocks"] if b["role"] == "tool")
user_id = next(b["id"] for b in listing["blocks"] if b["role"] == "user")

refused = json.loads(engine.handle_tool_call("clm_context", {"action": "remove", "ids": [user_id]}))
assert not refused["ok"], refused
receipt = json.loads(engine.handle_tool_call(
    "clm_context", {"action": "replace", "id": tool_id, "text": "app.py read; bug on line 3"}))
assert receipt["ok"] and receipt["after_tokens"] < receipt["before_tokens"], receipt
print("replace receipt:", receipt)
json.loads(engine.handle_tool_call("clm_context", {"action": "tracker", "text": "next: fix line 3"}))

selected = engine.select_context(request, conversation_messages=request, budget_tokens=20_000)
assert selected[3]["content"] == "app.py read; bug on line 3"
assert selected[3]["tool_call_id"] == "call_1"
assert selected[1]["content"].endswith("[context tracker]\nnext: fix line 3")
assert request[3]["content"].startswith("line of code"), "stored history must be untouched"
print("second request: tool output replaced, tracker on the first user message, history untouched")

# A fresh engine for the same session picks the edits up from disk.
again = loader.load_context_engine("clm").clone_for_agent()
again.update_model("test-model", 20_000)
again.on_session_start("sess-1", hermes_home=str(home))
assert again.select_context(request, budget_tokens=20_000)[3]["content"] == "app.py read; bug on line 3"
print("state reloaded from", again._state)

# Over the threshold: compress without a model call, keeping calls and results paired.
big = request[:5]
for n in range(2, 12):
    big += [
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": f"call_{n}", "type": "function", "function": {"name": "terminal", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": f"call_{n}", "content": "output " * 4000},
    ]
big.append({"role": "user", "content": "Carry on."})
assert engine.should_compress(50_000)
compacted = engine.compress(big, current_tokens=50_000)
calls = {c["id"] for m in compacted for c in m.get("tool_calls") or []}
results = {m["tool_call_id"] for m in compacted if m["role"] == "tool"}
assert calls == results, (calls ^ results)
assert [m for m in compacted if m["role"] == "user"] == [m for m in big if m["role"] == "user"]
size = sum(len(str(m.get("content"))) for m in compacted) // 4
print(f"compress: {len(big)} -> {len(compacted)} messages, about {size:,} tokens, "
      f"{len(calls)} calls all paired, user messages kept")
assert size < 0.75 * 20_000
print(engine.get_status())
shutil.rmtree(home, ignore_errors=True)
print("ALL HERMES CHECKS PASSED")
