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


# -- options: whole word / regex / preserve case / include / exclude / open editors ---------------


def test_search_project_whole_word_skips_substring_matches(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("concatenate\nthe cat sat\n", encoding="utf-8")

    matches = project_search.search_project(tmp_path, "cat", whole_word=True)

    assert [m.line_number for m in matches] == [2]


def test_search_project_regex_uses_the_query_as_a_pattern(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("cot\ncat\ncut\ncoat\n", encoding="utf-8")

    matches = project_search.search_project(tmp_path, r"c[ao]t", regex=True)

    assert [m.line_number for m in matches] == [1, 2]


def test_search_project_literal_mode_does_not_treat_the_query_as_a_pattern(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a.b\naxb\n", encoding="utf-8")

    assert [m.line_number for m in project_search.search_project(tmp_path, "a.b")] == [1]


def test_search_project_invalid_regex_matches_nothing(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("(\n", encoding="utf-8")

    assert project_search.search_project(tmp_path, "(", regex=True) == []


def test_search_project_whole_word_wraps_a_regex_alternation_as_a_unit(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("cat\ncatalog\ndog\ndogma\n", encoding="utf-8")

    matches = project_search.search_project(tmp_path, "cat|dog", regex=True, whole_word=True)

    assert [m.line_number for m in matches] == [1, 3]


def _tree(tmp_path: Path) -> None:
    (tmp_path / "settings").mkdir()
    (tmp_path / "script").mkdir()
    (tmp_path / "settings" / "settings.json").write_text('{"needle": 1}\n', encoding="utf-8")
    (tmp_path / "settings" / "strings.json").write_text('{"needle": 2}\n', encoding="utf-8")
    (tmp_path / "script" / "output.txt").write_text("needle\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("needle\n", encoding="utf-8")


def _found(matches, root: Path) -> set[str]:
    return {m.path.relative_to(root).as_posix() for m in matches}


def test_include_glob_by_extension_matches_at_any_depth(tmp_path: Path) -> None:
    _tree(tmp_path)

    found = _found(project_search.search_project(tmp_path, "needle", include="*.json"), tmp_path)

    assert found == {"settings/settings.json", "settings/strings.json"}


def test_include_accepts_a_comma_separated_list_and_a_path(tmp_path: Path) -> None:
    _tree(tmp_path)

    found = _found(project_search.search_project(tmp_path, "needle", include="*.md, script/output.txt"), tmp_path)

    assert found == {"README.md", "script/output.txt"}


def test_include_folder_path_covers_everything_beneath_it(tmp_path: Path) -> None:
    _tree(tmp_path)

    found = _found(project_search.search_project(tmp_path, "needle", include="settings"), tmp_path)

    assert found == {"settings/settings.json", "settings/strings.json"}


def test_exclude_glob_removes_matching_files(tmp_path: Path) -> None:
    _tree(tmp_path)

    found = _found(project_search.search_project(tmp_path, "needle", exclude="*.json, README.md"), tmp_path)

    assert found == {"script/output.txt"}


def test_exclude_wins_over_include(tmp_path: Path) -> None:
    _tree(tmp_path)

    found = _found(
        project_search.search_project(tmp_path, "needle", include="*.json", exclude="strings.json"), tmp_path
    )

    assert found == {"settings/settings.json"}


def test_double_star_prefix_is_accepted(tmp_path: Path) -> None:
    _tree(tmp_path)

    found = _found(project_search.search_project(tmp_path, "needle", include="**/*.json"), tmp_path)

    assert found == {"settings/settings.json", "settings/strings.json"}


def test_split_globs_trims_blanks_and_dot_slash() -> None:
    assert project_search.split_globs(" *.json , ,./src/a/file/, ") == ["*.json", "src/a/file"]


def test_only_paths_restricts_to_the_given_files(tmp_path: Path) -> None:
    _tree(tmp_path)

    found = _found(
        project_search.search_project(tmp_path, "needle", only_paths=[tmp_path / "README.md"]), tmp_path
    )

    assert found == {"README.md"}


def test_only_paths_empty_means_nothing_is_searched(tmp_path: Path) -> None:
    _tree(tmp_path)

    assert project_search.search_project(tmp_path, "needle", only_paths=[]) == []


def test_replace_honours_include_exclude_and_open_editors(tmp_path: Path) -> None:
    _tree(tmp_path)

    changed = project_search.replace_in_project(tmp_path, "needle", "pin", include="*.json", exclude="strings.json")

    assert changed == 1
    assert "pin" in (tmp_path / "settings" / "settings.json").read_text(encoding="utf-8")
    assert "needle" in (tmp_path / "settings" / "strings.json").read_text(encoding="utf-8")

    changed = project_search.replace_in_project(tmp_path, "needle", "pin", only_paths=[tmp_path / "README.md"])
    assert changed == 1
    assert "needle" in (tmp_path / "script" / "output.txt").read_text(encoding="utf-8")


def test_replace_regex_and_whole_word(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("cat concat c4t\n", encoding="utf-8")

    project_search.replace_in_project(tmp_path, r"c\dt", "dog", regex=True)
    project_search.replace_in_project(tmp_path, "cat", "cow", whole_word=True)

    assert (tmp_path / "a.txt").read_text(encoding="utf-8").strip() == "cow concat dog"


def test_replace_preserve_case_follows_each_matchs_own_casing(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("CAT Cat cat\n", encoding="utf-8")

    project_search.replace_in_project(tmp_path, "cat", "dog", keep_case=True)

    assert (tmp_path / "a.txt").read_text(encoding="utf-8").strip() == "DOG Dog dog"


def test_replace_without_preserve_case_inserts_the_replacement_verbatim(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("CAT Cat cat\n", encoding="utf-8")

    project_search.replace_in_project(tmp_path, "cat", "dog")

    assert (tmp_path / "a.txt").read_text(encoding="utf-8").strip() == "dog dog dog"


def test_replace_invalid_regex_is_a_noop(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("(\n", encoding="utf-8")

    assert project_search.replace_in_project(tmp_path, "(", "x", regex=True) == 0
