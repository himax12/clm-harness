from harness.env import load_dotenv


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
