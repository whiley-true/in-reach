import json
from pathlib import Path

from in_reach.app.rvt import strings_io


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _valid_document(script_strings: list) -> dict:
    return {
        "meta": {"name": [], "description": [], "category": []},
        "teams": [],
        "script_strings": script_strings,
    }


def test_count_script_strings_counts_the_table(tmp_path: Path) -> None:
    path = tmp_path / "strings.json"
    _write(
        path,
        _valid_document(
            [
                {"index": 0, "text": "one"},
                {"index": 1, "text": "two"},
                {"index": 2, "text": "three"},
            ]
        ),
    )

    assert strings_io.count_script_strings(path) == 3


def test_count_script_strings_is_zero_for_an_empty_table(tmp_path: Path) -> None:
    path = tmp_path / "strings.json"
    _write(path, _valid_document([]))

    assert strings_io.count_script_strings(path) == 0


def test_count_script_strings_ignores_schema_and_comment_keys(tmp_path: Path) -> None:
    path = tmp_path / "strings.json"
    document = _valid_document([{"index": 0, "text": "one"}])
    document = {"$schema": "../schemas/strings.schema.json", "_comment": "do not edit", **document}
    _write(path, document)

    assert strings_io.count_script_strings(path) == 1


def test_count_script_strings_is_none_for_a_missing_file(tmp_path: Path) -> None:
    assert strings_io.count_script_strings(tmp_path / "nope.json") is None


def test_count_script_strings_is_none_for_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "strings.json"
    path.write_text("{not valid json", encoding="utf-8")

    assert strings_io.count_script_strings(path) is None


def test_count_script_strings_is_none_when_it_does_not_match_the_schema(tmp_path: Path) -> None:
    path = tmp_path / "strings.json"
    _write(path, {"meta": {"name": [], "description": [], "category": []}, "teams": []})  # missing script_strings

    assert strings_io.count_script_strings(path) is None
