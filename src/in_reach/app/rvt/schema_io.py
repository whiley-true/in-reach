"""Generates VS Code-consumable JSON Schema files from this package's own Pydantic models, so
``settings/*.json`` get live validation/autocomplete/hover docs in VS Code's built-in JSON language
service without a second, hand-maintained schema -- the models under ``models/`` are already each
JSON file's real source of truth (see ``models/game_settings.py``'s docstring), so the schema is
just their ``model_json_schema()`` output, regenerated fresh whenever a project is (re)decompiled
(:mod:`in_reach.app.rvt.decompile`) rather than checked in anywhere.

Ported near-verbatim from the v2 prototype's own ``rvt/schema_io.py`` (PROMPT.md: "in settings,
please not[e] examples from repo v2 ... where we have a schema, please re-add this to the top of
the files").
"""

import json
import os
from pathlib import Path

from pydantic import BaseModel


def dump_json_schema(model_cls: type[BaseModel], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(model_cls.model_json_schema(), f, indent=2, ensure_ascii=False, sort_keys=False)
        f.write("\n")
    return out_path


def schema_ref(schema_path: Path, json_path: Path) -> str:
    """The ``"$schema"`` value ``json_path`` should embed to point at ``schema_path``. VS Code
    resolves a JSON file's own ``"$schema"`` key relative to that file's own location, so this is
    always a relative (never absolute) path -- computed rather than hardcoded so it stays correct
    if the directory depth between the two ever changes."""
    return Path(os.path.relpath(schema_path, start=json_path.parent)).as_posix()
