"""Forge labels created by a script, end to end.

The *script* decides how many forge labels a variant has -- naming one in ``for each object with label
"hill"`` creates it; nothing in ``settings/`` can, and the native binding has no add-label call. Three
layers had to agree for a project started from a blank variant to build once its script named a label:

- :mod:`~in_reach.app.rvt.megalo_compiler` has to create the label itself instead of giving up (it
  asks the native compiler to, via a stub);
- :func:`~in_reach.app.rvt.settings_writer.reconcile_forge_labels` and
  :func:`~in_reach.app.rvt.strings_writer.reconcile_script_strings` have to make ``settings/`` follow
  the compiled variant, instead of ``apply_*`` refusing a length mismatch; and
- :mod:`~in_reach.app.rvt.compile` has to write that back, or Apply reads "unapplied" forever.

Before any of this, such a project failed outright with "script_settings.forge_labels has 0 entries,
but this variant has 1".
"""
import json
from pathlib import Path

import pytest

from in_reach.app import apply_settings, new_project, project
from in_reach.app.blank_variant import resolve_blank_variant
from in_reach.app.rvt import compile as compile_module
from in_reach.app.rvt import megalo_compiler, rvt_bridge, settings_writer, strings_io, strings_writer, template_source
from in_reach.app.rvt.decompile import normalize_script_text
from in_reach.app.rvt.models.script_settings import ForgeLabel, ScriptSettings

_JUGGERNAUT_BIN = Path(__file__).parent / "resources" / "juggernaut" / "juggernaut.bin"

pytestmark = pytest.mark.skipif(
    not rvt_bridge.is_available(), reason="native _reachvarianttool extension not available on this platform"
)
_NEEDS_JUGGERNAUT = pytest.mark.skipif(not _JUGGERNAUT_BIN.is_file(), reason="juggernaut fixture .bin not present")


@pytest.fixture(scope="module")
def rvt():
    return rvt_bridge.get_rvt()


@pytest.fixture
def blank(rvt):
    return rvt.load(str(resolve_blank_variant(firefight=False)))


def _label_names(rvt, variant) -> list[str | None]:
    """Each label's English name (``None`` for one that has no name at all, which real variants have)."""
    mp = variant.multiplayer
    english = rvt.Language.english
    names = [mp.forge_label(i).name for i in range(mp.forge_label_count)]
    return [name.get_content(english) if name is not None else None for name in names]


def _loop(label: str, body: str = "current_object.delete()") -> str:
    return f'for each object with label "{label}" do\n   {body}\nend\n'


def _pool(rvt):
    return lambda: template_source.build_variants(rvt)


def _compile(rvt, variant, source: str) -> None:
    megalo_compiler.compile_script(rvt, variant, source, template_pool=_pool(rvt))


def _with_native_labels(rvt, *names: str):
    """A blank variant that already carries ``names`` as forge labels (created the only way one can
    be: by natively compiling a script that names them)."""
    variant = rvt.load(str(resolve_blank_variant(firefight=False)))
    script = "".join(_loop(name) for name in names)
    assert variant.multiplayer.compile_script("on init: do\n" + script + "end\n").success
    return variant


# -- the compiler creates the labels a script names ----------------------------------------------


def test_a_label_a_script_names_is_created_in_house(rvt, blank) -> None:
    _compile(rvt, blank, _loop("hill"))
    assert _label_names(rvt, blank) == ["hill"]
    assert 'for each object with label "hill" do' in normalize_script_text(blank.decompile_script())


def test_the_in_house_compiler_declares_a_variable_the_script_uses_as_native_does(rvt, blank) -> None:
    """Native declares every variable a script uses (``declare global.number[0] ...``), and so does
    the in-house compiler -- to the same network priority."""
    source = _loop("hill", "global.number[0] = 1")
    _compile(rvt, blank, source)
    native = rvt.load(str(resolve_blank_variant(firefight=False)))
    assert native.multiplayer.compile_script(source).success
    assert "declare global.number[0] with network priority low" in normalize_script_text(native.decompile_script())
    assert normalize_script_text(blank.decompile_script()) == normalize_script_text(native.decompile_script())


def test_without_that_step_a_missing_label_is_unsupported(rvt, blank, monkeypatch) -> None:
    """The twin of the test above: proves it's the vivify step doing the work, and that a compile
    which can never make the label exist gives up rather than restarting forever."""
    monkeypatch.setattr(megalo_compiler._Compiler, "_vivify_forge_labels", lambda self, names: None)
    with pytest.raises(megalo_compiler.UnsupportedConstruct, match="kept discovering new forge labels"):
        _compile(rvt, blank, _loop("hill"))


def test_looking_up_a_label_that_does_not_exist_raises_the_recoverable_kind(rvt, blank) -> None:
    compiler = megalo_compiler._Compiler(rvt, blank)
    expr = megalo_compiler.parse(_loop("hill")).body[0].label
    with pytest.raises(megalo_compiler.MissingForgeLabel, match="no unique forge label named 'hill'") as excinfo:
        compiler._resolve_forge_label_index(expr)
    assert excinfo.value.raw == "hill"


def test_each_distinct_label_is_created_once_in_first_use_order(rvt, blank) -> None:
    source = _loop("hill") + _loop("flag") + _loop("hill", "current_object.set_invincibility(1)") + _loop("bomb")
    _compile(rvt, blank, source)
    assert _label_names(rvt, blank) == ["hill", "flag", "bomb"]


def test_a_label_the_variant_already_has_is_reused_not_duplicated(rvt) -> None:
    variant = _with_native_labels(rvt, "hill")
    _compile(rvt, variant, _loop("hill") + _loop("flag"))
    assert _label_names(rvt, variant) == ["hill", "flag"]


def test_a_label_named_only_inside_a_function_body_is_found(rvt, blank) -> None:
    _compile(rvt, blank, "function sweep()\n" + "".join("   " + line + "\n" for line in _loop("hill").splitlines()) + "end\nsweep()\n")
    assert _label_names(rvt, blank) == ["hill"]


def test_a_label_named_as_a_call_argument_is_created_by_restarting_the_compile(rvt, blank) -> None:
    """Only ``for each ... with label`` is found by the up-front scan; any other place a label can be
    written is discovered mid-compile, when it can only be recovered from by starting over."""
    source = 'for each object do\n   if current_object.has_forge_label("hill") then\n      current_object.delete()\n   end\nend\n'
    _compile(rvt, blank, source)
    assert _label_names(rvt, blank) == ["hill"]
    assert 'has_forge_label("hill")' in normalize_script_text(blank.decompile_script())


def test_a_restart_after_discovering_a_label_does_not_trip_the_duplicate_function_check(rvt, blank) -> None:
    source = (
        "function check()\n"
        '   if current_object.has_forge_label("hill") then\n'
        "      current_object.delete()\n"
        "   end\n"
        "end\n"
        "for each object do\n   check()\nend\n"
    )
    _compile(rvt, blank, source)
    assert _label_names(rvt, blank) == ["hill"]


def test_several_labels_discovered_mid_compile_each_cost_one_restart_and_all_get_created(rvt, blank) -> None:
    source = "for each object do\n" + "".join(
        f'   if current_object.has_forge_label("{name}") then\n      current_object.delete()\n   end\n' for name in ("a", "b", "c")
    ) + "end\n"
    _compile(rvt, blank, source)
    assert _label_names(rvt, blank) == ["a", "b", "c"]


def test_a_label_by_number_that_does_not_exist_is_still_unsupported(rvt, blank) -> None:
    with pytest.raises(megalo_compiler.UnsupportedConstruct, match="out of range"):
        _compile(rvt, blank, "for each object with label 3 do\n   current_object.delete()\nend\n")


def test_a_variant_can_only_have_sixteen_labels(rvt, blank) -> None:
    source = "".join(_loop(f"label{i}") for i in range(17))
    with pytest.raises(megalo_compiler.UnsupportedConstruct, match="at most 16"):
        _compile(rvt, blank, source)


def test_sixteen_labels_is_fine(rvt, blank) -> None:
    _compile(rvt, blank, "".join(_loop(f"label{i}") for i in range(16)))
    assert len(_label_names(rvt, blank)) == 16


@_NEEDS_JUGGERNAUT
def test_the_base_variants_own_templates_survive_creating_a_label(rvt) -> None:
    """Creating a label replaces the variant's script (with a stub) -- but the templates were already
    scanned from a copy, so a script leaning on the base's own examples still compiles, with no pool."""
    variant = rvt.load(str(_JUGGERNAUT_BIN))
    source = _loop("hill", "global.number[0] = 1") + "if global.number[0] == 1 then\n   game.end_round()\nend\n"
    megalo_compiler.compile_script(rvt, variant, source)
    assert "hill" in _label_names(rvt, variant)
    text = normalize_script_text(variant.decompile_script())
    assert "global.number[0] = 1" in text and "game.end_round()" in text


def test_a_label_names_escapes_are_matched_after_unescaping(rvt, blank) -> None:
    _compile(rvt, blank, _loop("a\\\"b"))
    assert _label_names(rvt, blank) == ['a"b']
    # ...and a second mention of the same name resolves to it rather than creating another.
    _compile(rvt, blank, _loop("a\\\"b") + _loop("a\\\"b", "current_object.set_invincibility(1)"))
    assert _label_names(rvt, blank) == ['a"b']


# -- settings/script_settings.json follows the compiled variant ----------------------------------------


def _settings_for(labels: list[ForgeLabel]) -> ScriptSettings:
    return ScriptSettings(forge_labels=labels)


def test_labels_the_script_created_are_added_to_settings_with_their_real_names(rvt) -> None:
    variant = _with_native_labels(rvt, "hill", "flag")
    result = settings_writer.reconcile_forge_labels(rvt, variant.multiplayer, _settings_for([]), [])
    assert [label.name for label in result.script_settings.forge_labels] == ["hill", "flag"]
    assert result.added == ["hill", "flag"] and result.removed == [] and result.changed


def test_a_label_that_already_matches_changes_nothing_and_returns_the_same_object(rvt) -> None:
    variant = _with_native_labels(rvt, "hill")
    settings = _settings_for([ForgeLabel(name="hill")])
    result = settings_writer.reconcile_forge_labels(rvt, variant.multiplayer, settings, [])
    assert result.script_settings is settings and not result.changed


def test_entries_a_user_already_edited_are_kept_when_more_labels_appear(rvt) -> None:
    variant = _with_native_labels(rvt, "hill", "flag")
    edited = ForgeLabel(name="hill", requires_number=True, required_number=3, map_must_have_at_least=2)
    result = settings_writer.reconcile_forge_labels(rvt, variant.multiplayer, _settings_for([edited]), [])
    assert result.script_settings.forge_labels[0] == edited
    assert [label.name for label in result.script_settings.forge_labels] == ["hill", "flag"]
    assert result.added == ["flag"]


def test_trailing_untouched_entries_the_script_no_longer_needs_are_dropped(rvt, blank) -> None:
    settings = _settings_for([ForgeLabel(name="hill"), ForgeLabel(name="flag")])
    result = settings_writer.reconcile_forge_labels(rvt, blank.multiplayer, settings, [])
    assert result.script_settings.forge_labels == []
    assert result.removed == ["flag", "hill"] and result.changed


def test_a_trailing_entry_the_user_edited_is_never_silently_dropped(rvt, blank) -> None:
    kept = ForgeLabel(name="hill", requires_number=True, required_number=5)
    settings = _settings_for([kept])
    result = settings_writer.reconcile_forge_labels(rvt, blank.multiplayer, settings, [])
    assert result.script_settings.forge_labels == [kept] and not result.changed
    # ...so applying it still reports the mismatch, exactly as before.
    with pytest.raises(ValueError, match="forge_labels has 1 entries, but this variant has 0"):
        settings_writer.apply_script_settings(blank.multiplayer, result.script_settings)


def test_only_the_untouched_tail_is_dropped_when_an_edited_entry_sits_before_it(rvt) -> None:
    variant = _with_native_labels(rvt, "hill")
    edited = ForgeLabel(name="hill", requires_number=True, required_number=1)
    settings = _settings_for([edited, ForgeLabel(name="flag")])
    result = settings_writer.reconcile_forge_labels(rvt, variant.multiplayer, settings, [])
    assert result.script_settings.forge_labels == [edited]
    assert result.removed == ["flag"]


def test_the_input_settings_are_never_mutated(rvt) -> None:
    variant = _with_native_labels(rvt, "hill")
    settings = _settings_for([])
    settings_writer.reconcile_forge_labels(rvt, variant.multiplayer, settings, [])
    assert settings.forge_labels == []


def test_a_freshly_extracted_label_counts_as_untouched(rvt) -> None:
    """What makes the add-then-remove round trip lossless: the entry reconcile itself creates must
    read as pristine, or removing the label from the script could never clean it up."""
    variant = _with_native_labels(rvt, "hill")
    added = settings_writer.reconcile_forge_labels(rvt, variant.multiplayer, _settings_for([]), []).script_settings
    assert settings_writer._is_pristine_forge_label(added.forge_labels[0])


# -- settings/strings.json follows the compiled variant ------------------------------------------------


def _strings_of(rvt, variant) -> dict:
    return strings_io.extract_strings(variant.multiplayer)


def test_strings_the_script_created_are_added_to_strings_json(rvt, blank) -> None:
    before = _strings_of(rvt, blank)
    _compile(rvt, blank, _loop("hill"))
    result = strings_writer.reconcile_script_strings(blank.multiplayer, before)
    assert result.changed and result.removed == []
    texts = [entry["text"]["english"] for entry in result.strings["script_strings"]]
    assert "hill" in texts
    assert [e["index"] for e in result.strings["script_strings"]] == sorted(e["index"] for e in result.strings["script_strings"])


def test_a_format_string_the_script_created_is_added_too(rvt, blank) -> None:
    before = _strings_of(rvt, blank)
    _compile(rvt, blank, 'for each player do\n   current_player.set_objective_text("hello there")\nend\n')
    result = strings_writer.reconcile_script_strings(blank.multiplayer, before)
    assert "hello there" in [entry["text"]["english"] for entry in result.strings["script_strings"]]


def test_matching_strings_change_nothing_and_return_the_same_document(rvt, blank) -> None:
    doc = _strings_of(rvt, blank)
    result = strings_writer.reconcile_script_strings(blank.multiplayer, doc)
    assert result.strings is doc and not result.changed


def test_other_parts_of_the_strings_document_are_carried_through(rvt, blank) -> None:
    before = _strings_of(rvt, blank)
    _compile(rvt, blank, _loop("hill"))
    result = strings_writer.reconcile_script_strings(blank.multiplayer, before)
    assert result.strings["meta"] == before["meta"] and result.strings["teams"] == before["teams"]


def test_the_input_strings_document_is_never_mutated(rvt, blank) -> None:
    before = _strings_of(rvt, blank)
    snapshot = json.dumps(before, sort_keys=True)
    _compile(rvt, blank, _loop("hill"))
    strings_writer.reconcile_script_strings(blank.multiplayer, before)
    assert json.dumps(before, sort_keys=True) == snapshot


def _entry(index: int, english: str, **other: str) -> dict:
    languages = {"english": english, "japanese": None, "german": None, "french": None}
    languages.update(other)
    return {"index": index, "text": languages}


def _with_extra_entries(rvt, variant, *extra: dict) -> dict:
    """The variant's own real strings document, plus entries for indexes just past its table's end."""
    doc = _strings_of(rvt, variant)
    size = len(variant.multiplayer.script_strings)
    return {**doc, "script_strings": doc["script_strings"] + [{**entry, "index": size + i} for i, entry in enumerate(extra)]}


def test_trailing_untranslated_entries_past_the_end_of_the_table_are_dropped(rvt, blank) -> None:
    original = _strings_of(rvt, blank)
    doc = _with_extra_entries(rvt, blank, _entry(0, "hill"), _entry(0, "flag"))
    size = len(original["script_strings"])

    result = strings_writer.reconcile_script_strings(blank.multiplayer, doc)

    assert result.strings["script_strings"] == original["script_strings"]
    assert result.removed == [size + 1, size] and result.added == []


def test_a_label_names_string_copied_into_every_language_still_counts_as_untranslated(rvt, blank) -> None:
    every_language = {language: "hill" for language in strings_io.LANGUAGES}
    doc = _with_extra_entries(rvt, blank, {"index": 0, "text": every_language})
    result = strings_writer.reconcile_script_strings(blank.multiplayer, doc)
    assert result.removed == [len(blank.multiplayer.script_strings)]


def test_a_trailing_entry_with_a_real_translation_is_the_users_and_is_kept(rvt, blank) -> None:
    doc = _with_extra_entries(rvt, blank, _entry(0, "hill", german="Huegel"))

    result = strings_writer.reconcile_script_strings(blank.multiplayer, doc)

    assert result.strings is doc and not result.changed
    with pytest.raises(ValueError, match="out of range"):
        strings_writer.apply_strings(blank.multiplayer, result.strings)


# -- through compile.run_compile() ----------------------------------------------------------------------


def _project(tmp_path: Path, script: str | None = None) -> tuple[Path, Path]:
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir(parents=True)
    folder, warning = new_project.create_gametype_project(
        project_dir, "Label Test", source_variant=resolve_blank_variant(firefight=False)
    )
    assert warning is None
    if script is not None:
        (folder / "script" / "output.txt").write_text(script, encoding="utf-8")
    return project_dir, folder


def _script_settings(folder: Path) -> dict:
    return json.loads((folder / "settings" / "script_settings.json").read_text(encoding="utf-8"))


def _strings(folder: Path) -> dict:
    return json.loads((folder / "settings" / "strings.json").read_text(encoding="utf-8"))


def test_a_blank_project_whose_script_names_a_label_now_builds(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, _loop("hill", "global.number[0] = 1"))

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is True, compile_module.format_build_result(result)
    compiled = rvt_bridge.get_rvt().load(str(result.output_path))
    assert _label_names(rvt_bridge.get_rvt(), compiled) == ["hill"]
    assert "declare global.number[0] with network priority low" in compiled.decompile_script()


def test_the_new_label_and_its_name_are_written_back_into_settings(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, _loop("hill"))
    assert _script_settings(folder)["forge_labels"] == []

    compile_module.run_compile(project_dir, folder, save=True)

    assert [label["name"] for label in _script_settings(folder)["forge_labels"]] == ["hill"]
    assert "hill" in [entry["text"]["english"] for entry in _strings(folder)["script_strings"]]


def test_apply_is_not_left_reading_unapplied_afterwards(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, _loop("hill"))
    compile_module.run_compile(project_dir, folder, save=True)
    assert apply_settings.settings_have_unapplied_changes(folder) is False


def test_a_script_that_only_adds_a_format_string_no_longer_leaves_apply_unapplied(tmp_path: Path) -> None:
    """The same gap, found while fixing this one: any script-created string left ``strings.json``
    shorter than the build's own snapshot, forever."""
    project_dir, folder = _project(tmp_path, 'for each player do\n   current_player.set_objective_text("hello there")\nend\n')
    result = compile_module.run_compile(project_dir, folder, save=True)
    assert result.success is True, compile_module.format_build_result(result)
    assert apply_settings.settings_have_unapplied_changes(folder) is False


def test_the_build_says_what_it_added(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, _loop("hill"))
    result = compile_module.run_compile(project_dir, folder, save=True)
    notices = [n.text for n in result.notices]
    assert any("Added forge label(s) to script_settings.json: hill" in n for n in notices)
    assert any("script string(s) to strings.json" in n for n in notices)


def test_applying_twice_is_stable_and_says_nothing_new_the_second_time(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, _loop("hill"))
    compile_module.run_compile(project_dir, folder, save=True)
    settings_before = (folder / "settings" / "script_settings.json").read_bytes()
    strings_before = (folder / "settings" / "strings.json").read_bytes()

    second = compile_module.run_compile(project_dir, folder, save=True)

    assert second.success is True
    assert (folder / "settings" / "script_settings.json").read_bytes() == settings_before
    assert (folder / "settings" / "strings.json").read_bytes() == strings_before
    assert not any("Added" in n.text for n in second.notices)


def test_a_dry_run_reports_success_but_writes_nothing_into_settings(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, _loop("hill"))
    settings_before = (folder / "settings" / "script_settings.json").read_bytes()
    strings_before = (folder / "settings" / "strings.json").read_bytes()

    result = compile_module.run_compile(project_dir, folder, save=False)

    assert result.success is True
    assert (folder / "settings" / "script_settings.json").read_bytes() == settings_before
    assert (folder / "settings" / "strings.json").read_bytes() == strings_before


def test_a_failed_compile_leaves_settings_alone(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, _loop("hill", "this_is_not_a_real_call()"))
    settings_before = (folder / "settings" / "script_settings.json").read_bytes()

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is False
    assert (folder / "settings" / "script_settings.json").read_bytes() == settings_before


def test_the_settings_users_edit_on_a_label_survive_every_later_apply(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, _loop("hill"))
    compile_module.run_compile(project_dir, folder, save=True)
    path = folder / "settings" / "script_settings.json"
    data = _script_settings(folder)
    data["forge_labels"][0].update(requires_number=True, required_number=4, map_must_have_at_least=2)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is True, compile_module.format_build_result(result)
    label = _script_settings(folder)["forge_labels"][0]
    assert (label["requires_number"], label["required_number"], label["map_must_have_at_least"]) == (True, 4, 2)
    compiled = rvt_bridge.get_rvt().load(str(result.output_path))
    assert compiled.multiplayer.forge_label(0).required_number == 4
    assert compiled.multiplayer.forge_label(0).map_must_have_at_least == 2


def test_removing_every_use_of_a_label_cleans_up_what_was_added_for_it(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, _loop("hill"))
    compile_module.run_compile(project_dir, folder, save=True)
    (folder / "script" / "output.txt").write_text("game.end_round()\n", encoding="utf-8")

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is True, compile_module.format_build_result(result)
    assert _script_settings(folder)["forge_labels"] == []
    assert "hill" not in [entry["text"]["english"] for entry in _strings(folder)["script_strings"]]
    assert apply_settings.settings_have_unapplied_changes(folder) is False


def test_removing_a_label_the_user_configured_still_fails_clearly_rather_than_discarding_it(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, _loop("hill"))
    compile_module.run_compile(project_dir, folder, save=True)
    path = folder / "settings" / "script_settings.json"
    data = _script_settings(folder)
    data["forge_labels"][0].update(requires_number=True, required_number=4)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    edited = path.read_bytes()
    (folder / "script" / "output.txt").write_text("game.end_round()\n", encoding="utf-8")

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is False
    assert "forge_labels has 1 entries, but this variant has 0" in compile_module.format_build_result(result)
    assert path.read_bytes() == edited


def test_a_second_label_added_later_is_appended_after_the_first(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, _loop("hill"))
    compile_module.run_compile(project_dir, folder, save=True)
    (folder / "script" / "output.txt").write_text(_loop("hill") + _loop("flag"), encoding="utf-8")

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is True, compile_module.format_build_result(result)
    assert [label["name"] for label in _script_settings(folder)["forge_labels"]] == ["hill", "flag"]


def test_a_project_with_no_labels_at_all_is_untouched_by_any_of_this(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, "game.end_round()\n")
    settings_before = (folder / "settings" / "script_settings.json").read_bytes()
    strings_before = (folder / "settings" / "strings.json").read_bytes()

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is True
    assert (folder / "settings" / "script_settings.json").read_bytes() == settings_before
    assert (folder / "settings" / "strings.json").read_bytes() == strings_before
