from datetime import datetime, timezone
from pathlib import Path

from in_reach.app.categories import EngineCategory, EngineIcon
from in_reach.app.rvt import settings_io
from in_reach.app.rvt.models.game_settings import GameSettings, Meta


def test_load_meta_category_round_trips_what_dump_game_settings_wrote(tmp_path: Path) -> None:
    settings = GameSettings(
        meta=Meta(
            source_file="x.bin",
            generated_at=datetime.now(timezone.utc),
            category=EngineCategory.juggernaut,
            category_icon=EngineIcon.juggernaut,
        )
    )
    out_path = tmp_path / "settings.json"

    settings_io.dump_game_settings(settings, out_path)

    assert settings_io.load_meta_category(out_path) == (EngineCategory.juggernaut, EngineIcon.juggernaut)


def test_load_meta_category_defaults_when_category_icon_is_absent(tmp_path: Path) -> None:
    settings = GameSettings(
        meta=Meta(source_file="x.bin", generated_at=datetime.now(timezone.utc), category=EngineCategory.slayer)
    )
    out_path = tmp_path / "settings.json"

    settings_io.dump_game_settings(settings, out_path)

    assert settings_io.load_meta_category(out_path) == (EngineCategory.slayer, None)


def test_load_meta_category_defaults_for_a_missing_file(tmp_path: Path) -> None:
    assert settings_io.load_meta_category(tmp_path / "nope.json") == (EngineCategory.none, None)


def test_load_meta_category_defaults_for_unparsable_json(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("not json", encoding="utf-8")

    assert settings_io.load_meta_category(path) == (EngineCategory.none, None)


def test_load_meta_category_defaults_for_an_unknown_category_name(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"meta": {"category": "not_a_real_category"}}', encoding="utf-8")

    assert settings_io.load_meta_category(path) == (EngineCategory.none, None)
