from pathlib import Path

import pytest

from harness.budget import Estimator
from harness.config import Config
from harness.context import Context
from harness.shell import Shell, find_bash


def _has_bash() -> bool:
    try:
        return Path(find_bash()).exists()
    except RuntimeError:
        return False


def pytest_collection_modifyitems(config, items):
    """Without bash, skip the tests that run real commands instead of failing them."""
    if _has_bash():
        return
    skip = pytest.mark.skip(reason="needs bash (Git Bash on Windows)")
    for item in items:
        if {"workdir", "shell"} & set(getattr(item, "fixturenames", ())) or "matrix" in item.name:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def no_real_dotenv(monkeypatch):
    """Tests must never load the developer's real API key from the project's .env."""
    monkeypatch.setattr("harness.cli.load_dotenv", lambda: [])


@pytest.fixture
def workdir(tmp_path):
    # A space in the path on purpose: the real project path has them.
    d = tmp_path / "work dir"
    d.mkdir()
    return d


@pytest.fixture
def session_dir(tmp_path):
    d = tmp_path / "sess dir"
    (d / "outputs").mkdir(parents=True)
    return d


@pytest.fixture
def shell(workdir, session_dir):
    return Shell(workdir, session_dir, Config(command_timeout=30))


@pytest.fixture
def est():
    return Estimator()


def make_ctx(*blocks: tuple[str, str]) -> Context:
    ctx = Context(pinned="the task")
    for role, body in blocks:
        ctx.add(role, body)
    return ctx
