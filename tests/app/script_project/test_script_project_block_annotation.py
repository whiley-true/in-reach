"""``-- @block NAME`` at the top of a block file (the design's own examples start that way)."""
from pathlib import Path

import pytest

from in_reach.app.rvt.megalo_ast import parse_annotations
from in_reach.app.script_project import load_project

_PROJECT = '[blocks]\norder = ["SETUP"]\n'


def _load(tmp_path: Path, files: dict[str, str]):
    for relative, text in {"project.toml": _PROJECT, **files}.items():
        path = tmp_path / "script" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return load_project(tmp_path)


def test_a_block_annotation_names_the_block() -> None:
    result = parse_annotations("-- @block SETUP\n-- @block WIN_CHECK -- a note\n")

    assert [(a.kind, a.name) for a in result.items] == [("block", "SETUP"), ("block", "WIN_CHECK")]
    assert result.items[1].note == "a note"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("-- @block setup", "UPPER_CASE"),
        ("-- @block 9LIVES", "UPPER_CASE"),
        ("-- @block A B", "unexpected 'B'"),
        ("-- @block", "needs a block name"),
    ],
)
def test_block_annotation_problems(text: str, message: str) -> None:
    result = parse_annotations(text)

    assert result.items == [] and message in result.diagnostics[0].message


def test_a_block_file_that_says_its_own_name_is_fine(tmp_path: Path) -> None:
    project = _load(tmp_path, {"blocks/setup.mgl": "-- @block SETUP\nx = 1\n"})

    assert project.diagnostics == []


def test_a_block_annotation_that_disagrees_with_the_file_name_is_reported_at_its_line(tmp_path: Path) -> None:
    project = _load(tmp_path, {"blocks/setup.mgl": "x = 1\n-- @block WIN_CHECK\n"})

    assert [(d.code, d.file, d.line) for d in project.diagnostics] == [("block-name-mismatch", "blocks/setup.mgl", 2)]
    assert "SETUP" in project.diagnostics[0].message and "WIN_CHECK" in project.diagnostics[0].message


def test_a_block_annotation_in_a_module_file_is_reported(tmp_path: Path) -> None:
    project = _load(
        tmp_path,
        {
            "project.toml": '[[modules]]\nname = "m"\n',
            "modules/m/module.toml": '[module]\nname = "m"\n',
            "modules/m/m.mgl": "-- @block SETUP\n-- @fragment SETUP.x\n-- @loop player\nx = 1\n",
        },
    )

    assert ("block-in-module", "modules/m/m.mgl", 1) in [(d.code, d.file, d.line) for d in project.diagnostics]
