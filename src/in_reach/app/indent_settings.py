"""Indent-style preference (spaces vs. tabs, and width) -- backs the bottom status bar's "Spaces:
N" segment and its "Select Action" indentation commands (PROMPT.md: quick-access bar work).

Persisted the same way :mod:`in_reach.ide.zoom` persists ``UI_ZOOM``: one shared pair of keys in
the project-root ``.in-reach/.env``, not per individual gametype project -- an IDE-wide editing
preference, not something that should vary file to file.
"""

from __future__ import annotations

import math
from pathlib import Path

from in_reach.app import env_file

INDENT_STYLE_KEY = "INDENT_STYLE"
INDENT_WIDTH_KEY = "INDENT_WIDTH"

STYLE_SPACES = "spaces"
STYLE_TABS = "tabs"

DEFAULT_INDENT_STYLE = STYLE_SPACES
DEFAULT_INDENT_WIDTH = 4
MIN_INDENT_WIDTH = 1
MAX_INDENT_WIDTH = 8


def _clamp_width(width: int) -> int:
    return max(MIN_INDENT_WIDTH, min(MAX_INDENT_WIDTH, width))


def get_indent(env_path: Path) -> tuple[str, int]:
    """Reads the saved indent style/width.

    Args:
        env_path: Path to the project's ``.env`` file.

    Returns:
        ``(style, width)`` -- ``style`` is :data:`STYLE_SPACES` or :data:`STYLE_TABS`, ``width``
        clamped to ``[``:data:`MIN_INDENT_WIDTH` ``, ``:data:`MAX_INDENT_WIDTH` ``]``. Falls back to
        :data:`DEFAULT_INDENT_STYLE`/:data:`DEFAULT_INDENT_WIDTH` for anything missing/unparsable.
    """
    values = env_file.get_env_values(env_path)
    style = values.get(INDENT_STYLE_KEY, "")
    if style not in (STYLE_SPACES, STYLE_TABS):
        style = DEFAULT_INDENT_STYLE
    try:
        width = _clamp_width(int(values.get(INDENT_WIDTH_KEY, "")))
    except ValueError:
        width = DEFAULT_INDENT_WIDTH
    return style, width


def set_indent(env_path: Path, style: str, width: int) -> tuple[str, int]:
    """Clamps and writes ``style``/``width`` back to the project's ``.env``.

    Args:
        env_path: Path to the project's ``.env`` file.
        style: :data:`STYLE_SPACES` or :data:`STYLE_TABS`.
        width: Spaces per indent level.

    Returns:
        The values actually stored, after clamping.
    """
    if style not in (STYLE_SPACES, STYLE_TABS):
        style = DEFAULT_INDENT_STYLE
    width = _clamp_width(width)
    env_file.update_env_value(env_path, INDENT_STYLE_KEY, style)
    env_file.update_env_value(env_path, INDENT_WIDTH_KEY, str(width))
    return style, width


def _leading_whitespace(line: str) -> tuple[str, str]:
    """Splits ``line`` into its leading run of spaces/tabs and the rest."""
    index = 0
    while index < len(line) and line[index] in " \t":
        index += 1
    return line[:index], line[index:]


def convert_to_spaces(text: str, width: int) -> str:
    """Rewrites every line's own leading tabs to ``width`` spaces each (leading whitespace only --
    never touches a tab/space that isn't part of a line's own indentation)."""
    width = _clamp_width(width)
    lines = text.split("\n")
    return "\n".join(
        leading.replace("\t", " " * width) + rest for leading, rest in (_leading_whitespace(line) for line in lines)
    )


def convert_to_tabs(text: str, width: int) -> str:
    """Rewrites every line's own leading run of ``width``-space groups to tabs, one tab per full
    group (a partial trailing group of fewer than ``width`` spaces is left as spaces)."""
    width = _clamp_width(width)
    lines = text.split("\n")
    converted = []
    for line in lines:
        leading, rest = _leading_whitespace(line)
        expanded = leading.expandtabs(width)
        full_groups, remainder = divmod(len(expanded), width)
        converted.append("\t" * full_groups + " " * remainder + rest)
    return "\n".join(converted)


def trim_trailing_whitespace(text: str) -> str:
    """Strips trailing spaces/tabs from every line, leaving line endings and content otherwise
    untouched."""
    return "\n".join(line.rstrip(" \t") for line in text.split("\n"))


def detect_indent(text: str, current: tuple[str, int]) -> tuple[str, int]:
    """Best-effort guess of the indent style (and, for spaces, the width) actually used by
    ``text``'s own leading whitespace -- VSCode's own "Detect Indentation from Content" (PROMPT.md:
    replaces the old manual "Indent using spaces"/"Indent using tabs" commands).

    Whichever of tabs/spaces starts more lines wins the style, ties (including no tab-started lines
    at all) favor spaces. For spaces, the width is the GCD of
    every indented line's own leading-space count (e.g. levels of 2/4/6 spaces -> width 2) -- a tab
    character has no such per-line "how wide is one level" signal to read, so a tabs verdict leaves
    ``current``'s own width untouched rather than guessing one.

    Returns ``current`` unchanged if ``text`` has no indentation at all to read (a blank file, or
    one with no indented lines), so running this against one is a no-op rather than resetting to
    :data:`DEFAULT_INDENT_STYLE`/:data:`DEFAULT_INDENT_WIDTH`.
    """
    tab_count = 0
    space_indents: list[int] = []
    for line in text.split("\n"):
        if line.startswith("\t"):
            tab_count += 1
        elif line.startswith(" "):
            space_indents.append(len(line) - len(line.lstrip(" ")))

    if tab_count == 0 and not space_indents:
        return current
    if tab_count > len(space_indents):
        return STYLE_TABS, current[1]

    width = space_indents[0]
    for indent in space_indents[1:]:
        width = math.gcd(width, indent)
    return STYLE_SPACES, _clamp_width(width)
