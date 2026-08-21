import pathlib
import re

from dotenv import dotenv_values


def get_env_values(env_path: pathlib.Path) -> dict:
    """Read an env file, resolving ${VAR} interpolation, into a plain dict."""
    return dict(dotenv_values(env_path, interpolate=True))


def update_env_value(env_path: pathlib.Path, key: str, value: str) -> None:
    """Set ``key`` to ``value`` in the env file at ``env_path``.

    Updates the existing ``KEY=...`` line in place if present, otherwise
    appends a new one. Every other line is left untouched.
    """
    text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    lines = text.splitlines()

    quoted_value = f"'{value}'" if value else ""
    new_line = f"{key}={quoted_value}"
    pattern = re.compile(rf"^{re.escape(key)}=")

    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = new_line
            break
    else:
        lines.append(new_line)

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
