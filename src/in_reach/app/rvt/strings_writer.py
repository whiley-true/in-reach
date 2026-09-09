"""strings.json -> _reachvarianttool string-table writer -- the reverse of
:mod:`in_reach.app.rvt.strings_io`'s ``extract_strings()``, used by the "apply strings" step of
:mod:`in_reach.app.rvt.compile`'s compile pipeline.

Ported near-verbatim from ``in-reach-v2``'s own ``rvt/strings_writer.py`` (itself ported from
``refactor/mide/strings_writer.py``). Works directly on plain dicts -- the same shape
``extract_strings()``/``write_strings_json()`` already produce: ``{"meta": {"name": [...],
"description": [...], "category": [...]}, "teams": [...], "script_strings": [...]}``, each list
entry a plain ``{"index": int, "text": {lang: str | None, ...}}`` or, for ``teams``, ``{"index":
int, "name": {...} | None}``. Everything below reads those same shapes by key instead of by
attribute, rather than switching to the ``StringsDocument`` pydantic model (:mod:`in_reach.app.rvt.
models.strings`) for the write direction too -- that model only ever validates an on-disk
``strings.json`` before it gets here (see :func:`in_reach.app.rvt.strings_io.load_strings`), it
isn't what this module actually receives.

Covers every ReachStringTable extract_strings() reads: meta name/description/category, team
names, and script_strings. meta name/description/category and team names grow their table on
demand (via ReachStringTable.add_new()) when applying an entry whose index doesn't exist yet --
these tables start out with zero entries on a freshly-loaded blank, so without this a blank could
never have them set at all. script_strings entries are NOT grown this way: their entry count is
tied to script_settings (fixed once the Megalo script is compiled, see
:mod:`in_reach.app.rvt.settings_writer`'s docstring), so posting an out-of-range script_strings
index is still a hard error.

After writing, each touched table's serialized size is checked against its own max_buffer_size
(ReachStringTable::max_buffer_size). This is deliberately a *warning*, not a hard failure --
RVT's own bundled blank_mp fixture already exceeds its localized_desc table's max_buffer_size out
of the box, and the engine handles this gracefully at save time by spilling the real string
content into a custom xRVT/mstr block -- it's only a genuine save failure if the *whole file*
still can't fit even after that fallback, which variant.save() already raises for on its own.
apply_strings() returns the list of over-budget table names so the caller can surface them as
non-fatal notices.

A `None` per-language value means "leave this language untouched", not "clear it" -- there's no
unset operation bound, only set_content(); see strings_io.py's docstring for the has_content() vs
get_content() distinction this mirrors.
"""
from __future__ import annotations

from .rvt_bridge import get_rvt


def _coerce_localized_text(text: dict | str) -> dict:
    """A bare string is shorthand for ``{"english": text}`` (see ``models/strings.py``'s own
    ``LocalizedText``/``_coerce_localized_text`` docstring for why -- "most edits only care about
    English and shouldn't need to learn the full per-language shape just to set one string").
    :func:`~in_reach.app.rvt.strings_io.load_strings` validates that shorthand through the
    ``StringsDocument`` model but deliberately hands back the *original* (uncoerced) dict, not the
    model's own reshaping of it (see that function's own docstring) -- so a bare string can still
    reach here unchanged, and needs the same coercion applied at the point of use instead."""
    if isinstance(text, str):
        return {"english": text}
    return text


def _apply_language_text(rvt, string_obj, text: dict | str) -> None:
    for lang_name, value in _coerce_localized_text(text).items():
        if value is None:
            continue
        language = getattr(rvt.Language, lang_name)
        string_obj.set_content(language, value)


def _apply_string_table(rvt, table, entries: list[dict], table_name: str, grow: bool = False) -> str | None:
    """Returns a warning message if the table is over budget after applying, else None.

    `grow`: if an entry's index doesn't exist yet, create entries up to it via table.add_new()
    instead of raising (see module docstring) -- capped at the table's own `capacity` so a bogus
    huge index still raises a clear error instead of hammering add_new() pointlessly."""
    for entry in entries:
        index = entry["index"]
        if index >= len(table):
            if not grow:
                raise ValueError(f"{table_name}[{index}] is out of range (table has {len(table)} entries)")
            if index >= table.capacity:
                raise ValueError(f"{table_name}[{index}] is out of range (table capacity is {table.capacity})")
            while index >= len(table):
                table.add_new()
        _apply_language_text(rvt, table[index], entry["text"])
    size = table.get_size_to_save()
    if size > table.max_buffer_size:
        return f"{table_name} exceeds its max buffer size ({size} > {table.max_buffer_size} bytes) -- will be saved via the engine's overflow fallback"
    return None


def _apply_team_names(rvt, team_options, teams: list[dict]) -> None:
    for entry in teams:
        name = entry.get("name")
        if name is None:
            continue
        name = _coerce_localized_text(name)
        index = entry["index"]
        if index >= team_options.team_count:
            raise ValueError(f"teams[{index}] is out of range (there are {team_options.team_count} teams)")
        team = team_options.team(index)
        name_obj = team.get_name()
        if name_obj is None:
            # The team name table starts out empty -- the "name" convenience setter (bindings.cpp)
            # creates its one entry on first write, but only sets English. Every other language in
            # `name` still gets applied below via set_content directly.
            team.name = name.get("english") or ""
            name_obj = team.get_name()
        _apply_language_text(rvt, name_obj, name)


def apply_description_string(rvt, mp, description_string: str) -> str | None:
    """English-only convenience write of multiplayer.game_settings.metadata.description_string
    into localized_desc (the same mechanism, and the same on-demand table growth, as
    apply_strings()'s meta.description handling below -- see this module's docstring). Called from
    settings_writer.apply_multiplayer_settings() so editing this field via settings/settings.json
    actually takes effect on compile.

    Confirmed against a real built-in variant that localized_desc -- not variant_header.description
    (GameSettings.meta.description) -- holds a gametype's real, human-readable description.
    Multi-language content still has to go through settings/strings.json -- this only ever writes
    English, matching ReachString.text/TeamData.name's own "convenience accessor" precedent.
    Returns an over-budget-table warning, same convention as apply_strings()."""
    return _apply_string_table(rvt, mp.localized_desc, [{"index": 0, "text": {"english": description_string}}], "metadata.description_string", grow=True)


def apply_strings(mp, strings: dict) -> list[str]:
    """Apply `strings` (the same dict shape strings_io.extract_strings() produces) onto `mp` (a
    loaded variant's .multiplayer) and return any over-budget-table warnings (see module
    docstring). Does not save -- the caller (in_reach.app.rvt.compile.run_compile()) does that
    once all requested applies have run."""
    rvt = get_rvt()
    meta = strings["meta"]
    warnings = [
        _apply_string_table(rvt, mp.localized_name, meta["name"], "meta.name", grow=True),
        _apply_string_table(rvt, mp.localized_desc, meta["description"], "meta.description", grow=True),
        _apply_string_table(rvt, mp.localized_category, meta["category"], "meta.category", grow=True),
        _apply_string_table(rvt, mp.script_strings, strings["script_strings"], "script_strings"),
    ]
    _apply_team_names(rvt, mp.options.team, strings["teams"])
    return [w for w in warnings if w is not None]
