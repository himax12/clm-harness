"""Keeping secrets away from the agent, and out of what the harness stores.

Two layers, neither of which is a sandbox:

- the agent's commands run without secret-looking environment variables;
- known secret values and common key formats are replaced in command output before
  that output reaches the model's context, the transcript or a saved output file.

A command can still read a secret file and send it over the network. Only an OS
sandbox stops that.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .env import PROJECT_ROOT

REDACTED = "[REDACTED]"
MIN_SECRET_LEN = 8  # shorter values are too likely to be ordinary words

_SUBSTRINGS = ("TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL")
_PARTS = {"KEY", "APIKEY", "AUTH", "PRIVATE", "PAT"}
_EXACT = {"DATABASE_URL"}
_PREFIXES = ("ANTHROPIC_",)

# Formats recognisable on sight, whether or not the harness knows the value.
_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{32,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{40,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
]


def is_secret_name(name: str) -> bool:
    upper = name.upper()
    if upper in _EXACT or upper.startswith(_PREFIXES):
        return True
    if any(s in upper for s in _SUBSTRINGS):
        return True
    return any(part in _PARTS for part in upper.split("_"))


def command_env(passthrough: tuple[str, ...] = ()) -> dict[str, str]:
    """The environment the agent's commands run in: everything except secrets."""
    allowed = {name.upper() for name in passthrough}
    return {
        k: v for k, v in os.environ.items() if k.upper() in allowed or not is_secret_name(k)
    }


def removed_names(passthrough: tuple[str, ...] = ()) -> list[str]:
    kept = command_env(passthrough)
    return sorted(k for k in os.environ if k not in kept)


def _dotenv_values(path: Path) -> list[str]:
    values = []
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        value = line.partition("=")[2].strip().strip("\"'")
        if value:
            values.append(value)
    return values


def dotenv_files(workdir: Path) -> list[Path]:
    """`.env` files in the working folder, other than templates."""
    skip = (".example", ".sample", ".template")
    return sorted(
        p for p in Path(workdir).glob(".env*") if p.is_file() and not p.name.endswith(skip)
    )


def secret_values(workdir: Path, passthrough: tuple[str, ...] = ()) -> set[str]:
    """Values the harness knows to be secret: removed variables and `.env` contents."""
    values = {os.environ[name] for name in removed_names(passthrough)}
    for path in [*dotenv_files(workdir), PROJECT_ROOT / ".env"]:
        values.update(_dotenv_values(path))
    return {v for v in values if len(v) >= MIN_SECRET_LEN}


class Redactor:
    def __init__(self, values: set[str] = frozenset()):
        # Longest first, so a value that contains another is replaced whole.
        self.values = sorted(values, key=len, reverse=True)

    def __call__(self, text: str) -> str:
        for value in self.values:
            if value in text:
                text = text.replace(value, REDACTED)
        for pattern in _PATTERNS:
            text = pattern.sub(REDACTED, text)
        return text
