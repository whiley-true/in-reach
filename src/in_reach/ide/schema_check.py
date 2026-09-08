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
from pathlib import Path

from pydantic import ValidationError

from in_reach.app.rvt.models.game_settings import GameSettings
from in_reach.app.rvt.models.script_settings import ScriptSettings
from in_reach.app.rvt.models.strings import StringsDocument

#: Filenames unique to settings/ across this app's whole project layout -- matching by basename
#: alone is safe, nothing else in a project ever shares one of these exact names.
_MODELS_BY_FILENAME = {
    "settings.json": GameSettings,
    "script_settings.json": ScriptSettings,
    "strings.json": StringsDocument,
}


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
    model_cls = _MODELS_BY_FILENAME.get(path.name)
    if model_cls is None:
        return None

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return f"{path.name} is not valid JSON: {exc}"
    if not isinstance(data, dict):
        return f"{path.name} must be a JSON object."

    data.pop("$schema", None)
    data.pop("_comment", None)
    try:
        model_cls.model_validate(data)
    except ValidationError as exc:
        return f"{path.name} does not match its own schema:\n{exc}"
    return None
