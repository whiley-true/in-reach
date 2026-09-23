"""``strings_writer.apply_description_string``: a blank description never creates a string-table entry.

A personal variant saved without a description has an empty ``localized_desc`` table, so its decompiled
``strings.json`` has ``meta.description == []``. Writing the project's blank description into it as an entry of empty
text made every build's snapshot differ from ``settings/``: Apply stayed lit after the project was created, and after
the first click too."""
from types import SimpleNamespace

from in_reach.app.rvt import strings_writer


class _Table(list):
    """Stands in for a native string table: only its length matters here."""


def test_a_blank_description_leaves_an_empty_table_empty(monkeypatch) -> None:
    written = []
    monkeypatch.setattr(strings_writer, "_apply_string_table", lambda *args, **kwargs: written.append(args))
    mp = SimpleNamespace(localized_desc=_Table())

    assert strings_writer.apply_description_string(None, mp, "") is None
    assert written == []


def test_a_real_description_is_still_written_into_an_empty_table(monkeypatch) -> None:
    written = []
    monkeypatch.setattr(strings_writer, "_apply_string_table", lambda *args, **kwargs: written.append(args[2]))
    mp = SimpleNamespace(localized_desc=_Table())

    strings_writer.apply_description_string(None, mp, "Race to five")

    assert written == [[{"index": 0, "text": {"english": "Race to five"}}]]


def test_a_blank_description_still_overwrites_an_existing_entry(monkeypatch) -> None:
    """Clearing a description the variant has is a real edit, and still reaches the table."""
    written = []
    monkeypatch.setattr(strings_writer, "_apply_string_table", lambda *args, **kwargs: written.append(args[2]))
    mp = SimpleNamespace(localized_desc=_Table(["old text"]))

    strings_writer.apply_description_string(None, mp, "")

    assert written == [[{"index": 0, "text": {"english": ""}}]]
