"""Loading whole script projects from disk: :func:`in_reach.app.script_project.project.load_project`.

The base project is the design's own worked example (``TO_IMPLEMENT`` §13, "Hill Rush"); each test changes it
to break one thing and checks that exactly that is reported, in the right file at the right line.
"""
from pathlib import Path

import pytest

from hill_project import HILL as _HILL
from hill_project import PROJECT_TOML as _PROJECT_TOML
from hill_project import write_project
from in_reach.app.script_project.project import is_linked, load_project

def _write(folder: Path, files: dict[str, str | None]) -> Path:
    return write_project(folder, files)


def _project(tmp_path: Path, **changes: str | None):
    """The Hill Rush project with ``changes`` applied (keys use ``__`` for ``/`` and ``_dot_`` for ``.``; a value
    of ``None`` leaves that file out)."""
    files = dict(_HILL)
    for key, value in changes.items():
        files[key.replace("__", "/").replace("_dot_", ".").replace("_dash_", "-")] = value
    return load_project(_write(tmp_path, files))


def _codes(project) -> list[tuple[str, str, int]]:
    return [(d.code, d.file, d.line) for d in project.diagnostics]


# -- the design's example -------------------------------------------------------------------------------


def test_the_design_example_loads_without_a_single_diagnostic(tmp_path: Path) -> None:
    project = _project(tmp_path)

    assert project.diagnostics == [] and project.ok


def test_blocks_come_from_files_and_from_fragments(tmp_path: Path) -> None:
    project = _project(tmp_path)

    assert set(project.blocks) == {"SETUP", "HILL_PASS", "WIN_CHECK"}
    assert project.blocks["SETUP"].file.path == "blocks/setup.mgl"
    assert project.blocks["HILL_PASS"].file is None  # exists only because two modules contribute to it
    assert project.blocks["HILL_PASS"].contributors == ["hill_score", "hill_buff"]


def test_a_module_knows_which_blocks_it_contributes_to(tmp_path: Path) -> None:
    project = _project(tmp_path)

    assert {m.name: m.blocks for m in project.modules} == {"hill_score": ["HILL_PASS"], "hill_buff": ["HILL_PASS"]}


def test_the_blocks_are_in_the_listed_order(tmp_path: Path) -> None:
    assert _project(tmp_path).order == ["SETUP", "HILL_PASS", "WIN_CHECK"]


def test_the_profile_overrides_the_projects_constants(tmp_path: Path) -> None:
    project = _project(tmp_path)

    assert project.constants == {"SCORE_INTERVAL": "1", "SCORE_TO_WIN": "5"}  # dev.env says 5, project.toml says 50
    assert project.profile.name == "dev"


def test_a_modules_parameter_reaches_its_own_files(tmp_path: Path) -> None:
    project = _project(tmp_path)
    score = next(m for m in project.modules if m.name == "hill_score")

    assert score.constants["score_interval"] == "1"
    timer = next(a for a in score.files[0].annotations.items if a.kind == "storage")
    assert timer.name == "p_hill_timer" and timer.default.value == 1  # default=${score_interval}, filled in


def test_an_importer_can_set_a_parameter(tmp_path: Path) -> None:
    toml = _PROJECT_TOML.replace('name = "hill_score"\n', 'name = "hill_score"\nparams = { score_interval = 7 }\n')

    project = _project(tmp_path, project_dot_toml=toml)

    assert project.diagnostics == []
    score = next(m for m in project.modules if m.name == "hill_score")
    assert next(a for a in score.files[0].annotations.items if a.kind == "storage").default.value == 7


def test_a_blocks_constants_are_the_projects_and_the_profiles(tmp_path: Path) -> None:
    project = _project(tmp_path)

    assert "global.number[0] == 5" in project.blocks["WIN_CHECK"].file.processed


def test_profile_flags_decide_which_if_blocks_survive(tmp_path: Path) -> None:
    dev = _project(tmp_path / "dev")
    release = _project(tmp_path / "release", env__dev_dot_env="FLAGS=\nSCORE_TO_WIN=5\n")

    buff = lambda project: next(m for m in project.modules if m.name == "hill_buff").files[0].processed
    assert "y = 1" in buff(dev) and "y = 1" not in buff(release)


def test_annotations_are_read_from_every_file_with_the_files_path(tmp_path: Path) -> None:
    project = _project(tmp_path)

    found = {f.path: [a.kind for a in f.annotations.items] for f in project.files}
    assert found == {
        "blocks/setup.mgl": ["storage"],
        "blocks/win_check.mgl": ["doc"],
        "modules/hill_score/hill_score.mgl": ["storage", "fragment", "loop"],
        "modules/hill_buff/hill_buff.mgl": ["trait", "fragment", "loop"],
    }


def test_kinds_defined_in_the_project_and_a_module_are_merged(tmp_path: Path) -> None:
    project = _project(tmp_path)

    assert project.kinds["hill"].reached_by == ["label:hill"]
    assert project.kinds["hill"].defined_by == ["project.toml", "module hill_score"]


# -- is it a linked project? ----------------------------------------------------------------------------


def test_a_folder_without_a_project_toml_is_not_linked(tmp_path: Path) -> None:
    (tmp_path / "script").mkdir()
    (tmp_path / "script" / "output.txt").write_text("x = 1\n", encoding="utf-8")

    assert not is_linked(tmp_path)


def test_a_folder_with_a_project_toml_is_linked(tmp_path: Path) -> None:
    _write(tmp_path, {"project.toml": ""})

    assert is_linked(tmp_path)


def test_loading_an_unlinked_folder_says_so_instead_of_raising(tmp_path: Path) -> None:
    project = load_project(tmp_path)

    assert _codes(project) == [("project-missing", "project.toml", 0)]


# -- project.toml ---------------------------------------------------------------------------------------


def test_a_syntax_error_in_project_toml_stops_there_and_says_where(tmp_path: Path) -> None:
    project = _project(tmp_path, project_dot_toml='[project]\nname = "x"\n[blocks\n')

    assert [(d.code, d.file, d.line) for d in project.diagnostics] == [("toml-syntax", "project.toml", 3)]
    assert project.manifest is None and project.modules == []


def test_a_wrong_value_in_project_toml_is_located(tmp_path: Path) -> None:
    project = _project(tmp_path, project_dot_toml='[project]\ndialect = "mgl/9"\n')

    assert _codes(project) == [("manifest-invalid-value", "project.toml", 2)]


def test_an_unknown_key_in_project_toml_is_only_a_warning(tmp_path: Path) -> None:
    project = _project(tmp_path, project_dot_toml=_PROJECT_TOML.replace("[project]\n", "[project]\nwhat = 1\n", 1))

    unknown = [d for d in project.diagnostics if d.code == "manifest-unknown-key"]
    assert [(d.file, d.line, d.severity) for d in unknown] == [("project.toml", 2, "warning")]
    assert project.ok


def test_a_bad_project_constant_is_reported_at_its_line_and_the_rest_still_load(tmp_path: Path) -> None:
    toml = _PROJECT_TOML.replace("SCORE_TO_WIN = 50", 'SCORE_TO_WIN = "not a value"')

    project = _project(tmp_path, project_dot_toml=toml, env__dev_dot_env="FLAGS=DEV\n")

    assert ("constant-value", "project.toml", 7) in _codes(project)
    assert project.constants["SCORE_INTERVAL"] == "1"


# -- profiles -------------------------------------------------------------------------------------------


def test_the_ides_active_profile_beats_the_one_project_toml_names(tmp_path: Path) -> None:
    project = _project(
        tmp_path,
        env__release_dot_env="FLAGS=\nSCORE_TO_WIN=99\n",
        env__active_profile_dot_txt="release\n",
    )

    assert project.profile.name == "release" and project.constants["SCORE_TO_WIN"] == "99"


def test_a_profile_that_does_not_exist_is_reported_and_the_load_carries_on(tmp_path: Path) -> None:
    project = _project(tmp_path, env__dev_dot_env=None)

    assert ("profile-invalid", "env/dev.env", 0) in _codes(project)
    assert project.profile is None and project.constants["SCORE_TO_WIN"] == "50"  # project.toml's default stands


def test_a_broken_profile_is_reported_at_its_line(tmp_path: Path) -> None:
    project = _project(tmp_path, env__dev_dot_env="FLAGS=DEV\nnot a setting\n")

    assert ("profile-invalid", "env/dev.env", 2) in _codes(project)


# -- modules --------------------------------------------------------------------------------------------


def test_a_listed_module_with_no_folder_is_reported_at_its_entry(tmp_path: Path) -> None:
    toml = _PROJECT_TOML + '\n[[modules]]\nname = "ghost"\n'

    project = _project(tmp_path, project_dot_toml=toml)

    assert _codes(project) == [("module-missing", "project.toml", 22)]


def test_a_module_without_a_manifest_is_reported(tmp_path: Path) -> None:
    project = _project(tmp_path, modules__hill_buff__module_dot_toml=None)

    assert ("file-missing", "modules/hill_buff/module.toml", 0) in _codes(project)


def test_a_module_listed_twice_is_reported_at_the_second_entry(tmp_path: Path) -> None:
    project = _project(tmp_path, project_dot_toml=_PROJECT_TOML + '\n[[modules]]\nname = "hill_buff"\n')

    assert ("module-duplicate", "project.toml", 22) in _codes(project)


def test_an_invalid_module_name_is_reported(tmp_path: Path) -> None:
    project = _project(tmp_path, project_dot_toml=_PROJECT_TOML + '\n[[modules]]\nname = "9bad"\n')

    assert ("module-name", "project.toml", 22) in _codes(project)


def test_a_manifest_naming_a_different_module_than_its_folder_is_reported(tmp_path: Path) -> None:
    project = _project(tmp_path, modules__hill_buff__module_dot_toml='[module]\nname = "other"\n')

    assert ("module-name-mismatch", "modules/hill_buff/module.toml", 2) in _codes(project)


def test_a_module_folder_nothing_lists_is_a_warning(tmp_path: Path) -> None:
    project = _project(
        tmp_path,
        modules__spare__module_dot_toml='[module]\nname = "spare"\n',
        modules__spare__spare_dot_mgl="x = 1\n",
    )

    assert _codes(project) == [("module-unlisted", "modules/spare/module.toml", 0)]
    assert project.diagnostics[0].severity == "warning" and project.ok


def test_a_module_with_no_source_files_is_a_warning(tmp_path: Path) -> None:
    project = _project(tmp_path, modules__hill_buff__hill_buff_dot_mgl=None)

    assert _codes(project) == [("module-empty", "modules/hill_buff/module.toml", 0)]


def test_a_modules_old_requires_table_is_explained(tmp_path: Path) -> None:
    project = _project(
        tmp_path, modules__hill_buff__module_dot_toml='[module]\nname = "hill_buff"\n\n[requires]\ntraits = 1\n'
    )

    assert _codes(project) == [("manifest-dropped-table", "modules/hill_buff/module.toml", 4)]


def test_a_module_can_have_several_source_files_in_subfolders(tmp_path: Path) -> None:
    project = _project(tmp_path, modules__hill_buff__more__extra_dot_mgl="-- @number g_extra\n")

    buff = next(m for m in project.modules if m.name == "hill_buff")
    assert [f.path for f in buff.files] == ["modules/hill_buff/hill_buff.mgl", "modules/hill_buff/more/extra.mgl"]


# -- module parameters ----------------------------------------------------------------------------------


def test_setting_a_parameter_the_module_lacks_is_reported_at_the_importers_line(tmp_path: Path) -> None:
    toml = _PROJECT_TOML.replace('name = "hill_buff"\n', 'name = "hill_buff"\nparams = { speed = 3 }\n')

    project = _project(tmp_path, project_dot_toml=toml)

    assert _codes(project) == [("param-unknown", "project.toml", 17)]
    assert "module parameter:" in project.diagnostics[0].message


def test_a_parameter_without_a_default_that_nobody_sets_is_reported_at_the_import(tmp_path: Path) -> None:
    manifest = _HILL["modules/hill_score/module.toml"].replace(
        'default = "${SCORE_INTERVAL}"', 'doc = "no default"'
    )

    project = _project(tmp_path, modules__hill_score__module_dot_toml=manifest)

    assert ("param-missing", "project.toml", 12) in _codes(project)


def test_a_bad_default_is_reported_in_the_modules_own_manifest(tmp_path: Path) -> None:
    manifest = _HILL["modules/hill_score/module.toml"].replace('default = "${SCORE_INTERVAL}"', 'default = "hello"')

    project = _project(tmp_path, modules__hill_score__module_dot_toml=manifest)

    assert ("param-type", "modules/hill_score/module.toml", 9) in _codes(project)


def test_a_default_naming_an_undefined_constant_is_reported(tmp_path: Path) -> None:
    manifest = _HILL["modules/hill_score/module.toml"].replace("${SCORE_INTERVAL}", "${GHOST}")

    project = _project(tmp_path, modules__hill_score__module_dot_toml=manifest)

    assert ("param-undefined", "modules/hill_score/module.toml", 9) in _codes(project)


# -- preprocessing and annotations ----------------------------------------------------------------------


def test_an_undefined_placeholder_is_reported_at_its_line_and_column_and_only_that_file_loses_its_annotations(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path, modules__hill_buff__hill_buff_dot_mgl="-- @number g_x\nx = ${NOPE}\n")

    broken = [d for d in project.diagnostics if d.code == "preprocess"]
    assert [(d.file, d.line, d.col) for d in broken] == [("modules/hill_buff/hill_buff.mgl", 2, 4)]
    buff = next(m for m in project.modules if m.name == "hill_buff")
    assert buff.files[0].processed is None and buff.files[0].annotations.items == []
    score = next(m for m in project.modules if m.name == "hill_score")
    assert score.files[0].annotations.items  # the other module is unaffected


def test_a_malformed_annotation_is_reported_with_its_file_and_line(tmp_path: Path) -> None:
    text = "-- @fragment HILL_PASS.buff\n-- @number ok\n\n-- @timer bad priority=low\n-- @loop nope\n"

    project = _project(tmp_path, modules__hill_buff__hill_buff_dot_mgl=text)

    found = [(d.file, d.line, d.code) for d in project.diagnostics]
    assert found == [
        ("modules/hill_buff/hill_buff.mgl", 4, "annotation"),
        ("modules/hill_buff/hill_buff.mgl", 5, "annotation"),
    ]
    buff = next(m for m in project.modules if m.name == "hill_buff")
    assert [a.kind for a in buff.files[0].annotations.items] == ["fragment", "storage"]  # the good ones survive


def test_line_numbers_survive_an_if_block_being_removed(tmp_path: Path) -> None:
    text = "-- @fragment HILL_PASS.buff\n-- @if DEV\nx = 1\ny = 2\n-- @end\n-- @loop nope\n"

    project = _project(tmp_path, modules__hill_buff__hill_buff_dot_mgl=text, env__dev_dot_env="FLAGS=\n")

    assert [(d.line, d.code) for d in project.diagnostics] == [(6, "annotation")]


def test_a_file_that_is_not_utf8_is_reported_not_raised(tmp_path: Path) -> None:
    _write(tmp_path, _HILL)
    (tmp_path / "script" / "blocks" / "setup.mgl").write_bytes(b"\xff\xfe\x00bad")

    project = load_project(tmp_path)

    assert [d.code for d in project.diagnostics] == ["file-unreadable"]


# -- blocks and their order -----------------------------------------------------------------------------


def test_a_block_files_name_is_its_stem_upper_cased(tmp_path: Path) -> None:
    project = _project(tmp_path, blocks__map_roll_dot_mgl="x = 1\n")

    assert "MAP_ROLL" in project.blocks and project.blocks["MAP_ROLL"].file.path == "blocks/map_roll.mgl"


def test_a_block_file_name_that_cannot_be_a_block_name_is_reported(tmp_path: Path) -> None:
    project = _project(tmp_path, blocks__map_dash_roll_dot_mgl="x = 1\n")

    assert ("block-name", "blocks/map-roll.mgl", 0) in _codes(project)


def test_a_listed_block_nothing_defines_is_a_warning(tmp_path: Path) -> None:
    toml = _PROJECT_TOML.replace('"WIN_CHECK"]', '"WIN_CHECK", "GHOST"]')

    project = _project(tmp_path, project_dot_toml=toml)

    assert _codes(project) == [("block-undefined", "project.toml", 10)]
    assert "GHOST" in project.order  # still ordered, so a later fragment can fill it


def test_a_block_listed_twice_is_reported(tmp_path: Path) -> None:
    toml = _PROJECT_TOML.replace('"WIN_CHECK"]', '"WIN_CHECK", "SETUP"]')

    assert ("block-order-duplicate", "project.toml", 10) in _codes(_project(tmp_path, project_dot_toml=toml))


def test_a_modules_order_can_move_its_blocks_later_than_the_list_puts_them(tmp_path: Path) -> None:
    manifest = '[module]\nname = "hill_buff"\n\n[order]\nafter = ["WIN_CHECK"]\n'

    project = _project(tmp_path, modules__hill_buff__module_dot_toml=manifest)

    # hill_buff contributes to HILL_PASS, which the list puts before WIN_CHECK -- so those two now conflict
    assert [d.code for d in project.diagnostics] == ["order-cycle"]


def test_a_block_only_a_module_orders_is_placed_by_its_constraints(tmp_path: Path) -> None:
    toml = _PROJECT_TOML.replace('order = ["SETUP", "HILL_PASS", "WIN_CHECK"]', 'order = ["SETUP", "WIN_CHECK"]')

    project = _project(
        tmp_path,
        project_dot_toml=toml,
        modules__hill_score__module_dot_toml=_HILL["modules/hill_score/module.toml"].replace(
            'after = ["SETUP"]', 'after = ["SETUP"]\nbefore = ["WIN_CHECK"]'
        ),
        modules__hill_buff__module_dot_toml='[module]\nname = "hill_buff"\n\n[order]\nafter = ["SETUP"]\nbefore = ["WIN_CHECK"]\n',
    )

    assert project.diagnostics == []
    assert project.order == ["SETUP", "HILL_PASS", "WIN_CHECK"]


def test_an_order_naming_a_block_that_does_not_exist_is_reported_in_the_modules_manifest(tmp_path: Path) -> None:
    manifest = '[module]\nname = "hill_buff"\n\n[order]\nafter = ["NOWHERE"]\n'

    project = _project(tmp_path, modules__hill_buff__module_dot_toml=manifest)

    assert _codes(project) == [("order-unknown-block", "modules/hill_buff/module.toml", 5)]


def test_an_order_with_no_fragments_to_apply_it_to_is_a_warning(tmp_path: Path) -> None:
    project = _project(tmp_path, modules__hill_buff__hill_buff_dot_mgl="-- @number g_only_storage\n")

    assert _codes(project) == [("order-unused", "modules/hill_buff/module.toml", 4)]
    assert project.ok


def test_a_cycle_names_every_edge_that_forms_it(tmp_path: Path) -> None:
    manifest = '[module]\nname = "hill_buff"\n\n[order]\nbefore = ["SETUP"]\n'

    project = _project(tmp_path, modules__hill_buff__module_dot_toml=manifest)

    [cycle] = [d for d in project.diagnostics if d.code == "order-cycle"]
    assert cycle.file == "project.toml"
    assert "module hill_buff [order]" in cycle.message and "project.toml [blocks].order" in cycle.message


# -- kinds ----------------------------------------------------------------------------------------------


def test_a_kind_defined_two_ways_is_a_conflict(tmp_path: Path) -> None:
    manifest = _HILL["modules/hill_score/module.toml"].replace('reached_by = ["label:hill"]', 'reached_by = ["label:other"]')

    project = _project(tmp_path, modules__hill_score__module_dot_toml=manifest)

    assert ("kind-conflict", "modules/hill_score/module.toml", 12) in _codes(project)


def test_two_kinds_cannot_be_reached_the_same_way(tmp_path: Path) -> None:
    toml = _PROJECT_TOML + '\n[kinds.mound]\nreached_by = ["label:hill"]\n'

    project = _project(tmp_path, project_dot_toml=toml)

    [conflict] = [d for d in project.diagnostics if d.code == "kind-conflict"]
    assert "can't reach both hill and mound" in conflict.message and conflict.file == "project.toml"


def test_the_same_kind_defined_identically_twice_is_fine(tmp_path: Path) -> None:
    project = _project(tmp_path)  # the design example defines hill in project.toml and in hill_score

    assert not [d for d in project.diagnostics if d.code == "kind-conflict"]


# -- never raises ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "toml",
    ["", "[[modules]]\n", "[blocks]\norder = 5\n", "constants = 3\n", "\x00", "[modules]\nname = 1\n", "kinds = []\n"],
)
def test_loading_never_raises_on_a_broken_project_toml(tmp_path: Path, toml: str) -> None:
    project = load_project(_write(tmp_path, {"project.toml": toml}))

    assert isinstance(project.diagnostics, list)
