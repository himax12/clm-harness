from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(*paths: Path) -> list[str]:
    """Set variables from `.env` files without overriding ones already in the environment.

    Looks in the current directory and the project root unless paths are given.
    Returns the names that were set.
    """
    paths = paths or (Path.cwd() / ".env", PROJECT_ROOT / ".env")
    loaded: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.removeprefix("export ").partition("=")
            name, value = name.strip(), value.strip().strip("\"'")
            if name and value and name not in os.environ:
                os.environ[name] = value
                loaded.append(name)
    return loaded
