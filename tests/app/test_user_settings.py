import json
from pathlib import Path

from in_reach.app import user_settings
from in_reach.app.categories import EngineCategory, EngineIcon


def test_write_user_settings_writes_title_description_category_and_icon(tmp_path: Path) -> None:
    path = tmp_path / "user_settings.json"

    warning = user_settings.write_user_settings(
        path, "Slayer Plus", "A better slayer", EngineCategory.slayer, EngineIcon.slayer
    )

    assert warning is None
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["title"] == "Slayer Plus"
    assert document["description"] == "A better slayer"
    assert document["category"] == "slayer"
    assert document["category_icon"] == "slayer"


def test_write_user_settings_still_writes_the_file_when_mismatched(tmp_path: Path) -> None:
    path = tmp_path / "user_settings.json"

    warning = user_settings.write_user_settings(
        path, "Odd Slayer", "", EngineCategory.slayer, EngineIcon.oddball
    )

    assert warning is not None
    assert path.is_file()
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["category_icon"] == "oddball"


def test_write_user_settings_creates_parent_directories(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "folder" / "user_settings.json"

    user_settings.write_user_settings(path, "T", "", EngineCategory.none, EngineIcon.capture_the_flag)

    assert path.is_file()
