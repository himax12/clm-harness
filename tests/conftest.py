import pytest

from harness.budget import Estimator
from harness.config import Config
from harness.context import Context
from harness.shell import Shell


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
