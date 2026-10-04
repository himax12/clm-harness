from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .budget import Estimator
from .config import Config
from .redact import command_env
from .sandbox import Sandbox


@dataclass
class CommandResult:
    output: str  # stdout and stderr merged
    exit_code: int  # -1 when the harness killed it
    timed_out: bool
    seconds: float
    output_limit: bool = False  # killed for printing too much


def find_bash() -> str:
    override = os.environ.get("HARNESS_BASH")
    if override:
        return override
    if os.name != "nt":
        return "/bin/bash"
    for candidate in (
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
    ):
        if Path(candidate).exists():
            return candidate
    found = shutil.which("bash")
    # System32 and WindowsApps hold the WSL launcher, not a usable bash.
    if found and "system32" not in found.lower() and "windowsapps" not in found.lower():
        return found
    raise RuntimeError("Git Bash not found. Install Git for Windows or set HARNESS_BASH.")


def to_posix(path: Path) -> str:
    p = str(Path(path).resolve())
    if os.name != "nt":
        return p
    drive, rest = os.path.splitdrive(p)
    rest = rest.replace("\\", "/")
    return f"/{drive[0].lower()}{rest}" if drive else rest


def _q(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def _write(path: Path, text: str) -> None:
    # Bash chokes on CRLF, which is what Windows text mode would write.
    path.write_text(text, encoding="utf-8", newline="\n")


class Shell:
    """Runs each command in a fresh bash, carrying cwd and exported variables across."""

    def __init__(self, workdir: Path, session_dir: Path, cfg: Config):
        self.workdir = Path(workdir).resolve()
        self.cfg = cfg
        self.state = Path(session_dir) / "state"
        self.state.mkdir(parents=True, exist_ok=True)
        self.run_sh = self.state / "run.sh"
        self.user_sh = self.state / "user_cmd.sh"
        self._runs = 0
        self._jobs: list[int] = []  # Windows job handles, one per command
        # With a sandbox, commands run in a container: the host needs no bash, and
        # every path the scripts mention is the path inside the container.
        self.sandbox = Sandbox(self.workdir, session_dir, cfg) if cfg.sandbox == "docker" else None
        self.bash = None if self.sandbox else find_bash()
        self._inside = self.sandbox.path if self.sandbox else to_posix
        state = _q(self._inside(self.state))
        _write(
            self.run_sh,
            "\n".join(
                [
                    f"STATE={state}",
                    # The sandbox ends a timed-out command through this pid.
                    *(['echo $$ > "$STATE/pid"'] if self.sandbox else []),
                    '__save_state() { pwd > "$STATE/cwd"; export -p > "$STATE/env.sh"; }',
                    "trap __save_state EXIT",
                    '[ -f "$STATE/env.sh" ] && . "$STATE/env.sh" 2>/dev/null',
                    f'cd "$(cat "$STATE/cwd")" 2>/dev/null || cd {_q(self._inside(self.workdir))}',
                    f"export CTX={_q(self._inside(Path(session_dir) / 'LIVE_CTX.md'))}",
                    f"export CTX_DIR={_q(self._inside(Path(session_dir)))}",
                    "export CI=true TERM=dumb PAGER=cat GIT_PAGER=cat",
                    '. "$STATE/user_cmd.sh"',
                    "",
                ]
            ),
        )
        self.reset()

    def reset(self) -> None:
        """Forget the saved working directory and environment."""
        _write(self.state / "cwd", self._inside(self.workdir) + "\n")
        (self.state / "env.sh").unlink(missing_ok=True)

    def scripting_hint(self) -> str:
        """Name a scripting tool that really works in this shell.

        On Windows `python3` is often a Store stub that only prints an install hint.
        """
        hint = "`perl -0pi -e`"
        for name in ("python3", "python"):
            result = self.run(f'{name} -c "print(41 + 1)"')
            if result.exit_code == 0 and result.output.strip() == "42":
                hint = f"`{name}` and `re.sub`"
                break
        self.reset()
        return hint

    def run(self, command: str) -> CommandResult:
        _write(self.user_sh, command + "\n")
        started = time.monotonic()
        kwargs: dict = {}
        job = _new_job()
        if os.name == "nt":
            # Start suspended so the process is inside its job before it can spawn anything.
            suspended = _CREATE_SUSPENDED if job else 0
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | suspended
        else:
            kwargs["start_new_session"] = True
        # Output goes to a file, not a pipe. With a pipe, a background job (`server &`)
        # keeps the pipe open and the turn hangs until the job exits; and a command that
        # prints gigabytes is buffered whole in memory. A file lets us wait on bash alone
        # and watch the size while it runs.
        self._runs += 1
        sink_path = self.state / f"out-{self._runs}.bin"
        timed_out = too_big = False
        with open(sink_path, "wb") as sink:
            if self.sandbox:
                if not self.sandbox.started:
                    self.sandbox.start()
                # The command writes to the sink from inside the container; what the
                # docker client itself prints (an engine error) is kept apart.
                argv = self.sandbox.exec_argv(self.run_sh, sink_path)
                streams = {"stdout": subprocess.DEVNULL, "stderr": subprocess.PIPE}
            else:
                argv = [self.bash, self.run_sh.as_posix()]
                streams = {"stdout": sink, "stderr": subprocess.STDOUT,
                           "env": command_env(self.cfg.env_passthrough)}
            deadline = time.monotonic() + self.cfg.command_timeout
            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, **streams, **kwargs)
            if job:
                job = _adopt(job, proc)
            if job:
                self._jobs.append(job)
            while True:
                try:
                    proc.wait(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() >= deadline:
                        timed_out = True
                    elif sink_path.stat().st_size > self.cfg.max_output_bytes:
                        too_big = True
                    else:
                        continue
                    if self.sandbox:
                        self.sandbox.kill_command(self.state / "pid")
                    self._kill_tree(proc, job)
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        pass
                    break
        raw = _read_capped(sink_path, self.cfg.max_output_bytes)
        if self.sandbox and not (timed_out or too_big):
            engine = proc.stderr.read().strip()
            if engine:
                raw += b"\n[sandbox] " + engine
        if proc.stderr:
            proc.stderr.close()
        for _ in range(20):  # a killed process can take a moment to release the file
            try:
                sink_path.unlink()
                break
            except OSError:
                if not (timed_out or too_big):
                    break  # a background job still holds it open; that is allowed
                time.sleep(0.1)
        text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n")
        killed = timed_out or too_big
        return CommandResult(
            output=text,
            exit_code=-1 if killed else proc.returncode,
            timed_out=timed_out,
            seconds=time.monotonic() - started,
            output_limit=too_big,
        )

    @staticmethod
    def _kill_tree(proc: subprocess.Popen, job: int | None = None) -> None:
        """Kill a command and everything it started."""
        if os.name == "nt":
            if job:
                _kernel32.TerminateJobObject(job, 1)
            # Also by parent link, for the rare case the job could not be set up.
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        else:
            import signal

            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def close(self) -> None:
        """End every process any command started, including background jobs.

        With a sandbox the container is removed. Without one this works on Windows
        only, where each command runs in its own job object; on POSIX a background
        job that outlives its command is left running.
        """
        if self.sandbox:
            self.sandbox.close()
        for job in self._jobs:
            _kernel32.TerminateJobObject(job, 1)
            _kernel32.CloseHandle(job)
        self._jobs.clear()


# On Windows, killing a process by its parent link (taskkill /T) does not reliably reach
# the children Git Bash starts: a command like `yes` survived its own timeout and kept
# writing to disk. A job object contains every descendant, whatever its parent link, and
# TerminateJobObject ends them all.
_CREATE_SUSPENDED = 0x00000004
if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")
    _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]


def _new_job() -> int | None:
    if os.name != "nt":
        return None
    return _kernel32.CreateJobObjectW(None, None) or None


def _adopt(job: int, proc: subprocess.Popen) -> int | None:
    """Put a suspended process into the job, then let it run. Returns the job, or None
    if the process could not be put in it."""
    handle = int(proc._handle)
    ok = _kernel32.AssignProcessToJobObject(job, handle)
    _ntdll.NtResumeProcess(handle)
    if not ok:
        _kernel32.CloseHandle(job)
        return None
    return job


def _read_capped(path: Path, cap: int) -> bytes:
    """Read a command's output, keeping at most `cap` bytes: the start and the end."""
    size = path.stat().st_size
    with open(path, "rb") as f:
        if size <= cap:
            return f.read()
        head = f.read(cap // 2)
        f.seek(size - cap // 2)
        tail = f.read()
    return head + f"\n... [{size - cap:,} bytes omitted by the harness] ...\n".encode() + tail


def _elide(text: str, head: int, tail: int, pointer: str) -> str:
    gone = len(text) - head - tail
    return (
        text[:head]
        + f"\n... [{gone:,} characters elided; full output at {pointer}] ...\n"
        + text[len(text) - tail :]
    )


def format_observation(result: CommandResult, name: str, outputs_dir: Path, cfg: Config) -> str:
    """Turn a command result into the text the model sees.

    Output over the inline limit is saved in full to outputs/<name>.txt and cut to
    its head and tail.
    """
    text = result.output.rstrip() or "(no output)"
    if len(text) > cfg.inline_chars:
        _write(outputs_dir / f"{name}.txt", text)
        text = _elide(text, cfg.head_chars, cfg.tail_chars, f'"$CTX_DIR"/outputs/{name}.txt')
    if result.timed_out:
        text += f"\n(timed out after {cfg.command_timeout} s; partial output shown)"
    if result.output_limit:
        text += (f"\n(killed: output passed {cfg.max_output_bytes // 1_000_000} MB; "
                 "partial output shown. Print less, or redirect to a file.)")
    return f"{text}\n(exit_code={result.exit_code})"


def cap_to_room(
    observation: str, room_tokens: int, est: Estimator, name: str, outputs_dir: Path
) -> str:
    """Cut an observation so that it fits in the remaining context room."""
    room_tokens = max(room_tokens, 128)
    if est.tokens(observation) <= room_tokens:
        return observation
    path = outputs_dir / f"{name}.txt"
    if not path.exists():
        _write(path, observation)
    keep_chars = max(int(room_tokens * 4 / est.ratio) - 200, 200)
    half = keep_chars // 2
    return _elide(observation, half, half, f'"$CTX_DIR"/outputs/{name}.txt')
