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
        self.bash = find_bash()
        self.state = Path(session_dir) / "state"
        self.state.mkdir(parents=True, exist_ok=True)
        self.run_sh = self.state / "run.sh"
        self.user_sh = self.state / "user_cmd.sh"
        self._runs = 0
        state = _q(to_posix(self.state))
        _write(
            self.run_sh,
            "\n".join(
                [
                    f"STATE={state}",
                    '__save_state() { pwd > "$STATE/cwd"; export -p > "$STATE/env.sh"; }',
                    "trap __save_state EXIT",
                    '[ -f "$STATE/env.sh" ] && . "$STATE/env.sh" 2>/dev/null',
                    f'cd "$(cat "$STATE/cwd")" 2>/dev/null || cd {_q(to_posix(self.workdir))}',
                    f"export CTX={_q(to_posix(Path(session_dir) / 'LIVE_CTX.md'))}",
                    f"export CTX_DIR={_q(to_posix(Path(session_dir)))}",
                    "export CI=true TERM=dumb PAGER=cat GIT_PAGER=cat",
                    '. "$STATE/user_cmd.sh"',
                    "",
                ]
            ),
        )
        self.reset()

    def reset(self) -> None:
        """Forget the saved working directory and environment."""
        _write(self.state / "cwd", to_posix(self.workdir) + "\n")
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
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        # Output goes to a file, not a pipe. With a pipe, a background job (`server &`)
        # keeps the pipe open and the turn hangs until the job exits; and a command that
        # prints gigabytes is buffered whole in memory. A file lets us wait on bash alone
        # and watch the size while it runs.
        self._runs += 1
        sink_path = self.state / f"out-{self._runs}.bin"
        deadline = started + self.cfg.command_timeout
        timed_out = too_big = False
        with open(sink_path, "wb") as sink:
            proc = subprocess.Popen(
                [self.bash, self.run_sh.as_posix()],
                stdout=sink,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=command_env(self.cfg.env_passthrough),
                **kwargs,
            )
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
                    self._kill_tree(proc)
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        pass
                    break
        raw = _read_capped(sink_path, self.cfg.max_output_bytes)
        try:
            sink_path.unlink()
        except OSError:
            pass  # a background job may still hold it open
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
    def _kill_tree(proc: subprocess.Popen) -> None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                capture_output=True,
            )
        else:
            import signal

            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


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
