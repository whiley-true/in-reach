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

from dataclasses import dataclass, field
from difflib import SequenceMatcher

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
    Returns an over-budget-table warning, same convention as apply_strings().

    A blank description never creates an entry: a variant with no description strings at all (a
    personal variant saved without one) decompiles to an empty ``meta.description`` in
    ``strings.json``, and giving it an entry of blank text here would make every build's snapshot
    differ from ``settings/`` -- Apply would read "unapplied" however often it was clicked."""
    if not description_string and len(mp.localized_desc) == 0:
        return None
    return _apply_string_table(rvt, mp.localized_desc, [{"index": 0, "text": {"english": description_string}}], "metadata.description_string", grow=True)


@dataclass
class StringReconciliation:
    """What :func:`reconcile_script_strings` did: ``strings`` is the (possibly extended or trimmed)
    document to apply, ``added``/``removed`` the table indexes that changed."""

    strings: dict
    added: list[int] = field(default_factory=list)
    removed: list[int] = field(default_factory=list)
    updated: list[int] = field(default_factory=list)  # entries whose text :func:`own_text` replaced

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed or self.updated)


def _is_untranslated(entry: dict) -> bool:
    """An entry with nothing in any language that differs from its English text -- what a string the
    script itself just created looks like, so nothing a user typed would be lost by dropping it.
    (A forge label's name is copied into every language as-is; a format string's other languages are
    empty or unset. Neither is a translation.)"""
    if isinstance(entry["text"], str):  # the bare-string shorthand: English only
        return True
    english = entry["text"].get("english")
    return all(not text or text == english for language, text in entry["text"].items() if language != "english")


def _english(entry: dict) -> str | None:
    """An entry's English text, whether it is written out per language or as the bare-string shorthand."""
    text = entry["text"]
    return text if isinstance(text, str) else text.get("english")


def _every_language(text: str) -> dict:
    """``text`` in every language -- what a string edited in (or added by) the script gets: the script only has one
    text, so no language is left showing an older one."""
    from .strings_io import LANGUAGES

    return {language: text for language in LANGUAGES}


def _filled(texts: dict) -> dict:
    """``texts`` with every empty language given the English text."""
    english = texts.get("english")
    return {language: (value or english) for language, value in texts.items()}


def _literals(script: str) -> list[str]:
    """The string literals ``script`` passes to calls, in order -- not forge-label names (``with label "x"``,
    ``has_forge_label("x")``' own argument is a name too, but a label is renamed in settings, not here)."""
    from .megalo_ast.lexer import MegaloLexError, tokenize

    try:
        tokens = tokenize(script)
    except MegaloLexError:
        return []
    literals = []
    for position, token in enumerate(tokens):
        if token.kind != "string":
            continue
        before = tokens[position - 1] if position else None
        if before is not None and before.kind == "ident" and before.text == "label":
            continue
        literals.append(token.value)
    return literals


def edited_literals(old_script: str, new_script: str) -> list[tuple[str, str]]:
    """``(old text, new text)`` for each string literal ``new_script`` changed in place: one replaced by another at the
    same place in the sequence of literals, whose old text the new script no longer uses anywhere."""
    old, new = _literals(old_script), _literals(new_script)
    pairs = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes():
        if tag == "replace" and i2 - i1 == j2 - j1:
            pairs += zip(old[i1:i2], new[j1:j2])
    still_used = set(new)
    return [(before, after) for before, after in pairs if before != after and before not in still_used]


def rename_edited_strings(mp, old_script: str, new_script: str) -> list[tuple[str, str]]:
    """Renames, in ``mp``'s string table, each string the script edited in place (:func:`edited_literals`; the old script
    is the base variant's own), setting every language to the new text -- so the compile reuses that entry, index and
    all, rather than adding the new text as another one and leaving the old behind (a build always starts from the
    same base, whose table still holds the old text). A string whose new text is already in the table is left alone:
    the compile uses that one. Returns the renames made."""
    from .strings_io import LANGUAGES

    rvt = get_rvt()
    table = mp.script_strings
    english = rvt.Language.english
    by_text = {}
    for i in range(len(table)):
        if table[i].has_content(english):
            by_text.setdefault(table[i].get_content(english), i)
    renamed = []
    for before, after in edited_literals(old_script, new_script):
        if after in by_text or before not in by_text:
            continue
        index = by_text.pop(before)
        for language in LANGUAGES:
            table[index].set_content(getattr(rvt.Language, language), after)
        by_text[after] = index
        renamed.append((before, after))
    return renamed


def reconcile_script_strings(mp, strings: dict, previous: dict | None = None) -> StringReconciliation:
    """Makes ``strings["script_strings"]`` cover exactly the compiled variant's own script-string table.

    Like forge labels (see :func:`~in_reach.app.rvt.settings_writer.reconcile_forge_labels`), the
    *script* decides which strings exist -- every format string, and every forge label's name, is
    an entry the compile creates -- while ``settings/strings.json`` only holds what a user has written
    into them, by index. Without this, any script that adds a string left ``strings.json`` shorter than
    the build's own snapshot forever, so Apply read "unapplied" no matter how often it was clicked.

    Entries for indexes the compile created are added (with the text it gave them); trailing entries
    past the end of the table are dropped, but only if untranslated -- one carrying text in another
    language is the user's own work and is left for :func:`apply_strings` to report, as it always has.

    Args:
        mp: The just-compiled variant's ``MultiplayerData``.
        strings: A validated ``strings.json`` document (see :func:`~in_reach.app.rvt.strings_io.load_strings`).
        previous: The last build's ``build/strings.autogenerated.json`` -- what tells a string edited in the script (its
            entry still says what that build did: it follows the compile) from one edited in ``strings.json`` (kept).

    Returns:
        A :class:`StringReconciliation`; ``strings`` on it is the input itself if nothing changed.
    """
    from .strings_io import _all_languages

    rvt = get_rvt()
    table = mp.script_strings
    entries = list(strings["script_strings"])
    removed: list[int] = []
    while entries and entries[-1]["index"] >= len(table) and _is_untranslated(entries[-1]):
        removed.append(entries.pop()["index"])
    present = {entry["index"] for entry in entries}
    added = [i for i in range(len(table)) if i not in present]
    for i in added:  # a string the script added: its one text in every language
        entries.append({"index": i, "text": _filled(_all_languages(rvt, table[i]))})
    # A literal edited in the script is what the compile put in the table, and strings.json follows it -- otherwise the
    # old text, applied after the compile, would put the old string back in the game. Only when strings.json still says
    # what the last build did, though (``previous``): an entry someone changed in strings.json itself is theirs, and is
    # applied over the compile as always. Every language follows: the script has one text, and a translation of the old
    # one would be wrong for the new.
    last_built = {e["index"]: _english(e) for e in (previous or {}).get("script_strings", [])}
    updated: list[int] = []
    for position, entry in enumerate(entries):
        index = entry["index"]
        if index in added or index >= len(table) or index not in last_built:
            continue
        compiled = table[index].text
        english = _english(entry)
        if english == compiled or english != last_built[index]:
            continue
        entries[position] = {**entry, "text": _every_language(compiled)}
        updated.append(index)
    if not (added or removed or updated):
        return StringReconciliation(strings)
    entries.sort(key=lambda entry: entry["index"])
    return StringReconciliation({**strings, "script_strings": entries}, added, removed, updated)


def own_text(reconciled: StringReconciliation, owned: dict[int, str]) -> StringReconciliation:
    """``reconciled`` with the English text of each script string in ``owned`` (index -> text; see
    :mod:`~in_reach.app.rvt.resource_text`) set to that text, so what :func:`apply_strings` writes -- and what gets saved
    to ``settings/strings.json`` -- is what the code says. Other languages of an entry are left as they are."""
    entries = [dict(entry) for entry in reconciled.strings["script_strings"]]
    updated = []
    for entry in entries:
        text = owned.get(entry["index"])
        if text is not None and entry["text"].get("english") != text:
            entry["text"] = {**entry["text"], "english": text}
            updated.append(entry["index"])
    if not updated:
        return reconciled
    return StringReconciliation(
        {**reconciled.strings, "script_strings": entries}, reconciled.added, reconciled.removed,
        sorted(set(reconciled.updated) | set(updated)),
    )


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
