"""Editing a string literal in the script updates its existing script-string entry: the built game shows the new text,
``settings/strings.json`` follows it, and no new entry is made. (Before, the old text in ``strings.json`` was applied
over the compile, so the game kept showing the string as it was first built.)"""
import json
from pathlib import Path

import pytest

from in_reach import api
from in_reach.app import apply_settings, new_project, project
from in_reach.app.blank_variant import resolve_blank_variant
from in_reach.app.rvt import rvt_bridge, strings_writer

pytestmark = pytest.mark.skipif(not rvt_bridge.is_available(), reason="native _reachvarianttool extension not available")


def _message_script(text: str) -> str:
    return f'on init: do\n   game.show_message_to(all_players, none, "{text}")\nend\n'


def _strings(folder: Path) -> list[str]:
    entries = json.loads((folder / "settings" / "strings.json").read_text(encoding="utf-8"))["script_strings"]
    return [entry["text"]["english"] for entry in entries]


def _built_strings(folder: Path) -> list[str]:
    mp = rvt_bridge.get_rvt().load(str(new_project.compiled_variant_path(folder))).multiplayer
    return [mp.script_strings[i].text for i in range(len(mp.script_strings))]


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    project.create_project(tmp_path)
    return api.new_gametype_project(tmp_path, "Strings", source_variant=resolve_blank_variant(firefight=False))


def test_an_edited_string_updates_its_entry_in_place(folder: Path) -> None:
    script = folder / "script" / "output.mgl"
    script.write_text(_message_script("Hello there"), encoding="utf-8")
    assert api.build(folder).success
    first = _strings(folder)

    script.write_text(_message_script("Goodbye"), encoding="utf-8")
    outcome = api.build(folder)

    assert outcome.success
    assert len(_strings(folder)) == len(first)  # no new entry
    assert "Goodbye" in _strings(folder) and "Hello there" not in _strings(folder)
    assert "Goodbye" in _built_strings(folder) and "Hello there" not in _built_strings(folder)  # what the game shows
    assert any("Updated 1 script string" in d.message for d in outcome.diagnostics if d.severity == "notice")
    assert not apply_settings.settings_have_unapplied_changes(folder)  # settles in one build


def test_every_language_of_a_string_edited_in_the_script_takes_the_new_text() -> None:
    from in_reach.app.rvt.strings_io import LANGUAGES

    class _String:
        def __init__(self, text: str) -> None:
            self.text = text

    entry = {"index": 0, "text": {"english": "Old", "french": "Vieux", "german": None}}
    mp = type("MP", (), {"script_strings": [_String("New")]})()

    previous = {"script_strings": [{"index": 0, "text": {"english": "Old", "french": "Vieux", "german": None}}]}

    reconciled = strings_writer.reconcile_script_strings(mp, {"script_strings": [entry]}, previous)

    [updated] = reconciled.strings["script_strings"]
    assert updated["text"] == {language: "New" for language in LANGUAGES} and reconciled.updated == [0]


def test_a_string_edited_in_strings_json_since_the_last_build_is_kept() -> None:
    class _String:
        def __init__(self, text: str) -> None:
            self.text = text

    entry = {"index": 0, "text": "Edited by hand"}
    mp = type("MP", (), {"script_strings": [_String("Script text")]})()
    previous = {"script_strings": [{"index": 0, "text": {"english": "Script text"}}]}

    reconciled = strings_writer.reconcile_script_strings(mp, {"script_strings": [entry]}, previous)

    assert reconciled.strings["script_strings"] == [entry] and reconciled.updated == []


def test_a_string_edited_in_a_variant_that_already_had_it_updates_the_same_entry_in_every_language(tmp_path: Path) -> None:
    # A project made from a real variant: its base .bin -- what every build starts from -- already holds the string.
    # Before, the compile added the edited text as a new entry and the old one (with its translations) stayed.
    import shutil

    from in_reach.app.rvt.strings_io import LANGUAGES

    project.create_project(tmp_path)
    source = api.new_gametype_project(tmp_path, "Source", source_variant=resolve_blank_variant(firefight=False))
    (source / "script" / "output.mgl").write_text(_message_script("Hello there"), encoding="utf-8")
    assert api.build(source).success
    shutil.copy(new_project.compiled_variant_path(source), tmp_path / "source.bin")
    folder = api.new_gametype_project(tmp_path, "Real", source_variant=tmp_path / "source.bin")
    strings_path = folder / "settings" / "strings.json"
    data = json.loads(strings_path.read_text(encoding="utf-8"))
    entry = next(e for e in data["script_strings"] if e["text"].get("english") == "Hello there")
    entry["text"]["french"] = "Bonjour"
    strings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    assert api.build(folder).success
    count = len(_strings(folder))

    for text in ("Goodbye", "Farewell"):  # and again: the base still says "Hello there"
        (folder / "script" / "output.mgl").write_text(_message_script(text), encoding="utf-8")
        assert api.build(folder).success

        assert len(_strings(folder)) == count  # no new entry
        [edited] = [e for e in json.loads(strings_path.read_text(encoding="utf-8"))["script_strings"] if e["index"] == entry["index"]]
        assert edited["text"] == {language: text for language in LANGUAGES}
        assert _built_strings(folder)[entry["index"]] == text and "Hello there" not in _built_strings(folder)


def test_edited_literals_pairs_the_strings_changed_in_place() -> None:
    old = 'a("One")\nb("Two")\nc("Three")\nfor each object with label "hill" do\nend\n'
    new = 'a("One")\nb("Deux")\nc("Three")\nd("Four")\nfor each object with label "hills" do\nend\n'

    assert strings_writer.edited_literals(old, new) == [("Two", "Deux")]  # a label is renamed elsewhere; "Four" is new


def test_edited_literals_leaves_a_string_the_new_script_still_uses() -> None:
    assert strings_writer.edited_literals('a("One")\nb("Two")\n', 'a("Two")\nb("Two")\n') == []
