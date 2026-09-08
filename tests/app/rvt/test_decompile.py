import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from in_reach.app.rvt import decompile
from in_reach.app.rvt.models.game_settings import GameSettings, Meta, Multiplayer
from in_reach.app.rvt.models.script_settings import ScriptedOption, ScriptSettings

_FIXTURES_DIR = Path(__file__).parent / "resources"


class _FakeMultiplayer:
    def get_full_size_data(self):
        return _FakeSizeData()


class _FakeSizeData:
    bits = {
        "maximum": 100, "header": 1, "header_strings": 1, "cg_options": 1, "team_config": 1,
        "script_traits": 1, "script_options": 1, "script_strings": 1, "option_toggles": 1,
        "rating_params": 1, "map_perms": 1, "script_content": 1, "script_stats": 1,
        "script_widgets": 1, "forge_labels": 1, "title_update_1": 1,
    }
    counts = {
        "triggers": 0, "conditions": 0, "actions": 0, "forge_labels": 0, "strings": 0,
        "script_options": 0, "script_stats": 0, "script_traits": 0, "script_widgets": 0,
    }

    def total_bits(self) -> int:
        return sum(v for k, v in self.bits.items() if k != "maximum")


class _FakeVariant:
    def __init__(self, multiplayer) -> None:
        self.multiplayer = multiplayer

    def decompile_script(self) -> str:
        return "-- script --"


def _game_settings(*, multiplayer: bool = True, scripted_options=None) -> GameSettings:
    settings = GameSettings(
        meta=Meta(is_multiplayer=multiplayer, source_file="x.bin", generated_at=datetime.now(timezone.utc))
    )
    if multiplayer and scripted_options is not None:
        settings.multiplayer = Multiplayer(script_settings=ScriptSettings(scripted_options=scripted_options))
    return settings


def _patch(monkeypatch, variant, settings) -> None:
    monkeypatch.setattr(decompile, "get_rvt", lambda: type("Rvt", (), {"load": staticmethod(lambda path: variant)})())
    monkeypatch.setattr(decompile, "extract_game_settings", lambda v, path: settings)
    monkeypatch.setattr(decompile.strings_io, "extract_strings", lambda mp: {"meta": {}, "teams": [], "script_strings": []})


def test_decompile_into_project_writes_settings_strings_and_script(
    tmp_path: Path, monkeypatch
) -> None:
    option = ScriptedOption(name="Round Length")
    settings = _game_settings(scripted_options=[option])
    variant = _FakeVariant(_FakeMultiplayer())
    _patch(monkeypatch, variant, settings)

    bin_path = tmp_path / "source.bin"
    bin_path.write_bytes(b"\x00")
    folder = tmp_path / "project"
    folder.mkdir()

    decompile.decompile_into_project(bin_path, folder)

    settings_dir = folder / "settings"
    rvt_dir = folder / "edit" / "rvt"
    assert (settings_dir / decompile.SETTINGS_FILENAME).is_file()
    assert (settings_dir / decompile.SCRIPT_SETTINGS_FILENAME).is_file()
    assert (settings_dir / decompile.STRINGS_FILENAME).is_file()
    assert (rvt_dir / decompile.SCRIPT_FILENAME).read_text(encoding="utf-8") == "-- script --"

    script_settings_json = json.loads((settings_dir / decompile.SCRIPT_SETTINGS_FILENAME).read_text(encoding="utf-8"))
    assert script_settings_json["scripted_options"][0]["name"] == "Round Length"


def test_decompile_into_project_also_writes_the_build_generated_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    # PROMPT.md: ".generated.json files [should] be created when the project is started" -- not
    # just settings/, build/ too, from the same decompile pass.
    settings = _game_settings()
    variant = _FakeVariant(_FakeMultiplayer())
    _patch(monkeypatch, variant, settings)

    bin_path = tmp_path / "source.bin"
    bin_path.write_bytes(b"\x00")
    folder = tmp_path / "project"
    folder.mkdir()

    decompile.decompile_into_project(bin_path, folder)

    build_dir = folder / "build"
    assert (build_dir / decompile.GENERATED_SETTINGS_FILENAME).is_file()
    assert (build_dir / decompile.GENERATED_SCRIPT_SETTINGS_FILENAME).is_file()
    assert (build_dir / decompile.GENERATED_STRINGS_FILENAME).is_file()
    assert (build_dir / decompile.GENERATED_STATS_FILENAME).is_file()
    # valid_maps.json is a settings/-only concept -- build/'s own snapshot doesn't get one.
    assert not (build_dir / "valid_maps.json").exists()


def test_decompile_into_project_writes_valid_maps_json_filtered_by_script_settings(
    tmp_path: Path, monkeypatch
) -> None:
    from in_reach.app.maps_io import MapEntry
    from in_reach.app.rvt.models.enums import MapPermissionType
    from in_reach.app.rvt.models.script_settings import MapPermissions

    settings = _game_settings()
    settings.multiplayer.script_settings.map_permissions = MapPermissions(
        type=MapPermissionType.only_these_maps, map_ids=[42]
    )
    variant = _FakeVariant(_FakeMultiplayer())
    _patch(monkeypatch, variant, settings)

    bin_path = tmp_path / "source.bin"
    bin_path.write_bytes(b"\x00")
    folder = tmp_path / "project"
    folder.mkdir()
    allowed = MapEntry(filename="a.mvar", source="personal", title="A", description="", map_id=42, base_canvas_map=None)
    excluded = MapEntry(filename="b.mvar", source="personal", title="B", description="", map_id=7, base_canvas_map=None)

    decompile.decompile_into_project(bin_path, folder, map_entries=[allowed, excluded])

    valid_maps = json.loads((folder / "settings" / "valid_maps.json").read_text(encoding="utf-8"))
    assert [m["title"] for m in valid_maps["maps"]] == ["A"]


def test_resync_from_bin_updates_settings_and_build_without_touching_edit(tmp_path: Path, monkeypatch) -> None:
    # PROMPT.md: "[generated files] should update when rvt saves" -- but edit/rvt/script.txt is the
    # one hand-editable thing left, so a resync must never overwrite it.
    settings = _game_settings()
    variant = _FakeVariant(_FakeMultiplayer())
    _patch(monkeypatch, variant, settings)

    bin_path = tmp_path / "source.bin"
    bin_path.write_bytes(b"\x00")
    folder = tmp_path / "project"
    folder.mkdir()
    rvt_dir = folder / "edit" / "rvt"
    rvt_dir.mkdir(parents=True)
    (rvt_dir / decompile.SCRIPT_FILENAME).write_text("hand-edited script", encoding="utf-8")

    decompile.resync_from_bin(bin_path, folder)

    assert (folder / "build" / decompile.GENERATED_SETTINGS_FILENAME).is_file()
    assert (folder / "settings" / decompile.SETTINGS_FILENAME).is_file()
    assert (rvt_dir / decompile.SCRIPT_FILENAME).read_text(encoding="utf-8") == "hand-edited script"


def test_resync_from_bin_carries_category_through(tmp_path: Path, monkeypatch) -> None:
    from in_reach.app.categories import EngineCategory, EngineIcon

    settings = _game_settings()
    variant = _FakeVariant(_FakeMultiplayer())
    _patch(monkeypatch, variant, settings)

    bin_path = tmp_path / "source.bin"
    bin_path.write_bytes(b"\x00")
    folder = tmp_path / "project"
    folder.mkdir()

    decompile.resync_from_bin(
        bin_path, folder, category=EngineCategory.juggernaut, category_icon=EngineIcon.juggernaut
    )

    document = json.loads((folder / "build" / decompile.GENERATED_SETTINGS_FILENAME).read_text(encoding="utf-8"))
    assert document["meta"]["category"] == "juggernaut"
    assert document["meta"]["category_icon"] == "juggernaut"


def test_decompile_into_project_stamps_category_and_icon_into_settings_json(
    tmp_path: Path, monkeypatch
) -> None:
    from in_reach.app.categories import EngineCategory, EngineIcon

    settings = _game_settings()
    variant = _FakeVariant(_FakeMultiplayer())
    _patch(monkeypatch, variant, settings)

    bin_path = tmp_path / "source.bin"
    bin_path.write_bytes(b"\x00")
    folder = tmp_path / "project"
    folder.mkdir()

    decompile.decompile_into_project(
        bin_path, folder, category=EngineCategory.juggernaut, category_icon=EngineIcon.juggernaut
    )

    settings_json = json.loads((folder / "settings" / decompile.SETTINGS_FILENAME).read_text(encoding="utf-8"))
    assert settings_json["meta"]["category"] == "juggernaut"
    assert settings_json["meta"]["category_icon"] == "juggernaut"


def test_decompile_into_project_defaults_to_no_category(tmp_path: Path, monkeypatch) -> None:
    settings = _game_settings()
    variant = _FakeVariant(_FakeMultiplayer())
    _patch(monkeypatch, variant, settings)

    bin_path = tmp_path / "source.bin"
    bin_path.write_bytes(b"\x00")
    folder = tmp_path / "project"
    folder.mkdir()

    decompile.decompile_into_project(bin_path, folder)

    settings_json = json.loads((folder / "settings" / decompile.SETTINGS_FILENAME).read_text(encoding="utf-8"))
    assert settings_json["meta"]["category"] == "none"
    assert settings_json["meta"]["category_icon"] is None


def test_decompile_into_project_handles_non_multiplayer_variants(tmp_path: Path, monkeypatch) -> None:
    settings = _game_settings(multiplayer=False)
    variant = _FakeVariant(None)
    _patch(monkeypatch, variant, settings)

    bin_path = tmp_path / "source.bin"
    bin_path.write_bytes(b"\x00")
    folder = tmp_path / "project"
    folder.mkdir()

    decompile.decompile_into_project(bin_path, folder)

    script_settings_json = json.loads(
        (folder / "settings" / decompile.SCRIPT_SETTINGS_FILENAME).read_text(encoding="utf-8")
    )
    # No multiplayer settings, so script_settings falls back to a bare default -- no scripted
    # options rather than raising on the missing multiplayer.script_settings.
    assert script_settings_json["scripted_options"] == []
    # No multiplayer -- no build stats to report, so no stats file at all.
    assert not (folder / "build" / decompile.GENERATED_STATS_FILENAME).exists()


@pytest.mark.skipif(not (_FIXTURES_DIR / "juggernaut" / "juggernaut.bin").is_file(), reason="fixture .bin not present")
def test_decompile_into_project_against_a_real_bin(tmp_path: Path) -> None:
    """End-to-end against a real Reach .bin fixture (a saved Juggernaut variant) -- exercises the
    actual bundled native extension, not fakes."""
    folder = tmp_path / "project"
    folder.mkdir()

    decompile.decompile_into_project(_FIXTURES_DIR / "juggernaut" / "juggernaut.bin", folder)

    settings_dir = folder / "settings"
    settings = json.loads((settings_dir / decompile.SETTINGS_FILENAME).read_text(encoding="utf-8"))
    assert settings["meta"]["is_multiplayer"] is True
    assert settings["meta"]["title"]

    strings = json.loads((settings_dir / decompile.STRINGS_FILENAME).read_text(encoding="utf-8"))
    assert set(strings.keys()) == {"meta", "teams", "script_strings"}

    script = (folder / "edit" / "rvt" / decompile.SCRIPT_FILENAME).read_text(encoding="utf-8")
    assert "declare" in script

    stats = json.loads((folder / "build" / decompile.GENERATED_STATS_FILENAME).read_text(encoding="utf-8"))
    assert stats["space"]["bytes_used"] > 0
