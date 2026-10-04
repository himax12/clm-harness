import io
import json

import pytest

from clm_harness.cli import main as cli
from clm_harness.hostctx import CLEARED, Msg, Overlay, message_key, run_json


def convo() -> list[Msg]:
    """A short session: task, a tool call with a big result, a reply, a second call."""
    return [
        Msg("sys", "system", "You are an agent."),
        Msg("u1", "user", "Fix the failing test."),
        Msg("a1", "assistant", "I will read the file.", calls=("c1",)),
        Msg("t1", "tool", "x" * 4000, answers="c1"),
        Msg("a2", "assistant", "The bug is on line 3."),
        Msg("a3", "assistant", "", calls=("c2", "c3")),
        Msg("t2", "tool", "y" * 2000, answers="c2"),
        Msg("t3", "tool", "z" * 2000, answers="c3"),
    ]


@pytest.fixture
def ov():
    o = Overlay(limit=4000)
    o.sync(convo())
    return o


def texts(o: Overlay) -> dict:
    return {m.key: text for m, text, _ in o.view()}


def test_ids_are_stable_and_system_has_none(ov):
    listing = ov.apply("list")
    assert [b["id"] for b in listing["blocks"]] == [f"b{i:04d}" for i in range(1, 8)]
    assert listing["blocks"][0]["state"] == "protected"  # the user's message
    ov.sync(convo() + [Msg("u2", "user", "thanks")])
    assert ov.ids["t1"] == "b0003" and ov.ids["u2"] == "b0008"  # old ids did not move


def test_replace_shortens_and_keeps_the_original(ov):
    receipt = ov.apply("replace", id="b0003", text="file read; bug on line 3")
    assert receipt["ok"] and receipt["after_tokens"] < receipt["before_tokens"]
    assert texts(ov)["t1"] == "file read; bug on line 3"
    assert ov.apply("show", id="b0003")["original"] == "x" * 4000
    assert ov.apply("restore", ids=["b0003"])["ok"] and texts(ov)["t1"] == "x" * 4000


def test_user_and_system_messages_cannot_be_changed(ov):
    for action, kwargs in (("replace", {"id": "b0001", "text": "do something else"}),
                           ("remove", {"ids": ["b0001"]})):
        receipt = ov.apply(action, **kwargs)
        assert not receipt["ok"] and "user message" in receipt["error"]
    assert texts(ov)["u1"] == "Fix the failing test." and ov.refused == 2


def test_removing_a_tool_call_removes_its_results(ov):
    assert ov.apply("remove", ids=["b0005"])["ok"]  # the call with two results
    seen = texts(ov)
    assert seen["a3"] is None and seen["t2"] is None and seen["t3"] is None
    assert seen["t1"] is not None  # another call's result is untouched


def test_a_tool_result_cannot_be_removed_alone(ov):
    receipt = ov.apply("remove", ids=["b0006"])
    assert not receipt["ok"] and "tool result" in receipt["error"]
    assert texts(ov)["t2"] is not None


def test_calls_and_results_always_stay_paired(ov):
    for ids in (["b0002"], ["b0005", "b0006"], ["b0003"]):
        ov.apply("remove", ids=ids)
    kept = {m.key for m, text, _ in ov.view() if text is not None}
    for m in ov.msgs:
        if m.key not in kept:
            continue
        if m.role == "tool":
            assert any(m.answers in c.calls and c.key in kept for c in ov.msgs)
        for call in m.calls:
            assert any(t.answers == call and t.key in kept for t in ov.msgs)


def test_restoring_one_result_brings_back_the_whole_call(ov):
    ov.apply("remove", ids=["b0005"])
    assert ov.apply("restore", ids=["b0007"])["ok"]
    seen = texts(ov)
    assert None not in (seen["a3"], seen["t2"], seen["t3"])


def test_an_edit_is_whole_or_nothing(ov):
    receipt = ov.apply("remove", ids=["b0002", "b0001"])  # the second one is the user's
    assert not receipt["ok"] and not ov.removed


def test_the_step_in_progress_cannot_be_edited():
    o = Overlay()
    o.sync(convo(), in_flight=True)  # a3 and its results are the step in progress
    assert "in progress" in o.apply("replace", id="b0006", text="short")["error"]
    assert "in progress" in o.apply("remove", ids=["b0005"])["error"]
    assert o.apply("replace", id="b0003", text="short")["ok"]  # older output is fine


def test_unknown_ids_empty_text_and_growth(ov):
    assert "unknown block id" in ov.apply("replace", id="b0099", text="x")["error"]
    assert "needs text" in ov.apply("replace", id="b0003", text="  ")["error"]
    assert "GREW" in ov.apply("replace", id="b0004", text="much longer " * 50)["note"]


def test_tracker_is_set_and_listed(ov):
    assert ov.apply("tracker", text="done: read file. next: fix line 3")["ok"]
    assert ov.tracker_text().startswith("[context tracker]")
    assert ov.apply("list")["tracker"].startswith("done:")


def test_notice_fires_once_per_tier_and_stays_on_its_message():
    o = Overlay(limit=3000)
    o.sync(convo())  # about 2,000 estimated tokens: past the first tier
    first = o.notice()
    assert first and "clm_context" in first
    assert texts(o)["t3"].endswith(first)
    o.sync(convo() + [Msg("u2", "user", "ok")])
    assert o.notice() is None  # the same tier does not fire again
    assert texts(o)["t3"].endswith(first)  # and the old notice has not moved


def test_state_survives_a_save_and_load(ov, tmp_path):
    ov.apply("replace", id="b0003", text="short")
    ov.apply("remove", ids=["b0005"])
    ov.apply("tracker", text="note")
    ov.save(tmp_path / "s" / "state.json")
    again = Overlay.open(tmp_path / "s" / "state.json")
    again.sync(convo())
    assert texts(again) == texts(ov) and again.tracker == "note" and again.limit == 4000


def test_shrink_clears_old_tool_output_then_removes_old_calls():
    o = Overlay()
    o.sync(convo())
    o.shrink(1200, keep_last=3)
    assert texts(o)["t1"] == CLEARED and texts(o)["t2"] is not None
    o.shrink(10, keep_last=3)
    assert texts(o)["a1"] is None and texts(o)["t1"] is None
    assert texts(o)["u1"] is not None  # never the user's message


def test_calibration_follows_the_hosts_real_count(ov):
    estimate = ov.tokens()
    ov.calibrate(estimate * 2)
    assert ov.tokens() == pytest.approx(estimate * 2, rel=0.01)


def test_keys_for_messages_without_ids():
    seen: dict = {}
    assert message_key("tool", "out", answers="c9", seen=seen) == "t:c9"
    assert message_key("assistant", "", ("c1", "c2"), seen=seen) == "a:c1"
    first = message_key("user", "hello", seen=seen)
    assert message_key("user", "hello", seen=seen) == first + "#2"  # a repeat is distinct


def test_json_interface_round_trip(tmp_path, monkeypatch, capsys):
    state = str(tmp_path / "state.json")
    messages = [{"role": m.role, "text": m.text, "calls": list(m.calls), "answers": m.answers}
                for m in convo()]
    first = run_json({"state": state, "limit": 40_000, "messages": messages, "describe": True})
    assert "clm_context" in first["prompt"] and first["tool"]["name"] == "clm_context"
    assert all(not v["changed"] for v in first["view"])

    request = {"state": state, "messages": messages, "in_flight": False,
               "op": {"action": "replace", "id": "b0003", "text": "short"}}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(request)))
    assert cli(["hostctx"]) == 0
    reply = json.loads(capsys.readouterr().out)
    assert reply["result"]["ok"] and reply["limit"] == 40_000  # the limit was remembered
    changed = [v for v in reply["view"] if v["changed"]]
    assert [v["text"] for v in changed] == ["short"] and changed[0]["key"] == "t:c1"

    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert cli(["hostctx"]) == 2 and "error" in json.loads(capsys.readouterr().out)
