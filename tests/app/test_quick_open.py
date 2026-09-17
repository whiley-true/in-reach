from pathlib import Path

from in_reach.app import quick_open


def test_list_project_files_returns_every_file_sorted_by_relative_path(tmp_path: Path) -> None:
    (tmp_path / "settings").mkdir()
    (tmp_path / "settings" / "settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "script").mkdir()
    (tmp_path / "script" / "output.txt").write_text("", encoding="utf-8")
    (tmp_path / "Notes.txt").write_text("", encoding="utf-8")

    files = quick_open.list_project_files(tmp_path)

    assert [p.relative_to(tmp_path) for p in files] == [
        Path("Notes.txt"),
        Path("script") / "output.txt",
        Path("settings") / "settings.json",
    ]


def test_list_project_files_excludes_directories(tmp_path: Path) -> None:
    (tmp_path / "empty_dir").mkdir()
    (tmp_path / "file.txt").write_text("", encoding="utf-8")

    files = quick_open.list_project_files(tmp_path)

    assert files == [tmp_path / "file.txt"]


def test_list_project_files_for_a_nonexistent_folder_is_empty(tmp_path: Path) -> None:
    assert quick_open.list_project_files(tmp_path / "does-not-exist") == []


def test_list_project_files_excludes_the_vcs_history_folder(tmp_path: Path) -> None:
    # PROMPT.md: "in the top search bar do not include files in history - otherwise it gets too
    # long" -- every VCS snapshot lives under .in-reach/history as loose git objects, which would
    # otherwise vastly outnumber a project's own real files.
    (tmp_path / "settings").mkdir()
    (tmp_path / "settings" / "settings.json").write_text("{}", encoding="utf-8")
    history_objects = tmp_path / ".in-reach" / "history" / "objects" / "ab"
    history_objects.mkdir(parents=True)
    (history_objects / "cdef0123456789").write_text("", encoding="utf-8")
    (tmp_path / ".in-reach" / "history" / "HEAD").write_text("", encoding="utf-8")

    files = quick_open.list_project_files(tmp_path)

    assert files == [tmp_path / "settings" / "settings.json"]


def test_filter_files_matches_on_relative_path_case_insensitively(tmp_path: Path) -> None:
    (tmp_path / "settings").mkdir()
    settings_json = tmp_path / "settings" / "settings.json"
    settings_json.write_text("{}", encoding="utf-8")
    strings_json = tmp_path / "settings" / "strings.json"
    strings_json.write_text("{}", encoding="utf-8")
    files = [settings_json, strings_json]

    assert quick_open.filter_files(files, "SETTINGS.JSON", root=tmp_path) == [settings_json]


def test_filter_files_with_an_empty_query_returns_everything(tmp_path: Path) -> None:
    files = [tmp_path / "a.txt", tmp_path / "b.txt"]

    assert quick_open.filter_files(files, "", root=tmp_path) == files


def test_filter_files_preserves_input_order(tmp_path: Path) -> None:
    a = tmp_path / "aaa_match.txt"
    b = tmp_path / "bbb_match.txt"

    assert quick_open.filter_files([b, a], "match", root=tmp_path) == [b, a]
