import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from in_reach.app.rvt import decompile, rvt_bridge
from in_reach.app.rvt.models.game_settings import GameSettings, Meta, Multiplayer
from in_reach.app.rvt.models.script_settings import ScriptedOption, ScriptSettings

_FIXTURES_DIR = Path(__file__).parent / "resources"
_JUGGERNAUT_BIN = _FIXTURES_DIR / "juggernaut" / "juggernaut.bin"


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
    script_dir = folder / "script"
    assert (settings_dir / decompile.SETTINGS_FILENAME).is_file()
    assert (settings_dir / decompile.SCRIPT_SETTINGS_FILENAME).is_file()
    assert (settings_dir / decompile.STRINGS_FILENAME).is_file()
    assert (script_dir / decompile.SCRIPT_FILENAME).read_text(encoding="utf-8") == "-- script --"

    script_settings_json = json.loads((settings_dir / decompile.SCRIPT_SETTINGS_FILENAME).read_text(encoding="utf-8"))
    assert script_settings_json["scripted_options"][0]["name"] == "Round Length"


def test_decompile_into_project_normalizes_crlf_script_text(tmp_path: Path, monkeypatch) -> None:
    # decompile_script() itself returns "\r\n"-terminated lines (confirmed against the real native
    # extension) -- Path.write_text()'s own default text-mode translation (every "\n" -> os.linesep)
    # would otherwise double each one to "\r\r\n" on Windows, which reads back as two lines: a blank
    # line after every real one (PROMPT.md: "when it is generated it is has alternating blanks
    # lines"). Regression guard: the file on disk must read back with no such doubling regardless
    # of what line ending the native decompiler used.
    settings = _game_settings()
    variant = _FakeVariant(_FakeMultiplayer())
    variant.decompile_script = lambda: "declare x\r\n\r\nfor each player do\r\n   x = 1\r\nend\r\n"
    _patch(monkeypatch, variant, settings)

    bin_path = tmp_path / "source.bin"
    bin_path.write_bytes(b"\x00")
    folder = tmp_path / "project"
    folder.mkdir()

    decompile.decompile_into_project(bin_path, folder)

    script_text = (folder / "script" / decompile.SCRIPT_FILENAME).read_text(encoding="utf-8")
    assert script_text == "declare x\n\nfor each player do\n   x = 1\nend\n"


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


def test_decompile_into_project_writes_schema_files_at_the_project_root(
    tmp_path: Path, monkeypatch
) -> None:
    # PROMPT.md: "in settings, please not[e] examples from repo v2 ... where we have a schema,
    # please re-add this to the top of the files"; later: "move settings/schemas into schemas" --
    # a project-root schemas/ folder, not nested under settings/; build/ (disposable, autogenerated
    # output) doesn't need one either way.
    settings = _game_settings()
    variant = _FakeVariant(_FakeMultiplayer())
    _patch(monkeypatch, variant, settings)

    bin_path = tmp_path / "source.bin"
    bin_path.write_bytes(b"\x00")
    folder = tmp_path / "project"
    folder.mkdir()

    decompile.decompile_into_project(bin_path, folder)

    schema_dir = folder / "schemas"
    assert (schema_dir / decompile.SETTINGS_SCHEMA_FILENAME).is_file()
    assert (schema_dir / decompile.SCRIPT_SETTINGS_SCHEMA_FILENAME).is_file()
    assert (schema_dir / decompile.STRINGS_SCHEMA_FILENAME).is_file()
    assert not (folder / "settings" / "schemas").exists()
    assert not (folder / "settings" / "schema").exists()
    assert not (folder / "build" / "schemas").exists()


def test_decompile_into_project_embeds_a_relative_schema_reference(tmp_path: Path, monkeypatch) -> None:
    settings = _game_settings()
    variant = _FakeVariant(_FakeMultiplayer())
    _patch(monkeypatch, variant, settings)

    bin_path = tmp_path / "source.bin"
    bin_path.write_bytes(b"\x00")
    folder = tmp_path / "project"
    folder.mkdir()

    decompile.decompile_into_project(bin_path, folder)

    settings_json = json.loads((folder / "settings" / decompile.SETTINGS_FILENAME).read_text(encoding="utf-8"))
    assert settings_json["$schema"] == "../schemas/settings.schema.json"
    script_settings_json = json.loads(
        (folder / "settings" / decompile.SCRIPT_SETTINGS_FILENAME).read_text(encoding="utf-8")
    )
    assert script_settings_json["$schema"] == "../schemas/script_settings.schema.json"
    strings_json = json.loads((folder / "settings" / decompile.STRINGS_FILENAME).read_text(encoding="utf-8"))
    assert strings_json["$schema"] == "../schemas/strings.schema.json"


def test_resync_from_bin_also_regenerates_the_schema_files(tmp_path: Path, monkeypatch) -> None:
    settings = _game_settings()
    variant = _FakeVariant(_FakeMultiplayer())
    _patch(monkeypatch, variant, settings)

    bin_path = tmp_path / "source.bin"
    bin_path.write_bytes(b"\x00")
    folder = tmp_path / "project"
    folder.mkdir()

    decompile.resync_from_bin(bin_path, folder)

    assert (folder / "schemas" / decompile.SETTINGS_SCHEMA_FILENAME).is_file()


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

    # PROMPT.md: "move settings/valid_maps.json to build/valid_maps.json".
    valid_maps = json.loads((folder / "build" / "valid_maps.json").read_text(encoding="utf-8"))
    assert [m["title"] for m in valid_maps["maps"]] == ["A"]
    assert not (folder / "settings" / "valid_maps.json").exists()


def test_resync_from_bin_updates_settings_and_build_without_touching_edit(tmp_path: Path, monkeypatch) -> None:
    # PROMPT.md: "[generated files] should update when rvt saves" -- but script/output.txt is the
    # one hand-editable thing left, so a resync must never overwrite it.
    settings = _game_settings()
    variant = _FakeVariant(_FakeMultiplayer())
    _patch(monkeypatch, variant, settings)

    bin_path = tmp_path / "source.bin"
    bin_path.write_bytes(b"\x00")
    folder = tmp_path / "project"
    folder.mkdir()
    script_dir = folder / "script"
    script_dir.mkdir(parents=True)
    (script_dir / decompile.SCRIPT_FILENAME).write_text("hand-edited script", encoding="utf-8")

    decompile.resync_from_bin(bin_path, folder)

    assert (folder / "build" / decompile.GENERATED_SETTINGS_FILENAME).is_file()
    assert (folder / "settings" / decompile.SETTINGS_FILENAME).is_file()
    assert (script_dir / decompile.SCRIPT_FILENAME).read_text(encoding="utf-8") == "hand-edited script"


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


def test_decompile_into_project_stamps_title_and_description_into_settings_json(
    tmp_path: Path, monkeypatch
) -> None:
    settings = _game_settings()
    variant = _FakeVariant(_FakeMultiplayer())
    _patch(monkeypatch, variant, settings)

    bin_path = tmp_path / "source.bin"
    bin_path.write_bytes(b"\x00")
    folder = tmp_path / "project"
    folder.mkdir()

    decompile.decompile_into_project(bin_path, folder, title="My Gametype", description="A test gametype")

    settings_json = json.loads((folder / "settings" / decompile.SETTINGS_FILENAME).read_text(encoding="utf-8"))
    assert settings_json["meta"]["title"] == "My Gametype"
    assert settings_json["meta"]["description"] == "A test gametype"


def test_decompile_into_project_truncates_description_to_meta_max_length(tmp_path: Path, monkeypatch) -> None:
    # Meta.description's real max_length (127) is shorter than the New Project dialog's own -- a
    # decompile shouldn't fail over a few characters this field was never going to keep anyway.
    settings = _game_settings()
    variant = _FakeVariant(_FakeMultiplayer())
    _patch(monkeypatch, variant, settings)

    bin_path = tmp_path / "source.bin"
    bin_path.write_bytes(b"\x00")
    folder = tmp_path / "project"
    folder.mkdir()

    decompile.decompile_into_project(bin_path, folder, description="x" * 200)

    settings_json = json.loads((folder / "settings" / decompile.SETTINGS_FILENAME).read_text(encoding="utf-8"))
    assert settings_json["meta"]["description"] == "x" * 127


def test_resync_from_bin_carries_title_and_description_through(tmp_path: Path, monkeypatch) -> None:
    settings = _game_settings()
    variant = _FakeVariant(_FakeMultiplayer())
    _patch(monkeypatch, variant, settings)

    bin_path = tmp_path / "source.bin"
    bin_path.write_bytes(b"\x00")
    folder = tmp_path / "project"
    folder.mkdir()

    decompile.resync_from_bin(bin_path, folder, title="Kept Title", description="Kept description")

    document = json.loads((folder / "build" / decompile.GENERATED_SETTINGS_FILENAME).read_text(encoding="utf-8"))
    assert document["meta"]["title"] == "Kept Title"
    assert document["meta"]["description"] == "Kept description"


def test_resync_from_bin_without_an_override_keeps_the_bins_own_title(tmp_path: Path, monkeypatch) -> None:
    # PROMPT.md: "when a project name is changed via rvt ... the project title should change in
    # the tabs and in the breadcrumb" -- resync_from_bin's own caller (MainWindow's .bin-watcher)
    # now leaves title/description unset so a rename typed into RVT's own header flows straight
    # through rather than being reverted to whatever settings.json said before this save.
    settings = _game_settings()
    settings.meta.title = "RVT Renamed"
    settings.meta.description = "RVT's own description"
    variant = _FakeVariant(_FakeMultiplayer())
    _patch(monkeypatch, variant, settings)

    bin_path = tmp_path / "source.bin"
    bin_path.write_bytes(b"\x00")
    folder = tmp_path / "project"
    folder.mkdir()

    decompile.resync_from_bin(bin_path, folder)

    settings_json = json.loads((folder / "settings" / decompile.SETTINGS_FILENAME).read_text(encoding="utf-8"))
    assert settings_json["meta"]["title"] == "RVT Renamed"
    assert settings_json["meta"]["description"] == "RVT's own description"


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


@pytest.mark.skipif(
    not (_JUGGERNAUT_BIN.is_file() and rvt_bridge.is_available()),
    reason="fixture .bin not present, or native _reachvarianttool extension not available on this platform",
)
def test_decompile_into_project_against_a_real_bin(tmp_path: Path) -> None:
    """End-to-end against a real Reach .bin fixture (a saved Juggernaut variant) -- exercises the
    actual bundled native extension, not fakes."""
    folder = tmp_path / "project"
    folder.mkdir()

    decompile.decompile_into_project(_JUGGERNAUT_BIN, folder, title="My Project Title")

    settings_dir = folder / "settings"
    settings = json.loads((settings_dir / decompile.SETTINGS_FILENAME).read_text(encoding="utf-8"))
    assert settings["meta"]["is_multiplayer"] is True
    # This project's own title (passed in above) overrides the .bin's own header title -- see
    # test_decompile_into_project_stamps_title_and_description_into_settings_json.
    assert settings["meta"]["title"] == "My Project Title"

    strings = json.loads((settings_dir / decompile.STRINGS_FILENAME).read_text(encoding="utf-8"))
    assert set(strings.keys()) == {"$schema", "meta", "teams", "script_strings"}

    script = (folder / "script" / decompile.SCRIPT_FILENAME).read_text(encoding="utf-8")
    assert "declare" in script

    stats = json.loads((folder / "build" / decompile.GENERATED_STATS_FILENAME).read_text(encoding="utf-8"))
    assert stats["space"]["bytes_used"] > 0
