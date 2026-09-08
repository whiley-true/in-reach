"""String table export (plus, now, JSON -> dict load-back for the compile pipeline).

Ported from ``in-reach-v1``'s ``strings_io.py``, originally trimmed to the dump direction only --
:func:`load_strings` is now ported too, from ``in-reach-v2``'s own version of this module, since
PROMPT.md's "applying changes should try and compile the jsons into a gametype" means
``settings/strings.json`` really is hand-edited (or RVT-edited) input again, for
:mod:`in_reach.app.rvt.compile`'s ``run_compile()`` to read back and apply via
:mod:`in_reach.app.rvt.strings_writer`'s ``apply_strings()``. The JSON-Schema (``"$schema"``)
embedding v1 also trimmed *is* back too, ported from the v2 prototype instead -- see
:mod:`in_reach.app.rvt.schema_io`.

Dumps every ReachStringTable ``_reachvarianttool`` exposes on a multiplayer variant -- localized
name/description/category, each team's name, and the big generic script_strings table (Forge Label
names, Scripted Option/Trait names and descriptions, and any other script-referenced text -- up to
112 entries) -- across every language the engine stores (not just English).

Per-language values are ``None`` when that language was never saved for a given string, and only
``""`` when a language was saved with deliberately empty content (see ``ReachString.has_content()``
in ``bindings.cpp`` -- ``get_content()`` alone can't tell these two cases apart, since an unsaved
language also reads back as an empty string).
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from in_reach.app.rvt.models.strings import StringsDocument
from in_reach.app.rvt.rvt_bridge import get_rvt
from in_reach.app.rvt.schema_io import schema_ref

LANGUAGES = [
    "english",
    "japanese",
    "german",
    "french",
    "spanish",
    "mexican",
    "italian",
    "korean",
    "chinese_traditional",
    "chinese_simplified",
    "portugese",
    "polish",
]


def _all_languages(rvt, string) -> dict:
    result = {}
    for lang in LANGUAGES:
        language = getattr(rvt.Language, lang)
        result[lang] = string.get_content(language) if string.has_content(language) else None
    return result


def _extract_string_table(rvt, table) -> list[dict]:
    return [{"index": i, "text": _all_languages(rvt, table[i])} for i in range(len(table))]


def extract_strings(mp) -> dict:
    """``mp`` is a ``MultiplayerData`` (``variant.multiplayer``); returns empty tables if ``mp`` is
    ``None`` (nothing to extract for non-multiplayer variants)."""
    if mp is None:
        return {
            "meta": {"name": [], "description": [], "category": []},
            "teams": [],
            "script_strings": [],
        }
    rvt = get_rvt()
    options = mp.options
    teams = []
    for i in range(options.team.team_count):
        name = options.team.team(i).get_name()
        teams.append({"index": i, "name": _all_languages(rvt, name) if name is not None else None})
    return {
        "meta": {
            "name": _extract_string_table(rvt, mp.localized_name),
            "description": _extract_string_table(rvt, mp.localized_desc),
            "category": _extract_string_table(rvt, mp.localized_category),
        },
        "teams": teams,
        "script_strings": _extract_string_table(rvt, mp.script_strings),
    }


def write_strings_json(
    strings: dict, out_path: Path, schema_path: Path | None = None, comment: str | None = None
) -> Path:
    """``schema_path``, if given, is embedded as a relative ``"$schema"`` key (PROMPT.md: "in
    settings, please not[e] examples from repo v2 ... re-add this to the top of the files") -- see
    :func:`~in_reach.app.rvt.schema_io.schema_ref`."""
    document = dict(strings)
    if comment is not None:
        document = {"_comment": comment, **document}
    if schema_path is not None:
        document = {"$schema": schema_ref(schema_path, out_path), **document}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(document, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return out_path


def load_strings(path: Path) -> dict:
    """Reads+validates ``path`` (a ``strings.json``), returning the same plain dict shape
    :func:`extract_strings` produces (``_comment``/``$schema`` stripped) for
    :func:`~in_reach.app.rvt.strings_writer.apply_strings` to consume unchanged. Validation is
    against :class:`~in_reach.app.rvt.models.strings.StringsDocument` purely to catch a malformed
    hand-edit early with a clear message; the dict handed back is the original, not a
    ``model_dump()`` reshaping of it, so ``apply_strings()``'s existing plain-dict contract is
    untouched.

    Raises:
        ValueError: ``path`` isn't valid JSON, or doesn't match ``StringsDocument``'s schema.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc
    data.pop("_comment", None)
    data.pop("$schema", None)
    try:
        StringsDocument.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"{path} does not match the strings schema: {exc}") from exc
    return data
