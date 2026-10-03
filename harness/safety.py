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


def blocked(command: str) -> str | None:
    """The reason a command must never run, or None. A floor, not a sandbox."""
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
