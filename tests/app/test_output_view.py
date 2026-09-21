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


# -- the active environment profile is applied, so the view shows what actually gets compiled ---------------


def _project_with_profile(tmp_path: Path, script: str, env: str = "FLAGS=DEV\nSCORE=5\n") -> None:
    (tmp_path / "script" / "env").mkdir(parents=True)
    (tmp_path / "script" / "output.txt").write_text(script, encoding="utf-8")
    (tmp_path / "script" / "env" / "dev.env").write_text(env, encoding="utf-8")
    (tmp_path / "script" / "env" / "active_profile.txt").write_text("dev\n", encoding="utf-8")


def test_the_view_shows_the_script_with_the_active_profile_applied(tmp_path: Path) -> None:
    _project_with_profile(tmp_path, "-- @if DEV\ndebug()\n-- @end\n-- @if !DEV\nrelease()\n-- @end\nwin = ${SCORE}\n")

    text = output_view.write_output_view(tmp_path).read_text(encoding="utf-8")

    assert "debug()" in text and "release()" not in text
    assert "win = 5" in text and "${SCORE}" not in text


def test_the_source_file_itself_is_never_rewritten_by_making_the_view(tmp_path: Path) -> None:
    source = "win = ${SCORE}\n"
    _project_with_profile(tmp_path, source)
    output_view.write_output_view(tmp_path)
    assert (tmp_path / "script" / "output.txt").read_text(encoding="utf-8") == source


def test_a_script_that_cannot_be_preprocessed_is_shown_as_written_with_the_reason_on_top(tmp_path: Path) -> None:
    _project_with_profile(tmp_path, "ok = 1\nwin = ${MISSING}\n")

    text = output_view.write_output_view(tmp_path).read_text(encoding="utf-8")

    assert "-- NOT PREPROCESSED (line 2): '${MISSING}' isn't defined in the 'dev' profile" in text
    assert "win = ${MISSING}" in text  # still readable, so the user can see what to fix


def test_a_broken_env_file_is_named_in_the_banner_and_the_script_shown_as_written(tmp_path: Path) -> None:
    _project_with_profile(tmp_path, "x = 1\n", env="SCORE=oops oops\n")

    text = output_view.write_output_view(tmp_path).read_text(encoding="utf-8")

    assert "-- NOT PREPROCESSED (dev.env, line 1)" in text
    assert "x = 1" in text


def test_with_no_profile_and_no_directives_the_view_is_exactly_what_it_always_was(tmp_path: Path) -> None:
    (tmp_path / "script").mkdir()
    (tmp_path / "script" / "output.txt").write_text("do stuff\n", encoding="utf-8")
    text = output_view.write_output_view(tmp_path).read_text(encoding="utf-8")
    assert text.endswith("do stuff\n") and "NOT PREPROCESSED" not in text


def test_a_linked_projects_view_is_the_linkers_script_and_writes_nothing_else(tmp_path: Path) -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).parent / "script_project"))
    from hill_project import hill_rush

    hill_rush(tmp_path)

    path = output_view.write_output_view(tmp_path)

    text = path.read_text(encoding="utf-8")
    assert text.startswith("-- in-reach build: hill_rush") and "alias g_phase = global.number[1]" in text
    assert sorted(p.name for p in (tmp_path / "build").iterdir()) == ["Compiled.txt"]  # no link map, no settings
    assert not (tmp_path / "settings").exists()


def test_a_linked_project_that_does_not_link_says_why_in_its_view(tmp_path: Path) -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).parent / "script_project"))
    from hill_project import hill_rush

    hill_rush(tmp_path, blocks__setup_dot_mgl="-- @number a\n-- @number a\n")

    text = output_view.write_output_view(tmp_path).read_text(encoding="utf-8")

    assert "-- NOT LINKED: blocks/setup.mgl:2:" in text and "[IR006]" in text
