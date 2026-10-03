from __future__ import annotations

import re

_SPLIT = re.compile(r"\|\||&&|[;|&\n]")
_ROOT_TARGET = re.compile(r"^(/|~|\$HOME|\$\{HOME\}|/[A-Za-z]|[A-Za-z]:)[\\/]?\*?$")
_PATTERNS = [
    (re.compile(r"\bmkfs(\.\w+)?\b"), "formats a filesystem"),
    (re.compile(r"\bdd\b.*\bof=/dev/"), "writes directly to a device"),
    (re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"), "fork bomb"),
    (re.compile(r"\bformat\s+[A-Za-z]:", re.IGNORECASE), "formats a drive"),
]
_POWER = {"shutdown", "reboot", "halt", "poweroff"}
_HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
_SHELLS = {"bash", "sh", "zsh", "dash", "eval", "source", "."}


def _strip_heredoc_data(command: str) -> str:
    """Drop heredoc bodies unless they are fed to a shell.

    A heredoc written to a file is data, not a command: notes that merely mention
    `mkfs` must not be blocked. (Observed live: the model's notes about this very
    module were refused.)
    """
    lines = command.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        m = _HEREDOC.search(line)
        if not m:
            continue
        feeds_shell = any(t in _SHELLS for t in line[: m.start()].split())
        while i < len(lines) and lines[i].strip() != m.group(2):
            if feeds_shell:
                out.append(lines[i])
            i += 1
        i += 1  # the closing delimiter
    return "\n".join(out)


_GIT_OPTIONS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}


def _git_subcommand(tokens: list[str]) -> str | None:
    """`git -C dir push origin` -> "push". The word "push" as an argument does not count."""
    i = 1
    while i < len(tokens) and tokens[i].startswith("-"):
        i += 2 if tokens[i] in _GIT_OPTIONS_WITH_VALUE else 1
    return tokens[i] if i < len(tokens) else None


def blocked(command: str, allow_push: bool = False) -> str | None:
    """The reason a command must never run, or None. A floor, not a sandbox."""
    command = _strip_heredoc_data(command)
    flat = " ".join(command.split())
    for pattern, reason in _PATTERNS:
        if pattern.search(flat):
            return reason
    for segment in _SPLIT.split(command):
        tokens = segment.split()
        if tokens and tokens[0] == "sudo":
            tokens = tokens[1:]
        if not tokens:
            continue
        if tokens[0] in _POWER:
            return "shuts down or restarts the machine"
        if tokens[0] == "git" and _git_subcommand(tokens) == "push" and not allow_push:
            # Publishing is the one git action that cannot be undone locally.
            return "pushes to a git remote; the user must start the harness with --allow-push"
        if tokens[0] == "rm":
            flags = [t for t in tokens[1:] if t.startswith("-")]
            targets = [t.strip("\"'") for t in tokens[1:] if not t.startswith("-")]
            recursive = any(
                f == "--recursive" or (not f.startswith("--") and ("r" in f or "R" in f))
                for f in flags
            )
            if recursive and any(_ROOT_TARGET.match(t) for t in targets):
                return "recursively deletes a root or home directory"
    return None


def confirm(command: str) -> bool:
    print(f"\n$ {command}")
    return input("run this command? [y/N] ").strip().lower() in ("y", "yes")
