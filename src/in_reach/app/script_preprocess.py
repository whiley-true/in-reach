"""Environment profiles for a project's Megalo script: ``${NAME}`` constants and ``-- @if`` blocks.

A project's script is one file (``script/output.txt``), and it can stay one large file -- what this
adds is a way to build *variants* of it without copying it: the same source compiled for ``dev``
(a shorter round, a debug message) and for ``release``. A **profile** is ``script/env/<name>.env``::

    # dev.env
    FLAGS=DEV,VERBOSE_HUD
    SCORE_TO_WIN=5
    HILL_LABEL="hill"

and one of them is *active* (``script/env/active_profile.txt`` holds its name). Before the script is
compiled, and before ``build/Compiled.txt`` is written, :func:`preprocess` applies it:

- ``${SCORE_TO_WIN}`` becomes ``5``. Only a number (signed 16-bit, as Megalo's are), a percentage, a
  name, or a quoted string may be a value -- see :func:`check_value` -- so a value can't smuggle arbitrary
  code in; a quoted string can't go *inside* a string literal, only stand in for one. Comments are left
  alone, and a constant nobody defined is an error rather than a silent literal ``${...}``.
- ``-- @if DEV`` ... ``-- @end`` keeps the block only when ``DEV`` is one of the profile's flags
  (``-- @if !DEV`` when it isn't; ``-- @else`` flips it; they nest). Each directive must be alone on its
  line. They're ordinary ``--`` comments as far as Megalo is concerned, so a file that uses them still
  compiles unprocessed -- with every block kept.

Two properties this is careful about, because the compiler's own messages are the only feedback a script
author gets:

- **Line numbers never shift.** A line that's removed becomes an empty one, and a substitution never
  adds a newline, so "error at line 40" still points at line 40 of the file the user edits.
- **No profile and no directives means unchanged.** ``preprocess(text)`` returns ``text`` exactly, so
  every project written before this existed compiles the same as it always did.

A block removed by ``@if`` is never scanned for ``${...}``, so a dev-only block can refer to a constant
only the dev profile defines.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from in_reach.app import new_project

ENV_DIRNAME = new_project.ENV_DIRNAME
ENV_SUFFIX = new_project.ENV_SUFFIX
ACTIVE_PROFILE_FILENAME = new_project.ACTIVE_PROFILE_FILENAME
FLAGS_KEY = "FLAGS"

#: Megalo numbers are signed 16-bit (the same range the linker design's IR015 lint names).
MIN_NUMBER = -32768
MAX_NUMBER = 32767

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_INT = re.compile(r"-?\d+")
_PERCENT = re.compile(r"-?\d+%")
_QUOTED = re.compile(r'"(?:[^"\\\n]|\\.)*"')
_DIRECTIVE = re.compile(r"^\s*--\s*@(if|else|end)(?=\s|$)(.*)$")
_PLACEHOLDER = re.compile(r"\$\{([^}]*)\}")
# An `-- @name ...` annotation line (see megalo_ast.annotations), up to where its arguments start. @doc is prose.
_ANNOTATION = re.compile(r"^(\s*--\s*@(?!doc\b)[A-Za-z][A-Za-z0-9_-]*)(.*)$")


class PreprocessError(ValueError):
    """Something in the script or the active profile that stops it being preprocessed.

    ``line`` (1-based) and ``col`` (0-based, an index into the line) locate it in the file named by
    ``path`` -- ``None`` meaning the script itself, otherwise an env file. (``compile.py`` turns ``col``
    into the 1-based column a :class:`~in_reach.app.rvt.compile.BuildMessage` carries.)"""

    def __init__(self, message: str, line: int = 0, col: int = 0, path: Path | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.line = line
        self.col = col
        self.path = path


@dataclass(frozen=True)
class Profile:
    """One environment: its name, its ``FLAGS``, and its ``NAME=value`` constants (raw text)."""

    name: str
    flags: frozenset[str] = frozenset()
    constants: dict[str, str] = field(default_factory=dict)


# -- values -----------------------------------------------------------------------------------------


def value_kind(value: str) -> str | None:
    """``"int"``, ``"percent"``, ``"name"`` or ``"string"``; ``None`` for anything else -- including
    a number outside signed 16-bit."""
    if _INT.fullmatch(value):
        return "int" if MIN_NUMBER <= int(value) <= MAX_NUMBER else None
    if _PERCENT.fullmatch(value):
        return "percent"
    if _NAME.fullmatch(value):
        return "name"
    if _QUOTED.fullmatch(value):
        return "string"
    return None


def check_value(name: str, value: str) -> str:
    """Returns ``value``'s kind, or raises :class:`PreprocessError` saying why it can't be a constant."""
    kind = value_kind(value)
    if kind is not None:
        return kind
    if _INT.fullmatch(value):
        raise PreprocessError(f"{name}={value} is outside Megalo's number range ({MIN_NUMBER} to {MAX_NUMBER})")
    raise PreprocessError(
        f"{name}={value!r} isn't a number, a percentage (like -100%), a name, or a quoted string"
    )


# -- profiles -----------------------------------------------------------------------------------------


def parse_profile(name: str, text: str, path: Path | None = None) -> Profile:
    """Parses env-file ``text``. ``KEY=VALUE`` per line, ``#`` comments and blank lines ignored; values
    keep their quotes (a ``"hill"`` constant is a string, not the word hill).

    Raises:
        PreprocessError: A malformed line, a duplicate or invalid name, or a value that isn't allowed
            (see :func:`check_value`) -- located in ``path``.
    """
    flags: frozenset[str] = frozenset()
    constants: dict[str, str] = {}
    seen: set[str] = set()
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        def fail(message: str, _n=number) -> PreprocessError:
            return PreprocessError(message, _n, 0, path)

        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep:
            raise fail(f"expected NAME=VALUE, got {line!r}")
        if not _NAME.fullmatch(key):
            raise fail(f"{key!r} isn't a valid name (letters, digits and underscores, not starting with a digit)")
        if key in seen:
            raise fail(f"{key} is defined twice")
        seen.add(key)
        if key == FLAGS_KEY:
            parts = [part.strip() for part in value.split(",") if part.strip()]
            for part in parts:
                if not _NAME.fullmatch(part):
                    raise fail(f"{part!r} isn't a valid flag name")
            flags = frozenset(parts)
            continue
        if not value:
            raise fail(f"{key} has no value")
        try:
            check_value(key, value)
        except PreprocessError as exc:
            raise fail(exc.message) from None
        constants[key] = value
    return Profile(name, flags, constants)


def env_dir(folder: Path) -> Path:
    """``<project>/script/env`` -- where profiles live (need not exist)."""
    return folder / new_project.SCRIPT_DIRNAME / ENV_DIRNAME


def list_profiles(folder: Path) -> list[str]:
    """The names of ``folder``'s profiles (``dev`` for ``script/env/dev.env``), sorted."""
    directory = env_dir(folder)
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob(f"*{ENV_SUFFIX}") if p.is_file())


def active_profile_name(folder: Path) -> str | None:
    """The profile ``folder`` is set to build with, or ``None`` if none is chosen."""
    try:
        name = (env_dir(folder) / ACTIVE_PROFILE_FILENAME).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return name or None


def set_active_profile(folder: Path, name: str | None) -> None:
    """Chooses the profile to build with (``None`` clears the choice).

    Raises:
        ValueError: ``name`` isn't one of :func:`list_profiles`.
    """
    path = env_dir(folder) / ACTIVE_PROFILE_FILENAME
    if name is None:
        path.unlink(missing_ok=True)
        return
    if name not in list_profiles(folder):
        raise ValueError(f"{name!r} isn't a profile of this project (have: {', '.join(list_profiles(folder)) or 'none'})")
    path.write_text(name + "\n", encoding="utf-8")


def load_profile(folder: Path, name: str) -> Profile:
    """Reads ``script/env/<name>.env``.

    Raises:
        PreprocessError: The file is missing or invalid.
    """
    path = env_dir(folder) / f"{name}{ENV_SUFFIX}"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        raise PreprocessError(f"the active profile {name!r} has no file {path}", 0, 0, path) from None
    return parse_profile(name, text, path)


# -- preprocessing ------------------------------------------------------------------------------------


@dataclass
class _Block:
    line: int
    cond: bool  # whether the ``@if``'s own condition held
    parent_active: bool
    seen_else: bool = False

    @property
    def active(self) -> bool:
        return self.parent_active and (not self.cond if self.seen_else else self.cond)


def uses_directives(source: str) -> bool:
    """Whether ``source`` uses a ``-- @if`` / ``@else`` / ``@end`` directive or a ``${NAME}`` constant --
    that is, whether :func:`preprocess` could change it."""
    return any(_DIRECTIVE.match(line) or _PLACEHOLDER.search(line) for line in source.splitlines())


def has_comments(source: str) -> bool:
    """Whether ``source`` has a ``--`` comment that isn't one of the directives (those are
    :func:`uses_directives`'s). A ``--`` inside a quoted string isn't a comment."""
    return any("--" in _QUOTED.sub('""', line) for line in source.splitlines() if not _DIRECTIVE.match(line))


def preprocess(source: str, profile: Profile | None = None) -> str:
    """``source`` with ``profile``'s ``@if`` blocks resolved and its ``${NAME}`` constants substituted.

    Args:
        source: The script text.
        profile: The profile to apply, or ``None`` for none (no flags, no constants -- so a ``${X}``
            outside a removed block is an error, and every ``@if FLAG`` block is dropped, every
            ``@if !FLAG`` block kept).

    Returns:
        Text with the same number of lines, in the same places. Exactly ``source`` if it uses neither
        feature.

    Raises:
        PreprocessError: A malformed or unbalanced directive, or a ``${...}`` that isn't defined.
    """
    flags = profile.flags if profile else frozenset()
    stack: list[_Block] = []
    out: list[str] = []
    for number, raw in enumerate(source.splitlines(keepends=True), start=1):
        body = raw.rstrip("\r\n")
        eol = raw[len(body):]
        active = stack[-1].active if stack else True
        directive = _DIRECTIVE.match(body)
        if directive:
            keyword, argument = directive.group(1), directive.group(2).strip()
            # A directive line belongs to the region *around* its block, not to the branch it opens or
            # closes -- so an `@else`/`@end` stays visible whether or not the branch before it was kept.
            visible = active if keyword == "if" or not stack else stack[-1].parent_active
            _apply_directive(keyword, argument, number, flags, stack, active)
            out.append(raw if visible else eol)
            continue
        out.append(_substitute_line(body, number, profile) + eol if active else eol)
    if stack:
        raise PreprocessError("'-- @if' is never closed with '-- @end'", stack[-1].line)
    return "".join(out)


def _apply_directive(keyword: str, argument: str, number: int, flags: frozenset[str], stack: list[_Block], active: bool) -> None:
    if keyword == "if":
        negated = argument.startswith("!")
        name = argument[1:].strip() if negated else argument
        if not _NAME.fullmatch(name):
            raise PreprocessError("'-- @if' needs one flag name, like '-- @if DEV' or '-- @if !DEV'", number)
        stack.append(_Block(number, (name in flags) != negated, active))
        return
    if argument:
        raise PreprocessError(f"'-- @{keyword}' takes nothing after it", number)
    if not stack:
        raise PreprocessError(f"'-- @{keyword}' without a matching '-- @if'", number)
    if keyword == "end":
        stack.pop()
    else:
        if stack[-1].seen_else:
            raise PreprocessError("a second '-- @else' for the same '-- @if'", number)
        stack[-1].seen_else = True


def _substitute_line(line: str, number: int, profile: Profile | None) -> str:
    """:func:`_substitute` for one line, which also fills an annotation's arguments: ``-- @ptimer t
    default=${interval}`` is how a module's parameter reaches a declaration, so it has to be substituted even
    though it is a comment. Only the arguments -- not the ``-- @`` prefix, a ``-- note`` after them, or an
    ``@doc`` line's prose."""
    annotation = _ANNOTATION.match(line)
    if annotation is None:
        return _substitute(line, number, profile)
    prefix = annotation.group(1)
    # Blank the prefix instead of cutting it off, so a column in an error is still a column in the real line.
    return prefix + _substitute(" " * len(prefix) + annotation.group(2), number, profile)[len(prefix):]


def _substitute(line: str, number: int, profile: Profile | None) -> str:
    """Replaces ``${NAME}`` in one line of code -- never inside a ``--`` comment (but see
    :func:`_substitute_line`, for annotations)."""
    if "${" not in line:
        return line
    out: list[str] = []
    i = 0
    in_string = False
    while i < len(line):
        char = line[i]
        if in_string:
            if char == "\\" and i + 1 < len(line):
                out.append(line[i : i + 2])
                i += 2
                continue
            if char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif line.startswith("--", i):
            out.append(line[i:])
            break
        if line.startswith("${", i):
            match = _PLACEHOLDER.match(line, i)
            if match is None:
                raise PreprocessError("'${' with no closing '}'", number, i)
            out.append(_value_of(match.group(1).strip(), number, i, in_string, profile))
            i = match.end()
            continue
        out.append(char)
        i += 1
    return "".join(out)


def _value_of(name: str, number: int, col: int, in_string: bool, profile: Profile | None) -> str:
    if not _NAME.fullmatch(name):
        raise PreprocessError(f"'${{{name}}}' isn't a valid constant name", number, col)
    if profile is None:
        raise PreprocessError(f"'${{{name}}}' has no value: no environment profile is active", number, col)
    value = profile.constants.get(name)
    if value is None:
        raise PreprocessError(f"'${{{name}}}' isn't defined in the {profile.name!r} profile", number, col)
    if in_string and value_kind(value) in ("percent", "string"):
        raise PreprocessError(
            f"'${{{name}}}' is {value}, which can't go inside a string literal (only a number or a name can)",
            number,
            col,
        )
    return value


def preprocess_project(folder: Path, source: str) -> str:
    """:func:`preprocess` ``source`` with ``folder``'s active profile, if it has one.

    Raises:
        PreprocessError: The active profile's file is missing or invalid, or see :func:`preprocess`.
    """
    name = active_profile_name(folder)
    profile = load_profile(folder, name) if name else None
    return preprocess(source, profile)
