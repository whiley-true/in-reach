import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from in_reach.app.rvt import decompile
from in_reach.app.rvt.models.game_settings import GameSettings, Meta, Multiplayer
from in_reach.app.rvt.models.script_settings import ScriptedOption, ScriptSettings

_FIXTURES_DIR = Path(__file__).parent / "resources"


class _FakeMultiplayer:
    pass


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


def test_decompile_into_project_writes_settings_strings_and_script(
    tmp_path: Path, monkeypatch
) -> None:
    option = ScriptedOption(name="Round Length")
    settings = _game_settings(scripted_options=[option])
    variant = _FakeVariant(_FakeMultiplayer())

    monkeypatch.setattr(decompile, "get_rvt", lambda: type("Rvt", (), {"load": staticmethod(lambda path: variant)})())
    monkeypatch.setattr(decompile, "extract_game_settings", lambda v, path: settings)
    monkeypatch.setattr(decompile.strings_io, "extract_strings", lambda mp: {"meta": {}, "teams": [], "script_strings": []})

    bin_path = tmp_path / "source.bin"
    bin_path.write_bytes(b"\x00")
    folder = tmp_path / "project"
    folder.mkdir()

    decompile.decompile_into_project(bin_path, folder)

    settings_dir = folder / "edit" / "settings"
    rvt_dir = folder / "edit" / "rvt"
    assert (settings_dir / decompile.SETTINGS_FILENAME).is_file()
    assert (settings_dir / decompile.SCRIPT_SETTINGS_FILENAME).is_file()
    assert (settings_dir / decompile.STRINGS_FILENAME).is_file()
    assert (rvt_dir / decompile.SCRIPT_FILENAME).read_text(encoding="utf-8") == "-- script --"

    script_settings_json = json.loads((settings_dir / decompile.SCRIPT_SETTINGS_FILENAME).read_text(encoding="utf-8"))
    assert script_settings_json["scripted_options"][0]["name"] == "Round Length"


def test_decompile_into_project_handles_non_multiplayer_variants(tmp_path: Path, monkeypatch) -> None:
    settings = _game_settings(multiplayer=False)
    variant = _FakeVariant(None)

    monkeypatch.setattr(decompile, "get_rvt", lambda: type("Rvt", (), {"load": staticmethod(lambda path: variant)})())
    monkeypatch.setattr(decompile, "extract_game_settings", lambda v, path: settings)
    monkeypatch.setattr(decompile.strings_io, "extract_strings", lambda mp: {"meta": {}, "teams": [], "script_strings": []})

    bin_path = tmp_path / "source.bin"
    bin_path.write_bytes(b"\x00")
    folder = tmp_path / "project"
    folder.mkdir()

    decompile.decompile_into_project(bin_path, folder)

    script_settings_json = json.loads(
        (folder / "edit" / "settings" / decompile.SCRIPT_SETTINGS_FILENAME).read_text(encoding="utf-8")
    )
    # No multiplayer settings, so script_settings falls back to a bare default -- no scripted
    # options rather than raising on the missing multiplayer.script_settings.
    assert script_settings_json["scripted_options"] == []


@pytest.mark.skipif(not (_FIXTURES_DIR / "juggernaut" / "juggernaut.bin").is_file(), reason="fixture .bin not present")
def test_decompile_into_project_against_a_real_bin(tmp_path: Path) -> None:
    """End-to-end against a real Reach .bin fixture (a saved Juggernaut variant) -- exercises the
    actual bundled native extension, not fakes."""
    folder = tmp_path / "project"
    folder.mkdir()

    decompile.decompile_into_project(_FIXTURES_DIR / "juggernaut" / "juggernaut.bin", folder)

    settings_dir = folder / "edit" / "settings"
    settings = json.loads((settings_dir / decompile.SETTINGS_FILENAME).read_text(encoding="utf-8"))
    assert settings["meta"]["is_multiplayer"] is True
    assert settings["meta"]["title"]

    strings = json.loads((settings_dir / decompile.STRINGS_FILENAME).read_text(encoding="utf-8"))
    assert set(strings.keys()) == {"meta", "teams", "script_strings"}

    script = (folder / "edit" / "rvt" / decompile.SCRIPT_FILENAME).read_text(encoding="utf-8")
    assert "declare" in script
