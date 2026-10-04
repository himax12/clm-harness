"""Running the agent's commands in a Docker container instead of on the host.

One container lives for the whole run. The working folder is mounted at /work and the
session folder at /session; nothing else of the host is visible. By default the
container has no network, no Linux capabilities, and limits on memory, CPU and the
number of processes. `.env` files in the working folder are covered by an empty file.

What this does not do: it does not limit how much the agent writes into the working
folder, and it is only as strong as Docker's own isolation.
"""
from __future__ import annotations

import os
import secrets
import shutil
import subprocess
from pathlib import Path

from .config import SANDBOX_IMAGE as IMAGE
from .config import Config
from .redact import dotenv_files

# Built on first use when the default image is missing. Small on purpose: bash, git,
# Python and the usual text tools.
DOCKERFILE = """\
FROM python:3.12-slim
RUN apt-get update \\
 && apt-get install -y --no-install-recommends git curl ca-certificates procps patch jq make \\
 && rm -rf /var/lib/apt/lists/*
"""
WORK = "/work"
SESSION = "/session"

# Ends the last command by killing its process group. The pid file is written by run.sh;
# docker starts each exec'd process as the leader of its own group, and field 5 of
# /proc/<pid>/stat confirms the group. Fails unless the group is gone afterwards.
_KILL = (
    'p=$(cat "$0" 2>/dev/null) || exit 0; set -- $(cat "/proc/$p/stat" 2>/dev/null); '
    'g=${5:-$p}; [ "$g" -gt 1 ] || exit 1; '
    'kill -9 -- "-$g" 2>/dev/null || ! kill -0 -- "-$g" 2>/dev/null'
)
# Output goes straight to a file in the session folder. If it went through docker's
# pipe, a background job would hold the pipe open and `docker exec` would not return.
_EXEC = 'exec bash "$0" > "$1" 2>&1 < /dev/null'


def find_docker() -> str:
    found = shutil.which("docker")
    if not found:
        raise RuntimeError("docker not found. Install Docker, or run without --sandbox docker.")
    return found


def docker_status(timeout: int = 20) -> tuple[bool, str]:
    """Whether Docker can run Linux containers right now, and a line saying so."""
    try:
        docker = find_docker()
        done = subprocess.run(
            [docker, "version", "--format", "{{.Server.Version}} {{.Server.Os}}"],
            capture_output=True, text=True, timeout=timeout,
        )
    except RuntimeError as e:
        return False, str(e)
    except subprocess.TimeoutExpired:
        return False, f"the Docker engine did not answer within {timeout} s; is it running?"
    if done.returncode != 0:
        lines = (done.stderr or done.stdout).strip().splitlines()
        return False, lines[-1] if lines else "docker version failed"
    version, _, server_os = done.stdout.strip().partition(" ")
    if server_os != "linux":
        return False, f"Docker is set to {server_os or 'unknown'} containers; Linux is needed"
    return True, f"Docker {version}"


def _mount(source: Path, target: str, readonly: bool = False) -> list[str]:
    if "," in str(source):
        raise RuntimeError(f"cannot mount a path that contains a comma: {source}")
    spec = f"type=bind,source={source},target={target}"
    return ["--mount", spec + (",readonly" if readonly else "")]


def run_argv(docker: str, name: str, image: str, workdir: Path, session_dir: Path,
             cfg: Config, masked: list[Path], empty: Path) -> list[str]:
    """The `docker run` command that starts the container."""
    # The container ends by itself a little after the run's own time limit, so a
    # harness that dies without cleaning up does not leave it running for ever.
    lifetime = str(cfg.max_wall_seconds + 900) if cfg.max_wall_seconds else "infinity"
    argv = [
        docker, "run", "--detach", "--rm", "--init", "--name", name,
        "--label", "clm-harness=1",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--memory", cfg.sandbox_memory, "--cpus", str(cfg.sandbox_cpus),
        "--pids-limit", str(cfg.sandbox_pids),
        "--tmpfs", "/tmp:rw,exec,mode=1777,size=1g",
        "--workdir", WORK,
        # The mounted folder belongs to another user as far as git can tell.
        "-e", "GIT_CONFIG_COUNT=1", "-e", "GIT_CONFIG_KEY_0=safe.directory",
        "-e", "GIT_CONFIG_VALUE_0=*",
    ]
    if not cfg.sandbox_network:
        argv += ["--network", "none"]
    if os.name != "nt":
        # Files the agent creates should belong to the user, not to root.
        argv += ["--user", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp"]
    argv += _mount(workdir, WORK) + _mount(session_dir, SESSION)
    for path in masked:
        argv += _mount(empty, f"{WORK}/{path.name}", readonly=True)
    return argv + [image, "sleep", lifetime]


def exec_argv(docker: str, name: str, script: str, sink: str,
              passthrough: tuple[str, ...] = ()) -> list[str]:
    """The `docker exec` command that runs one command script in the container."""
    argv = [docker, "exec"]
    for var in passthrough:
        if var in os.environ:
            argv += ["-e", var]  # no value: docker takes it from our environment
    return argv + [name, "bash", "-c", _EXEC, script, sink]


class Sandbox:
    def __init__(self, workdir: Path, session_dir: Path, cfg: Config):
        self.workdir = Path(workdir).resolve()
        self.session_dir = Path(session_dir).resolve()
        self.cfg = cfg
        self.docker = find_docker()
        self.name = f"clm-{secrets.token_hex(6)}"
        self.started = False

    def path(self, path: Path) -> str:
        """Where a host path is inside the container."""
        path = Path(path).resolve()
        for root, inside in ((self.session_dir, SESSION), (self.workdir, WORK)):
            if path == root or root in path.parents:
                rel = path.relative_to(root).as_posix()
                return inside if rel == "." else f"{inside}/{rel}"
        raise ValueError(f"{path} is not visible in the sandbox")

    def _docker(self, *args: str, timeout: int, stdin: str | None = None):
        try:
            return subprocess.run([self.docker, *args], capture_output=True, text=True,
                                  timeout=timeout, input=stdin)
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"docker {args[0]} did not finish within {timeout} s; is Docker running?"
            ) from None

    def _ensure_image(self) -> None:
        image = self.cfg.sandbox_image
        if image != IMAGE:
            return  # `docker run` pulls any other image by itself
        if self._docker("image", "inspect", image, timeout=60).returncode == 0:
            return
        built = self._docker("build", "-t", image, "-", timeout=1_200, stdin=DOCKERFILE)
        if built.returncode != 0:
            raise RuntimeError(f"could not build the sandbox image: {built.stderr.strip()[-400:]}")

    def start(self) -> None:
        self._ensure_image()
        empty = self.session_dir / "state" / "empty"
        empty.parent.mkdir(parents=True, exist_ok=True)
        empty.write_bytes(b"")
        argv = run_argv(self.docker, self.name, self.cfg.sandbox_image, self.workdir,
                        self.session_dir, self.cfg, dotenv_files(self.workdir), empty)
        done = self._docker(*argv[1:], timeout=600)
        if done.returncode != 0:
            raise RuntimeError(f"could not start the sandbox: {done.stderr.strip()[-400:]}")
        self.started = True

    def exec_argv(self, script: Path, sink: Path) -> list[str]:
        return exec_argv(self.docker, self.name, self.path(script), self.path(sink),
                         self.cfg.env_passthrough)

    def kill_command(self, pid_file: Path) -> None:
        """End the running command and what it started. If that cannot be done, end
        the whole container; the next command starts a new one."""
        try:
            # bash, not sh: dash's `kill` does not accept `--` before a negative pid.
            done = self._docker("exec", self.name, "bash", "-c", _KILL, self.path(pid_file),
                                timeout=20)
            if done.returncode == 0:
                return
        except RuntimeError:
            pass
        self.close()

    def close(self) -> None:
        """Remove the container, ending everything in it."""
        if not self.started:
            return
        self.started = False
        try:
            self._docker("rm", "--force", self.name, timeout=60)
        except RuntimeError:
            pass  # it still ends by itself: see `lifetime` in run_argv
