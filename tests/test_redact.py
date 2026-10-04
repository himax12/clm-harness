import json

import pytest

from clm_harness.cli import main as cli
from clm_harness.config import Config
from clm_harness.loop import ModelReply, ScriptedModel, run, run_command
from clm_harness.redact import (REDACTED, Redactor, command_env, dotenv_files, is_secret_name,
                            removed_names, secret_values)

# Made-up values, built from pieces so that secret scanners do not flag this file.
FAKE_TOKEN = "tok-" + "0123456789abcdef"
FAKE_STRIPE = "sk_" + "live_" + "0123456789abcdefghij"


@pytest.mark.parametrize("name", [
    "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "GITHUB_TOKEN", "GH_TOKEN", "AWS_SECRET_ACCESS_KEY",
    "AWS_ACCESS_KEY_ID", "AWS_SESSION_TOKEN", "OPENAI_API_KEY", "NPM_TOKEN", "PGPASSWORD",
    "DB_PASSWD", "GOOGLE_APPLICATION_CREDENTIALS", "SSH_AUTH_SOCK", "MY_PRIVATE_THING",
    "DATABASE_URL", "stripe_secret", "Azure_Pat",
])
def test_secret_looking_names(name):
    assert is_secret_name(name)


@pytest.mark.parametrize("name", [
    "PATH", "HOME", "PWD", "OLDPWD", "TEMP", "USERNAME", "GIT_AUTHOR_NAME", "KEYBOARD_LAYOUT",
    "JAVA_HOME", "LANG", "TERM", "CI", "PYTHONPATH", "MONKEY", "AWS_REGION",
])
def test_ordinary_names(name):
    assert not is_secret_name(name)


def test_command_env_drops_secrets_and_keeps_the_rest(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    monkeypatch.setenv("ORDINARY_SETTING", "1")
    env = command_env()
    assert "GITHUB_TOKEN" not in env and "ANTHROPIC_API_KEY" not in env
    assert env["ORDINARY_SETTING"] == "1" and "PATH" in {k.upper() for k in env}
    assert {"GITHUB_TOKEN", "ANTHROPIC_API_KEY"} <= set(removed_names())


def test_passthrough_lets_a_named_variable_through(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    assert command_env(("github_token",))["GITHUB_TOKEN"] == "ghp_x"
    assert "GITHUB_TOKEN" not in removed_names(("GITHUB_TOKEN",))


def test_dotenv_files_skip_templates(workdir):
    for name in (".env", ".env.local", ".env.example", ".env.sample", "notenv"):
        (workdir / name).write_text("X=1\n")
    assert [p.name for p in dotenv_files(workdir)] == [".env", ".env.local"]


def test_secret_values_come_from_removed_variables_and_dotenv_files(workdir, monkeypatch):
    monkeypatch.setenv("DEPLOY_TOKEN", FAKE_TOKEN)
    monkeypatch.setenv("SHORT_TOKEN", "abc")  # too short to redact safely
    (workdir / ".env").write_text('DB_URL="postgres://u:hunter2hunter2@db/x"\nDEBUG=1\n')
    (workdir / ".env.example").write_text("DB_URL=placeholder-value-here\n")
    values = secret_values(workdir)
    assert FAKE_TOKEN in values and "postgres://u:hunter2hunter2@db/x" in values
    assert "abc" not in values and "1" not in values and "placeholder-value-here" not in values


def test_redactor_replaces_known_values_longest_first():
    r = Redactor({"secretvalue", "secretvalue-extended"})
    assert r("a secretvalue-extended b secretvalue c") == f"a {REDACTED} b {REDACTED} c"


@pytest.mark.parametrize("text", [
    "key=sk-ant-api03-" + "a" * 40,
    "ghp_" + "A1" * 18,
    "github_pat_" + "b" * 50,
    "AKIA" + "ABCDEFGH12345678",
    "xoxb-1234567890-abcdefghij",
    "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nabc\n-----END RSA PRIVATE KEY-----",
])
def test_redactor_recognises_common_key_formats(text):
    out = Redactor()(f"before {text} after")
    assert REDACTED in out and out.startswith("before ") and out.endswith(" after")
    assert text.split("=")[-1][:12] not in out


def test_redactor_leaves_ordinary_text_alone():
    text = "sk-short ghp_tiny AKIA123 a normal line of output"
    assert Redactor({"unrelated-secret"})(text) == text


def events(result):
    lines = (result.session_dir / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def test_secrets_never_reach_the_context_the_transcript_or_saved_output(workdir, monkeypatch):
    monkeypatch.setenv("DEPLOY_TOKEN", FAKE_TOKEN)
    (workdir / ".env").write_text(f"STRIPE={FAKE_STRIPE}\n")
    cfg = Config(inline_chars=200, head_chars=50, tail_chars=50)  # force a saved output file
    model = ScriptedModel([
        run_command('echo "[$DEPLOY_TOKEN]"'),          # the variable is not even set
        run_command("cat .env; seq 1 200"),             # the file is readable, the value redacted
        ModelReply(text="done"),
    ])
    result = run("t", workdir, cfg, model)

    assert "[]" in model.seen[1]
    assert REDACTED in model.seen[2]
    everything = model.seen[2] + (result.session_dir / "transcript.jsonl").read_text(encoding="utf-8")
    for path in (result.session_dir / "outputs").iterdir():
        everything += path.read_text(encoding="utf-8")
    for path in (result.session_dir / "blocks").iterdir():
        everything += path.read_text(encoding="utf-8")
    assert FAKE_STRIPE not in everything
    assert FAKE_TOKEN not in everything

    start = events(result)[0]
    assert start["env_removed"] >= 1 and start["secrets_redacted"] >= 2


def test_doctor_offline_reports_shell_and_credential(workdir, monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-a-real-key")
    (workdir / ".env").write_text("X=y\n")
    assert cli(["doctor", "--offline", "--dir", str(workdir)]) == 0
    out = capsys.readouterr().out
    assert "ok    bash" in out and "credential: found in ANTHROPIC_API_KEY" in out
    assert "sk-ant-not-a-real-key" not in out
    assert "ANTHROPIC_API_KEY" in out and "readable by the agent" in out


def test_doctor_fails_without_a_credential(workdir, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr("clm_harness.cli.load_dotenv", lambda: [])
    assert cli(["doctor", "--offline", "--dir", str(workdir)]) == 1
    assert "FAIL  credential" in capsys.readouterr().out
