from pathlib import Path

from in_reach.app import output_view


def test_output_view_path_is_under_build_dir(tmp_path: Path) -> None:
    assert output_view.output_view_path(tmp_path) == tmp_path / "build" / "Compiled.txt"


def test_write_output_view_prepends_the_banner_to_the_scripts_content(tmp_path: Path) -> None:
    (tmp_path / "script").mkdir()
    (tmp_path / "script" / "output.txt").write_text("do stuff\n", encoding="utf-8")

    path = output_view.write_output_view(tmp_path)

    assert path == tmp_path / "build" / "Compiled.txt"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("-- This file is auto-generated and non-editable")
    assert "do stuff" in text


def test_write_output_view_banner_is_split_across_two_comment_lines(tmp_path: Path) -> None:
    # PROMPT.md: "please split this [banner] over two lines".
    path = output_view.write_output_view(tmp_path)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("-- This file is auto-generated and non-editable")
    assert lines[1].startswith("--")
    assert lines[1] != lines[0]


def test_write_output_view_with_no_script_yet_still_writes_just_the_banner(tmp_path: Path) -> None:
    path = output_view.write_output_view(tmp_path)

    text = path.read_text(encoding="utf-8")
    assert text.startswith("-- This file is auto-generated and non-editable")


def test_write_output_view_creates_the_build_dir_if_missing(tmp_path: Path) -> None:
    assert not (tmp_path / "build").exists()

    output_view.write_output_view(tmp_path)

    assert (tmp_path / "build").is_dir()


def test_write_output_view_reflects_the_scripts_latest_content_on_each_call(tmp_path: Path) -> None:
    (tmp_path / "script").mkdir()
    script_path = tmp_path / "script" / "output.txt"
    script_path.write_text("v1", encoding="utf-8")
    path = output_view.write_output_view(tmp_path)
    assert "v1" in path.read_text(encoding="utf-8")

    script_path.write_text("v2", encoding="utf-8")
    output_view.write_output_view(tmp_path)

    assert "v2" in path.read_text(encoding="utf-8")
    assert "v1" not in path.read_text(encoding="utf-8")
