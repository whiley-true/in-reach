from pathlib import Path

from in_reach.app import project_search


def test_search_project_finds_matches_across_multiple_files(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello world\nsecond line\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("# Title\nworld peace\n", encoding="utf-8")

    matches = project_search.search_project(tmp_path, "world")

    assert len(matches) == 2
    assert {m.path.name for m in matches} == {"a.txt", "b.md"}
    assert matches[0].line_number == 1


def test_search_project_is_case_insensitive_by_default(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("Hello World\n", encoding="utf-8")

    matches = project_search.search_project(tmp_path, "hello world")

    assert len(matches) == 1


def test_search_project_case_sensitive_excludes_a_different_case_match(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("Hello World\n", encoding="utf-8")

    matches = project_search.search_project(tmp_path, "hello world", case_sensitive=True)

    assert matches == []


def test_search_project_records_line_number_and_column(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("one\ntwo needle three\n", encoding="utf-8")

    matches = project_search.search_project(tmp_path, "needle")

    assert len(matches) == 1
    assert matches[0].line_number == 2
    assert matches[0].column == 4
    assert matches[0].line_text == "two needle three"


def test_search_project_only_one_entry_per_line_with_multiple_matches(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("cat cat cat\n", encoding="utf-8")

    matches = project_search.search_project(tmp_path, "cat")

    assert len(matches) == 1


def test_search_project_skips_files_that_are_not_valid_utf8(tmp_path: Path) -> None:
    (tmp_path / "binary.bin").write_bytes(b"\xff\xfe\x00needle\x00")
    (tmp_path / "text.txt").write_text("needle here\n", encoding="utf-8")

    matches = project_search.search_project(tmp_path, "needle")

    assert [m.path.name for m in matches] == ["text.txt"]


def test_search_project_recurses_into_subfolders(tmp_path: Path) -> None:
    nested = tmp_path / "script"
    nested.mkdir(parents=True)
    (nested / "output.txt").write_text("needle in a haystack\n", encoding="utf-8")

    matches = project_search.search_project(tmp_path, "needle")

    assert len(matches) == 1
    assert matches[0].path == nested / "output.txt"


def test_search_project_empty_query_returns_nothing(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("anything\n", encoding="utf-8")

    assert project_search.search_project(tmp_path, "") == []


def test_search_project_missing_root_returns_nothing(tmp_path: Path) -> None:
    assert project_search.search_project(tmp_path / "nope", "x") == []


# -- replace_in_project ---------------------------------------------------------------------------


def test_replace_in_project_rewrites_every_matching_file(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello world\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("world of hello\n", encoding="utf-8")
    (tmp_path / "c.txt").write_text("nothing here\n", encoding="utf-8")

    changed = project_search.replace_in_project(tmp_path, "hello", "goodbye")

    assert changed == 2
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "goodbye world\n"
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "world of goodbye\n"
    assert (tmp_path / "c.txt").read_text(encoding="utf-8") == "nothing here\n"


def test_replace_in_project_preserves_original_casing_is_not_attempted(tmp_path: Path) -> None:
    # Case-insensitive replace substitutes the literal replacement text regardless of how the
    # original match was cased -- no attempt to "match" the found casing.
    (tmp_path / "a.txt").write_text("Hello hello HELLO\n", encoding="utf-8")

    project_search.replace_in_project(tmp_path, "hello", "bye")

    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "bye bye bye\n"


def test_replace_in_project_case_sensitive_only_touches_exact_case(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("Hello hello\n", encoding="utf-8")

    project_search.replace_in_project(tmp_path, "hello", "bye", case_sensitive=True)

    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "Hello bye\n"


def test_replace_in_project_does_not_touch_a_file_with_no_match(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("nothing to see\n", encoding="utf-8")
    before = path.stat().st_mtime

    changed = project_search.replace_in_project(tmp_path, "needle", "found")

    assert changed == 0
    assert path.stat().st_mtime == before


def test_replace_in_project_empty_query_is_a_no_op(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("anything\n", encoding="utf-8")

    assert project_search.replace_in_project(tmp_path, "", "x") == 0
