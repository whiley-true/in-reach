"""Pydantic model -> JSON, extraction-only (plus one narrow load-back path).

Ported from ``in-reach-v1``'s ``settings_io.py``, trimmed to the dump direction only: there is no
more hand-edited JSON to load back (editing happens through ReachVariantTool itself, not by hand),
so ``load_game_settings`` and the JSON-Schema (``$schema``) embedding aren't ported.

:func:`load_script_settings` is the one exception -- not for hand-editing, but so a read-only UI
can read back a project's already-extracted ``edit/settings/script_settings.json`` (see
:mod:`in_reach.app.rvt.decompile`) to know each Scripted Option's current shape (values/range)
without re-deriving that from a loaded ``.bin``.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from in_reach.app.rvt.models.game_settings import GameSettings
from in_reach.app.rvt.models.script_settings import ScriptSettings


def _dump_json(data: dict, out_path: Path, comment: str | None) -> Path:
    if comment is not None:
        data = {"_comment": comment, **data}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=False)
        f.write("\n")
    return out_path


def dump_game_settings(settings: GameSettings, out_path: Path, comment: str | None = None) -> Path:
    """Writes ``game_settings.json`` only -- ``multiplayer.script_settings`` is stripped out of the
    dump (see :func:`dump_script_settings` for that file). ``comment``, if given, is embedded as a
    ``"_comment"`` key."""
    data = settings.model_dump(mode="json")
    if data.get("multiplayer"):
        data["multiplayer"].pop("script_settings", None)
    return _dump_json(data, out_path, comment)


def dump_script_settings(script_settings: ScriptSettings, out_path: Path, comment: str | None = None) -> Path:
    return _dump_json(script_settings.model_dump(mode="json"), out_path, comment)


def load_script_settings(path: Path) -> ScriptSettings:
    """Reads `path` (normally ``cfg/script_settings.json``) back into a :class:`ScriptSettings`.

    Returns a bare default ``ScriptSettings()`` if `path` doesn't exist or fails to parse/validate
    -- this only ever backs a read-only UI, so there's nothing to raise to; an empty options list
    just means that UI shows no Scripted Options yet.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ScriptSettings()
    data.pop("_comment", None)
    try:
        return ScriptSettings.model_validate(data)
    except ValidationError:
        return ScriptSettings()
