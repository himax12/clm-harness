from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def user_config_dir() -> Path:
    """Where an installed harness keeps the user's settings.

    `%APPDATA%\\clm-harness` on Windows; `$XDG_CONFIG_HOME/clm-harness`, or
    `~/.config/clm-harness`, on macOS and Linux.
    """
    if os.name == "nt":
        base = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "clm-harness"


def user_env_file() -> Path:
    return user_config_dir() / ".env"


def save_user_key(name: str, value: str) -> Path:
    """Write one variable to the user's `.env`, replacing an earlier value of it.

    The file is readable by the user only, where the system supports that.
    """
    path = user_env_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    kept = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip().removeprefix("export ").partition("=")[0].strip() != name:
                kept.append(line)
    path.write_text("\n".join([*kept, f"{name}={value}"]) + "\n", encoding="utf-8", newline="\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def load_dotenv(*paths: Path) -> list[str]:
    """Set variables from `.env` files without overriding ones already in the environment.

    Unless paths are given, looks in the current directory, then the project root (a
    source checkout), then the user's config folder (an installed copy). Returns the
    names that were set.
    """
    paths = paths or (Path.cwd() / ".env", PROJECT_ROOT / ".env", user_env_file())
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
