"""The semantic model (what a project's files mean) and the linter's structural rules.

Each test writes a small project with one module ``m`` and looks at what the model makes of it, or at exactly which
rule fires at which line -- positions inside a fragment's body are file lines, not body lines.
"""
from pathlib import Path

import pytest

from in_reach.app.script_project import load_project
from in_reach.app.script_project.lint import lint
from in_reach.app.script_project.model import build_model

_PROJECT = '[blocks]\norder = ["SETUP", "PASS"]\n\n[[modules]]\nname = "m"\n\n[kinds.thing]\nreached_by = ["biped"]\n'


def _write(tmp_path: Path, module: str, blocks: dict[str, str] | None = None, project: str = _PROJECT) -> Path:
    files = {
        "project.toml": project,
        "modules/m/module.toml": '[module]\nname = "m"\n',
        "modules/m/m.mgl": module,
        **{f"blocks/{name}.mgl": text for name, text in (blocks or {}).items()},
    }
    for relative, text in files.items():
        path = tmp_path / "script" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def _model(tmp_path: Path, module: str, blocks: dict[str, str] | None = None, project: str = _PROJECT):
    loaded = load_project(_write(tmp_path, module, blocks, project))
    return loaded, build_model(loaded)


def _lint(tmp_path: Path, module: str, blocks: dict[str, str] | None = None, project: str = _PROJECT):
    _, model = _model(tmp_path, module, blocks, project)
    return lint(model)


def _at(found, code: str) -> list[tuple[str, int]]:
    return [(d.file, d.line) for d in found if d.code == code]


_FRAGMENT = "-- @fragment PASS.f\n-- @loop player\nx = 1\n"


# -- regions --------------------------------------------------------------------------------------------


def test_a_fragment_takes_its_header_and_the_lines_after_it(tmp_path: Path) -> None:
    _, model = _model(tmp_path, "-- @doc heals\n-- @fragment PASS.tick\n-- @loop player\n-- @gate a == 1\n-- @guard b == 2\n-- @traits layer=injury\n-- @fusion never\nx = 1\ny = 2\n")

    [fragment] = model.fragments
    assert (fragment.id, fragment.block, fragment.loop, fragment.layer) == ("m.tick", "PASS", "player", "injury")
    assert fragment.doc == ["heals"] and fragment.fusion.mode == "never"
    assert fragment.gate is not None and len(fragment.guards) == 1
    assert [line for line in fragment.body if line.strip()] == ["x = 1", "y = 2"]
    assert fragment.body_line == 8


def test_a_fragments_body_stops_at_the_next_fragment(tmp_path: Path) -> None:
    _, model = _model(tmp_path, _FRAGMENT + "\n-- @fragment PASS.g\n-- @loop team\ny = 2\n")

    first, second = model.fragments
    assert [l for l in first.body if l.strip()] == ["x = 1"]
    assert [l for l in second.body if l.strip()] == ["y = 2"]
    assert (first.loop, second.loop) == ("player", "team")


def test_a_preamble_definition_records_what_it_provides_and_where_fragments_go(tmp_path: Path) -> None:
    text = "-- @preamble ctx\n-- @provides cx:object role:number\n-- @doc sets things up\ncx = 1\nif cx != 0 then\n-- @guard-end\nend\n\n" + _FRAGMENT
    _, model = _model(tmp_path, text)

    preamble = model.preambles["ctx"]
    assert [(v.name, v.type) for v in preamble.provides] == [("cx", "object"), ("role", "number")]
    assert preamble.doc == ["sets things up"]
    assert preamble.body[preamble.guard_index].strip() == "-- @guard-end"
    assert len(model.fragments) == 1  # the definition isn't a fragment


def test_a_guard_end_right_before_a_fragment_header_is_still_the_preambles(tmp_path: Path) -> None:
    text = "-- @preamble ctx\nx = 1\n-- @guard-end\n" + _FRAGMENT

    _, model = _model(tmp_path, text)

    assert model.preambles["ctx"].guard_index == 1 and len(model.fragments) == 1


def test_a_fragment_can_name_a_preamble_to_use(tmp_path: Path) -> None:
    text = "-- @preamble ctx\nx = 1\n\n-- @fragment PASS.f\n-- @loop player\n-- @preamble ctx\ny = 1\n"

    loaded, model = _model(tmp_path, text)

    assert model.fragments[0].preamble == "ctx" and model.diagnostics == []


@pytest.mark.parametrize(
    ("text", "code", "line"),
    [
        ("-- @fragment PASS.f\nx = 1\n", "fragment-no-loop", 1),
        ("-- @fragment PASS.f\n-- @loop player\n-- @loop team\nx = 1\n", "header-duplicate", 3),
        ("-- @fragment PASS.f\n-- @loop player\n-- @fusion auto\n-- @fusion never\nx = 1\n", "header-duplicate", 4),
        (_FRAGMENT + "\n" + _FRAGMENT, "fragment-duplicate", 5),
        ("-- @fragment PASS.f\n-- @loop player\n-- @preamble nope\nx = 1\n", "preamble-unknown", 1),
        ("-- @preamble ctx\nx = 1\n\n-- @preamble ctx\ny = 1\n", "preamble-duplicate", 4),
        ("-- @preamble ctx\n-- @loop player\nx = 1\n", "header-mismatch", 2),
        ("-- @fragment PASS.f\n-- @loop player\n-- @provides a:number\nx = 1\n", "provides-outside-preamble", 3),
    ],
)
def test_header_problems_are_reported_at_their_line(tmp_path: Path, text: str, code: str, line: int) -> None:
    _, model = _model(tmp_path, text)

    assert [(d.code, d.file, d.line) for d in model.diagnostics if d.code == code] == [(code, "modules/m/m.mgl", line)]


def test_code_outside_any_fragment_is_a_warning_not_silently_dropped(tmp_path: Path) -> None:
    _, model = _model(tmp_path, "-- @number g\n\nx = 1\n\n" + _FRAGMENT)

    [warning] = [d for d in model.diagnostics if d.code == "loose-code"]
    assert (warning.severity, warning.line) == ("warning", 3)


def test_comments_and_annotations_before_the_first_fragment_are_not_loose_code(tmp_path: Path) -> None:
    _, model = _model(tmp_path, "-- a comment\n-- @number g\n-- @doc about it\n\n" + _FRAGMENT)

    assert model.diagnostics == []


def test_a_block_files_code_is_kept_whole(tmp_path: Path) -> None:
    _, model = _model(tmp_path, _FRAGMENT, blocks={"setup": "-- @block SETUP\non init: do\n   x = 1\nend\n"})

    block = model.blocks["SETUP"]
    assert block.file == "blocks/setup.mgl" and block.lines[1] == "on init: do"


def test_a_fragment_in_a_block_file_is_reported(tmp_path: Path) -> None:
    _, model = _model(tmp_path, _FRAGMENT, blocks={"setup": "-- @fragment SETUP.x\n-- @loop player\nx = 1\n"})

    assert ("fragment-in-block", "blocks/setup.mgl", 1) in [(d.code, d.file, d.line) for d in model.diagnostics]


def test_declarations_are_collected_with_their_owner(tmp_path: Path) -> None:
    _, model = _model(
        tmp_path,
        '-- @pnumber p_x\n-- @bitfield thing.flags { a, b }\n-- @trait t_a { x = 1 }\n-- @label L_a = "a"\n' + _FRAGMENT,
        blocks={"setup": "-- @number g_y\n"},
    )

    assert sorted((d.annotation.name, d.owner) for d in model.storage) == [("g_y", "blocks/setup.mgl"), ("p_x", "module m")]
    assert [d.annotation.name for d in model.bitfields] == ["flags"]
    assert sorted(d.annotation.name for d in model.resources) == ["L_a", "t_a"]


# -- IR005 / IR006 / IR007 / IR010 / IR011 / IR016 ------------------------------------------------------


def test_ir007_true_and_false_are_not_values(tmp_path: Path) -> None:
    found = _lint(tmp_path, "-- @fragment PASS.f\n-- @loop player\nx = 1\ny = true\nif z == false then\n   x = 2\nend\n")

    assert _at(found, "IR007") == [("modules/m/m.mgl", 4), ("modules/m/m.mgl", 5)]
    assert found[0].hint == "use 1 or 0"


def test_ir007_in_a_block_file_uses_the_files_own_line_numbers(tmp_path: Path) -> None:
    found = _lint(tmp_path, _FRAGMENT, blocks={"setup": "-- @block SETUP\n\nx = true\n"})

    assert _at(found, "IR007") == [("blocks/setup.mgl", 3)]


def test_ir005_a_timer_declared_with_a_network_priority(tmp_path: Path) -> None:
    found = _lint(tmp_path, _FRAGMENT, blocks={"setup": "declare global.timer[0] with network priority low\n"})

    assert _at(found, "IR005") == [("blocks/setup.mgl", 1)]


def test_a_timer_with_no_priority_and_a_number_with_one_are_fine(tmp_path: Path) -> None:
    found = _lint(tmp_path, _FRAGMENT, blocks={"setup": "declare global.timer[0] = 5\ndeclare global.number[0] with network priority low\n"})

    assert found == []


def test_ir006_a_name_declared_twice_across_modules_and_blocks(tmp_path: Path) -> None:
    found = _lint(tmp_path, "-- @pnumber score\n" + _FRAGMENT, blocks={"setup": "-- @number score\n"})

    [dup] = [d for d in found if d.code == "IR006"]
    assert dup.file == "modules/m/m.mgl" or dup.file == "blocks/setup.mgl"
    assert "already declared at" in dup.message and dup.hint


def test_ir006_names_share_one_space_across_storage_and_resources(tmp_path: Path) -> None:
    found = _lint(tmp_path, '-- @number t_a\n-- @trait t_a { x = 1 }\n' + _FRAGMENT)

    assert len(_at(found, "IR006")) == 1


def test_ir006_a_preambles_provided_name_cannot_reuse_a_declared_one(tmp_path: Path) -> None:
    found = _lint(tmp_path, "-- @number g_x\n-- @preamble ctx\n-- @provides g_x:number\nx = 1\n\n" + _FRAGMENT)

    assert len(_at(found, "IR006")) == 1


def test_ir006_the_same_declare_slot_twice(tmp_path: Path) -> None:
    found = _lint(tmp_path, _FRAGMENT, blocks={"setup": "declare global.number[0]\nx = 1\ndeclare global.number[0] with network priority low\n"})

    assert _at(found, "IR006") == [("blocks/setup.mgl", 3)]


def test_ir010_an_unlabelled_for_each_object_in_a_tick(tmp_path: Path) -> None:
    found = _lint(tmp_path, _FRAGMENT, blocks={"win": "for each object do\n   x = 1\nend\n"})

    assert _at(found, "IR010") == [("blocks/win.mgl", 1)]


def test_ir010_not_in_an_event_and_not_when_labelled(tmp_path: Path) -> None:
    found = _lint(
        tmp_path, _FRAGMENT,
        blocks={"win": "on init: for each object do\n   x = 1\nend\nfor each object with label 2 do\n   x = 1\nend\n"},
    )

    assert _at(found, "IR010") == []


def test_ir010_inside_a_fragment_at_its_file_line(tmp_path: Path) -> None:
    found = _lint(tmp_path, "-- @fragment PASS.f\n-- @loop player\n\nfor each object do\n   x = 1\nend\n")

    assert _at(found, "IR010") == [("modules/m/m.mgl", 4)]


def test_ir010_a_fragment_that_loops_over_every_object(tmp_path: Path) -> None:
    found = _lint(tmp_path, "-- @fragment PASS.f\n-- @loop object\nx = 1\n")

    assert _at(found, "IR010") == [("modules/m/m.mgl", 1)]


def test_ir011_a_bitfield_of_sixteen_flags(tmp_path: Path) -> None:
    flags = ", ".join(f"f{i}" for i in range(16))

    found = _lint(tmp_path, f"-- @bitfield thing.flags {{ {flags} }}\n" + _FRAGMENT)

    assert _at(found, "IR011") == [("modules/m/m.mgl", 1)]
    assert "16 flags" in found[0].message


def test_fifteen_flags_are_fine(tmp_path: Path) -> None:
    flags = ", ".join(f"f{i}" for i in range(15))

    assert _at(_lint(tmp_path, f"-- @bitfield thing.flags {{ {flags} }}\n" + _FRAGMENT), "IR011") == []


def test_ir016_assuming_a_block_that_runs_later(tmp_path: Path) -> None:
    found = _lint(tmp_path, "-- @fragment PASS.f\n-- @loop player\n-- @assumes SETUP\nx = 1\n", blocks={"setup": "x = 1\n"})
    assert _at(found, "IR016") == []  # SETUP is before PASS: satisfied

    found = _lint(tmp_path / "b", "-- @fragment SETUP.f\n-- @loop player\n-- @assumes PASS\nx = 1\n", blocks={"setup": "x = 1\n"})
    assert _at(found, "IR016") == [("modules/m/m.mgl", 3)]
    assert "position" in found[-1].message


def test_ir016_assuming_a_block_that_does_not_exist(tmp_path: Path) -> None:
    found = _lint(tmp_path, "-- @fragment PASS.f\n-- @loop player\n-- @assumes NOWHERE\nx = 1\n")

    assert _at(found, "IR016") == [("modules/m/m.mgl", 3)]


def test_ir016_in_a_block_file(tmp_path: Path) -> None:
    found = _lint(tmp_path, _FRAGMENT, blocks={"setup": "-- @assumes PASS\nx = 1\n"})

    assert _at(found, "IR016") == [("blocks/setup.mgl", 1)]


def test_object_storage_needs_a_declared_kind(tmp_path: Path) -> None:
    found = _lint(tmp_path, "-- @onumber thing.hp\n-- @onumber ghost.hp2\n" + _FRAGMENT)

    assert _at(found, "kind-unknown") == [("modules/m/m.mgl", 2)]


def test_a_bitfield_needs_a_declared_kind(tmp_path: Path) -> None:
    assert _at(_lint(tmp_path, "-- @bitfield ghost.flags { a }\n" + _FRAGMENT), "kind-unknown") == [("modules/m/m.mgl", 1)]


@pytest.mark.parametrize(("owner", "ok"), [("team0", True), ("team7", True), ("team8", False), ("teams", False), ("blue", False)])
def test_team_storage_needs_a_team_owner(tmp_path: Path, owner: str, ok: bool) -> None:
    found = _lint(tmp_path, f"-- @tnumber {owner}.tally\n" + _FRAGMENT)

    assert (_at(found, "team-owner-invalid") == []) is ok


def test_a_body_that_does_not_parse_is_reported_once_at_its_line(tmp_path: Path) -> None:
    found = _lint(tmp_path, "-- @fragment PASS.f\n-- @loop player\nx = 1\ny = = 2\n")

    assert _at(found, "body-syntax") == [("modules/m/m.mgl", 4)]
    assert "fragment m.f" in found[0].hint


def test_a_clean_project_has_no_findings(tmp_path: Path) -> None:
    found = _lint(
        tmp_path,
        "-- @pnumber p_x\n-- @onumber thing.hp\n\n-- @fragment PASS.f\n-- @loop player\ncurrent_player.p_x += 1\n",
        blocks={"setup": "-- @block SETUP\non init: do\n   global.number[0] = 1\nend\n"},
    )

    assert found == []


def test_a_diagnostic_with_a_hint_prints_it() -> None:
    from in_reach.app.script_project import ProjectDiagnostic

    text = str(ProjectDiagnostic(severity="error", code="IR007", message="m", file="a.mgl", line=2, hint="use 1 or 0"))

    assert text == "a.mgl:2: error: m [IR007] -- use 1 or 0"


# -- false positives found on real, decompiled scripts ---------------------------------------------------------------------


def test_ir007_leaves_a_yes_no_argument_alone(tmp_path: Path) -> None:
    """The decompiler writes ``current_object.set_hidden(true)`` and the compiler takes it: it isn't a value."""
    found = _lint(
        tmp_path,
        "-- @fragment PASS.f\n-- @loop player\ncurrent_object.set_hidden(true)\nscript_widget[0].set_visibility(current_player, false)\n",
    )

    assert _at(found, "IR007") == []


def test_ir007_still_flags_true_as_a_value_next_to_an_argument(tmp_path: Path) -> None:
    text = "-- @fragment PASS.f\n-- @loop player\nf(true)\nx = true\nif y == true then\n   z = 1\nend\nif true then\n   z = 2\nend\n"

    found = _lint(tmp_path, text)

    assert _at(found, "IR007") == [("modules/m/m.mgl", 4), ("modules/m/m.mgl", 5), ("modules/m/m.mgl", 8)]


def test_ir007_flags_true_inside_an_expression_that_is_an_argument(tmp_path: Path) -> None:
    found = _lint(tmp_path, "-- @fragment PASS.f\n-- @loop player\nf(x == true)\n")

    assert _at(found, "IR007") == [("modules/m/m.mgl", 3)]  # only a *bare* true/false is the yes/no argument


def test_ir010_is_a_warning_because_the_compiler_accepts_it_and_shipped_scripts_do_it(tmp_path: Path) -> None:
    found = _lint(tmp_path, _FRAGMENT, blocks={"win": "for each object do\n   x = 1\nend\n"})

    assert [(d.code, d.severity) for d in found if d.code == "IR010"] == [("IR010", "warning")]


def test_the_loop_object_form_of_ir010_is_a_warning_too(tmp_path: Path) -> None:
    found = _lint(tmp_path, "-- @fragment PASS.f\n-- @loop object\nx = 1\n")

    assert [(d.code, d.severity) for d in found if d.code == "IR010"] == [("IR010", "warning")]


def test_ir007_and_the_other_errors_are_still_errors(tmp_path: Path) -> None:
    found = _lint(tmp_path, "-- @fragment PASS.f\n-- @loop player\nx = true\n")

    assert [d.severity for d in found if d.code == "IR007"] == ["error"]
