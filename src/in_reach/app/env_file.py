"""Reads and writes a project's ``.env`` file.

Small enough that it doesn't need python-dotenv's own writer -- every write here is a single
``KEY=value`` line edit made directly against the raw text, leaving every other line untouched.
"""

from __future__ import annotations

import re
from pathlib import Path


def get_env_values(env_path: Path) -> dict[str, str]:
    """Parses ``KEY=value`` pairs out of an ``.env`` file.

    Args:
        env_path: Path to the project's ``.env`` file.

    Returns:
        A dict of the file's key/value pairs. ``{}`` if the file doesn't exist yet.
    """
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip("'\"")
    return values


def update_env_value(env_path: Path, key: str, value: str) -> None:
    """Sets ``key`` to ``value`` in ``env_path``, in place.

    Updates the existing ``KEY=...`` line if present, otherwise appends a new one at the end.

    Args:
        env_path: Path to the project's ``.env`` file.
        key: Env var name to set.
        value: Value to assign.
    """
    text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    lines = text.splitlines()

    new_line = f"{key}={value}"
    pattern = re.compile(rf"^{re.escape(key)}=")

    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = new_line
            break
    else:
        lines.append(new_line)

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
