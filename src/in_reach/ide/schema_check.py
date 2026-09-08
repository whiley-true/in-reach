"""Blocks saving a ``settings/*.json`` file whose new content wouldn't actually validate against
its own schema (PROMPT.md: "implement schema checking in our text editor - where if a file has a
schema, and a user tries to save the file with an incorrect value, then the save should fail").

Validates straight against the same Pydantic model :func:`~in_reach.app.rvt.schema_io.dump_json_schema`
generated the on-disk ``"$schema"``-referenced schema *from* in the first place, rather than
parsing that schema file back into a generic JSON-Schema validator (``$ref``/``$defs`` resolution,
``oneOf``/``allOf``, ...). Exactly equivalent for a schema this app owns end-to-end on both sides,
and avoids a new third-party JSON-Schema-validation dependency for a schema space nothing outside
this app ever actually needs to validate against.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from in_reach.app.rvt.models.game_settings import GameSettings
from in_reach.app.rvt.models.script_settings import ScriptSettings
from in_reach.app.rvt.models.strings import StringsDocument
from in_reach.ide.json_position import find_value_span

#: Filenames unique to settings/ across this app's whole project layout -- matching by basename
#: alone is safe, nothing else in a project ever shares one of these exact names.
_MODELS_BY_FILENAME = {
    "settings.json": GameSettings,
    "script_settings.json": ScriptSettings,
    "strings.json": StringsDocument,
}


@dataclass
class SchemaError:
    """One validation problem, plus (when it names an actual value in the text, rather than e.g.
    a required field that's simply absent) the character span in the original ``text`` that value
    came from -- what :mod:`in_reach.ide.editor`'s live-as-you-type check underlines."""

    loc: tuple
    message: str
    span: tuple[int, int] | None


def find_errors(path: Path, text: str) -> list[SchemaError] | None:
    """Every schema problem in ``text`` (as if about to be saved to ``path``), with enough detail
    for both save-blocking (:func:`validate_before_save`) and live inline highlighting (PROMPT.md:
    "we want it like in vscode, so highlighting and error message if schema is incorrect").

    Args:
        path: Where the file is (or would be) saved.
        text: The content to check.

    Returns:
        ``None`` if ``path``'s name isn't one of this app's own schema-backed files. Otherwise a
        list of every problem found -- empty if ``text`` parses and validates cleanly.
    """
    model_cls = _MODELS_BY_FILENAME.get(path.name)
    if model_cls is None:
        return None

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        span = (exc.pos, exc.pos + 1) if exc.pos < len(text) else None
        return [SchemaError(loc=(), message=f"{path.name} is not valid JSON: {exc}", span=span)]
    if not isinstance(data, dict):
        return [SchemaError(loc=(), message=f"{path.name} must be a JSON object.", span=(0, len(text)))]

    stripped = {k: v for k, v in data.items() if k not in ("$schema", "_comment")}
    try:
        model_cls.model_validate(stripped)
    except ValidationError as exc:
        errors = []
        for error in exc.errors():
            loc = tuple(error["loc"])
            errors.append(SchemaError(loc=loc, message=error["msg"], span=find_value_span(text, loc)))
        return errors
    return []


def validate_before_save(path: Path, text: str) -> str | None:
    """Whether ``text`` -- about to be saved to ``path`` -- would still validate against
    ``path``'s own schema, if it has one.

    Args:
        path: Where the file is about to be saved.
        text: The new content about to be written.

    Returns:
        ``None`` if ``path``'s name isn't one of this app's own schema-backed files, or ``text``
        parses and validates cleanly. Otherwise a user-facing message describing what's wrong,
        for the caller to show and refuse the save over.
    """
    errors = find_errors(path, text)
    if not errors:
        return None
    if not errors[0].loc:
        # A JSON-syntax or not-an-object error -- already a complete, standalone message.
        return errors[0].message
    details = "\n".join(f"{'.'.join(str(part) for part in e.loc)}\n  {e.message}" for e in errors)
    return f"{path.name} does not match its own schema:\n{details}"
