import io
import json
import subprocess
import sys

from clm_harness.cli import main as cli
from clm_harness.loop import ModelReply, ScriptedModel, run_command
from clm_harness.mcp import RUN_TASK, handle, run_task, serve


def talk(*messages, runner=None) -> list[dict]:
    """Send messages to the server and return its answers."""
    stdin = io.BytesIO(b"".join(json.dumps(m).encode() + b"\n" for m in messages))
    stdout = io.BytesIO()
    serve(stdin, stdout, runner or (lambda args: {"status": "finished", "answer": "ok"}))
    return [json.loads(line) for line in stdout.getvalue().splitlines()]


def test_handshake_and_tool_list():
    answers = talk(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},  # no answer expected
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "ping"},
    )
    assert [a["id"] for a in answers] == [1, 2, 3]
    assert answers[0]["result"]["protocolVersion"] == "2025-03-26"  # the client's version
    assert answers[0]["result"]["serverInfo"]["name"] == "clm-harness"
    tools = answers[1]["result"]["tools"]
    assert [t["name"] for t in tools] == ["run_task"]
    assert tools[0]["inputSchema"]["required"] == ["task", "dir"]
    assert answers[2]["result"] == {}


def test_unknown_protocol_version_gets_ours():
    answer = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": "1999-01-01"}})
    assert answer["result"]["protocolVersion"] == "2025-06-18"


def test_tool_call_returns_the_result_as_text():
    seen = {}

    def runner(args):
        seen.update(args)
        return {"status": "finished", "answer": "done", "dollars": 0.02, "session_dir": "/s"}

    [answer] = talk({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                     "params": {"name": "run_task", "arguments": {"task": "t", "dir": "/w"}}},
                    runner=runner)
    assert seen == {"task": "t", "dir": "/w"}
    result = answer["result"]
    assert result["isError"] is False
    assert json.loads(result["content"][0]["text"])["answer"] == "done"


def test_a_task_that_did_not_finish_or_raised_is_a_tool_error():
    def unfinished(args):
        return {"status": "cost_limit", "answer": ""}

    def broken(args):
        raise RuntimeError("the sandbox cannot start")

    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "run_task", "arguments": {}}}
    assert talk(call, runner=unfinished)[0]["result"]["isError"] is True
    failed = talk(call, runner=broken)[0]["result"]
    assert failed["isError"] is True and "sandbox cannot start" in failed["content"][0]["text"]


def test_protocol_errors():
    answers = talk(
        {"jsonrpc": "2.0", "id": 1, "method": "nope"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "other"}},
    )
    assert answers[0]["error"]["code"] == -32601 and answers[1]["error"]["code"] == -32602
    stdout = io.BytesIO()
    serve(io.BytesIO(b"not json\n\n"), stdout)
    assert json.loads(stdout.getvalue())["error"]["code"] == -32700


def test_run_task_checks_its_input_before_spending(tmp_path):
    for args, text in (({"task": "", "dir": str(tmp_path)}, "task"),
                       ({"task": "x", "dir": "relative/path"}, "absolute"),
                       ({"task": "x", "dir": str(tmp_path / "missing")}, "absolute")):
        try:
            run_task(args)
        except ValueError as e:
            assert text in str(e)
        else:
            raise AssertionError(f"accepted {args}")


def test_run_task_runs_the_loop_with_a_capped_cost(workdir, monkeypatch):
    made = {}

    def fake_model(cfg):
        made["cfg"] = cfg
        return ScriptedModel([run_command("echo hi > out.txt"), ModelReply(text="wrote it")])

    monkeypatch.setattr("clm_harness.cli._claude", fake_model)
    out = run_task({"task": "write a file", "dir": str(workdir), "sandbox": False,
                    "max_cost": 999})
    assert out["status"] == "finished" and out["answer"] == "wrote it"
    assert (workdir / "out.txt").read_text().strip() == "hi"
    assert made["cfg"].max_cost_usd == 2.0 and made["cfg"].sandbox == "none"  # the ceiling held


def test_sandbox_is_the_default_and_fails_clearly_without_docker(workdir, monkeypatch):
    monkeypatch.setattr("clm_harness.cli._claude", lambda cfg: ScriptedModel([]))
    monkeypatch.setattr("clm_harness.sandbox.docker_status", lambda: (False, "docker not found"))
    try:
        run_task({"task": "x", "dir": str(workdir)})
    except RuntimeError as e:
        assert "sandbox cannot start" in str(e) and "sandbox=false" in str(e)
    else:
        raise AssertionError("ran without a sandbox by default")


def test_the_real_command_speaks_the_protocol_on_clean_stdout():
    # Through a real process: nothing but protocol lines may reach stdout.
    request = (json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
               + "\n" + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n")
    done = subprocess.run([sys.executable, "-m", "clm_harness.cli", "mcp"], input=request.encode(),
                          capture_output=True, timeout=60)
    lines = done.stdout.splitlines()
    assert done.returncode == 0 and len(lines) == 2
    assert json.loads(lines[1])["result"]["tools"][0]["name"] == RUN_TASK["name"]


def test_run_json_flag_prints_one_object(workdir, monkeypatch, capsys):
    monkeypatch.setattr("clm_harness.cli._claude",
                        lambda cfg: ScriptedModel([ModelReply(text="all done")]))
    assert cli(["run", "say done", "--dir", str(workdir), "--json", "--quiet"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "finished" and out["answer"] == "all done"
    assert set(out) == {"status", "answer", "dollars", "session_dir"}
