import io
import os

import pytest

from clm_harness.cli import main as cli
from clm_harness.env import load_dotenv, save_user_key, user_env_file


def test_loads_values_and_ignores_comments_and_blanks(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OTHER", raising=False)
    env = tmp_path / ".env"
    env.write_text('# a comment\n\nANTHROPIC_API_KEY="sk-test"\nexport OTHER = two words\nEMPTY=\n')
    assert load_dotenv(env) == ["ANTHROPIC_API_KEY", "OTHER"]
    import os

    assert os.environ["ANTHROPIC_API_KEY"] == "sk-test" and os.environ["OTHER"] == "two words"
    assert "EMPTY" not in os.environ
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.delenv("OTHER")


def test_does_not_override_the_real_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-shell")
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=from-file\n")
    assert load_dotenv(env) == []
    import os

    assert os.environ["ANTHROPIC_API_KEY"] == "from-shell"


def test_missing_file_is_fine(tmp_path):
    assert load_dotenv(tmp_path / "nope.env") == []


@pytest.fixture
def config_home(tmp_path, monkeypatch):
    """Point the user's config folder at a temporary one, on every platform."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path / "clm-harness"


def test_user_config_folder_follows_the_platform(config_home):
    assert user_env_file() == config_home / ".env"


def test_saved_key_is_found_by_the_default_search(config_home, tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here
    monkeypatch.setattr("clm_harness.env.PROJECT_ROOT", tmp_path / "nowhere")
    monkeypatch.delenv("CLM_TEST_EXTRA", raising=False)
    save_user_key("ANTHROPIC_API_KEY", "sk-ant-first")
    save_user_key("CLM_TEST_EXTRA", "kept")
    save_user_key("ANTHROPIC_API_KEY", "sk-ant-second")  # replaces, does not append
    lines = user_env_file().read_text().splitlines()
    assert lines == ["CLM_TEST_EXTRA=kept", "ANTHROPIC_API_KEY=sk-ant-second"]
    try:
        assert set(load_dotenv()) == {"CLM_TEST_EXTRA", "ANTHROPIC_API_KEY"}
        assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-second"
    finally:  # load_dotenv writes to the real environment
        os.environ.pop("CLM_TEST_EXTRA", None)
        os.environ.pop("ANTHROPIC_API_KEY", None)


def test_setup_saves_a_key_from_stdin_without_printing_it(config_home, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("sk-ant-from-stdin\n"))
    assert cli(["setup", "--key-stdin", "--offline"]) == 0
    assert "ANTHROPIC_API_KEY=sk-ant-from-stdin" in user_env_file().read_text()
    out = capsys.readouterr()
    assert "sk-ant-from-stdin" not in out.out + out.err and str(user_env_file()) in out.out


def test_setup_with_no_key_saves_nothing(config_home, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("\n"))
    assert cli(["setup", "--key-stdin", "--offline"]) == 2
    assert not user_env_file().exists()


def test_setup_refuses_a_key_the_api_rejects(config_home, monkeypatch, capsys):
    def reject(model):
        raise PermissionError("invalid x-api-key")

    monkeypatch.setattr("clm_harness.llm.check_credential", reject)
    monkeypatch.setattr("sys.stdin", io.StringIO("sk-ant-bad\n"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert cli(["setup", "--key-stdin"]) == 1
    assert not user_env_file().exists() and "ANTHROPIC_API_KEY" not in os.environ
    assert "not accepted" in capsys.readouterr().err


def test_run_without_a_shell_says_what_to_install(monkeypatch, tmp_path, capsys):
    def no_bash():
        raise RuntimeError("Git Bash not found.")

    monkeypatch.setattr("clm_harness.cli._claude", lambda cfg: object())
    monkeypatch.setattr("clm_harness.shell.find_bash", no_bash)
    assert cli(["run", "do it", "--dir", str(tmp_path)]) == 2
    assert "Git Bash not found" in capsys.readouterr().err


def test_doctor_does_not_fail_for_missing_bash_when_docker_works(monkeypatch, tmp_path, capsys):
    def no_bash():
        raise RuntimeError("Git Bash not found.")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-a-real-key")
    monkeypatch.setattr("clm_harness.shell.find_bash", no_bash)
    monkeypatch.setattr("clm_harness.sandbox.docker_status", lambda: (True, "Docker 1.0"))
    assert cli(["doctor", "--offline", "--dir", str(tmp_path)]) == 0
    assert "--sandbox docker" in capsys.readouterr().out
    monkeypatch.setattr("clm_harness.sandbox.docker_status", lambda: (False, "docker not found"))
    assert cli(["doctor", "--offline", "--dir", str(tmp_path)]) == 1
