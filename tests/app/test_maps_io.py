import json
from pathlib import Path

from mvar_fixtures import build_chdr_bytes, build_full_mvar

from in_reach.app import maps_io


def test_scan_maps_reads_every_mvar_in_each_folder(tmp_path: Path) -> None:
    personal = tmp_path / "personal"
    personal.mkdir()
    (personal / "MyMap.mvar").write_bytes(build_chdr_bytes(title="My Map", map_id=3006))
    standard = tmp_path / "standard"
    standard.mkdir()
    (standard / "Countdown.mvar").write_bytes(build_chdr_bytes(title="Countdown", map_id=1020))

    entries = maps_io.scan_maps(personal_dir=personal, standard_dir=standard)

    assert [e.filename for e in entries] == ["MyMap.mvar", "Countdown.mvar"]
    assert [e.source for e in entries] == [maps_io.SOURCE_PERSONAL, maps_io.SOURCE_STANDARD]
    assert entries[1].base_canvas_map == "Countdown"


def test_scan_maps_sorts_personal_first_then_standard_then_hopper_by_title(tmp_path: Path) -> None:
    personal = tmp_path / "personal"
    standard = tmp_path / "standard"
    hopper = tmp_path / "hopper"
    for folder in (personal, standard, hopper):
        folder.mkdir()
    (hopper / "z.mvar").write_bytes(build_chdr_bytes(title="Zulu"))
    (standard / "a.mvar").write_bytes(build_chdr_bytes(title="Alpha"))
    (personal / "b.mvar").write_bytes(build_chdr_bytes(title="Bravo"))

    entries = maps_io.scan_maps(personal_dir=personal, standard_dir=standard, hopper_dir=hopper)

    assert [e.title for e in entries] == ["Bravo", "Alpha", "Zulu"]


def test_scan_maps_skips_a_corrupt_file_rather_than_raising(tmp_path: Path) -> None:
    folder = tmp_path / "maps"
    folder.mkdir()
    (folder / "corrupt.mvar").write_bytes(b"not a real file")
    (folder / "good.mvar").write_bytes(build_chdr_bytes(title="Good Map"))

    entries = maps_io.scan_maps(personal_dir=folder)

    assert [e.title for e in entries] == ["Good Map"]


def test_scan_maps_of_a_missing_or_unset_folder_is_empty() -> None:
    assert maps_io.scan_maps() == []
    assert maps_io.scan_maps(personal_dir=Path("/does/not/exist")) == []


def test_scan_maps_still_gets_an_entry_when_only_forge_labels_fail_to_parse(tmp_path: Path) -> None:
    # A chdr-only file (no mvar chunk) still yields an entry -- just with forge_labels=[] -- rather
    # than being excluded outright over a label-parsing hiccup.
    folder = tmp_path / "maps"
    folder.mkdir()
    (folder / "map.mvar").write_bytes(build_chdr_bytes(title="No Labels"))

    entries = maps_io.scan_maps(personal_dir=folder)

    assert entries[0].forge_labels == []


def test_scan_maps_reads_real_forge_labels_when_present(tmp_path: Path) -> None:
    folder = tmp_path / "maps"
    folder.mkdir()
    (folder / "map.mvar").write_bytes(
        build_full_mvar(map_id=3006, title="Labeled", description="", labels=["team_only", "ctf_flag"])
    )

    entries = maps_io.scan_maps(personal_dir=folder)

    assert entries[0].forge_labels == ["team_only", "ctf_flag"]


def test_write_maps_json_writes_to_in_reach(tmp_path: Path) -> None:
    in_reach_dir = tmp_path / ".in-reach"
    in_reach_dir.mkdir()

    maps_path = maps_io.write_maps_json(
        [maps_io.MapEntry("x.mvar", maps_io.SOURCE_PERSONAL, "X", "", 0, None)], in_reach_dir
    )

    assert maps_path == in_reach_dir / "maps.json"
    maps_doc = json.loads(maps_path.read_text(encoding="utf-8"))
    assert maps_doc["maps"][0]["title"] == "X"


def test_write_maps_json_with_no_entries_writes_an_empty_list(tmp_path: Path) -> None:
    in_reach_dir = tmp_path / ".in-reach"
    in_reach_dir.mkdir()

    maps_path = maps_io.write_maps_json([], in_reach_dir)

    assert json.loads(maps_path.read_text(encoding="utf-8"))["maps"] == []


def test_write_maps_json_a_second_call_overwrites_the_shared_copy(tmp_path: Path) -> None:
    # PROMPT.md: maps.json is shared across every project, not duplicated per one -- a second
    # project's own scan should overwrite the one file, not create a second copy.
    in_reach_dir = tmp_path / ".in-reach"
    in_reach_dir.mkdir()

    maps_io.write_maps_json([maps_io.MapEntry("a.mvar", maps_io.SOURCE_PERSONAL, "A", "", 0, None)], in_reach_dir)
    maps_path = maps_io.write_maps_json(
        [maps_io.MapEntry("b.mvar", maps_io.SOURCE_PERSONAL, "B", "", 0, None)], in_reach_dir
    )

    maps_doc = json.loads(maps_path.read_text(encoding="utf-8"))
    assert [entry["title"] for entry in maps_doc["maps"]] == ["B"]


def test_read_maps_json_round_trips_what_write_maps_json_wrote(tmp_path: Path) -> None:
    in_reach_dir = tmp_path / ".in-reach"
    in_reach_dir.mkdir()
    entry = maps_io.MapEntry("x.mvar", maps_io.SOURCE_PERSONAL, "X", "desc", 42, "Countdown", ["ctf_flag"])
    maps_io.write_maps_json([entry], in_reach_dir)

    assert maps_io.read_maps_json(in_reach_dir) == [entry]


def test_read_maps_json_of_a_missing_file_is_empty(tmp_path: Path) -> None:
    assert maps_io.read_maps_json(tmp_path / ".in-reach") == []


def test_read_maps_json_of_unparsable_json_is_empty(tmp_path: Path) -> None:
    in_reach_dir = tmp_path / ".in-reach"
    in_reach_dir.mkdir()
    (in_reach_dir / maps_io.MAPS_FILENAME).write_text("not json", encoding="utf-8")

    assert maps_io.read_maps_json(in_reach_dir) == []


# -- filter_maps_for_gametype --------------------------------------------------------------------


def _entry(**overrides) -> "maps_io.MapEntry":
    defaults = dict(
        filename="a.mvar", source=maps_io.SOURCE_PERSONAL, title="A", description="", map_id=42,
        base_canvas_map=None, forge_labels=[],
    )
    defaults.update(overrides)
    return maps_io.MapEntry(**defaults)


def test_filter_maps_for_gametype_with_no_restrictions_returns_everything() -> None:
    from in_reach.app.rvt.models.script_settings import ScriptSettings

    entries = [_entry(map_id=1), _entry(map_id=2)]

    assert maps_io.filter_maps_for_gametype(entries, ScriptSettings()) == entries


def test_filter_maps_for_gametype_only_these_maps_is_an_allow_list() -> None:
    from in_reach.app.rvt.models.enums import MapPermissionType
    from in_reach.app.rvt.models.script_settings import MapPermissions, ScriptSettings

    allowed = _entry(map_id=1, title="Allowed")
    excluded = _entry(map_id=2, title="Excluded")
    settings = ScriptSettings(map_permissions=MapPermissions(type=MapPermissionType.only_these_maps, map_ids=[1]))

    result = maps_io.filter_maps_for_gametype([allowed, excluded], settings)

    assert [e.title for e in result] == ["Allowed"]


def test_filter_maps_for_gametype_never_these_maps_is_a_deny_list() -> None:
    from in_reach.app.rvt.models.enums import MapPermissionType
    from in_reach.app.rvt.models.script_settings import MapPermissions, ScriptSettings

    allowed = _entry(map_id=1, title="Allowed")
    excluded = _entry(map_id=2, title="Excluded")
    settings = ScriptSettings(map_permissions=MapPermissions(type=MapPermissionType.never_these_maps, map_ids=[2]))

    result = maps_io.filter_maps_for_gametype([allowed, excluded], settings)

    assert [e.title for e in result] == ["Allowed"]


def test_filter_maps_for_gametype_requires_every_forge_label() -> None:
    from in_reach.app.rvt.models.script_settings import ForgeLabel, ScriptSettings

    has_both = _entry(title="Has Both", forge_labels=["flag_a", "flag_b"])
    has_one = _entry(title="Has One", forge_labels=["flag_a"])
    settings = ScriptSettings(forge_labels=[ForgeLabel(name="flag_a"), ForgeLabel(name="flag_b")])

    result = maps_io.filter_maps_for_gametype([has_both, has_one], settings)

    assert [e.title for e in result] == ["Has Both"]


def test_filter_maps_for_gametype_ignores_blank_forge_label_names() -> None:
    from in_reach.app.rvt.models.script_settings import ForgeLabel, ScriptSettings

    entry = _entry(forge_labels=[])
    settings = ScriptSettings(forge_labels=[ForgeLabel(name="")])

    assert maps_io.filter_maps_for_gametype([entry], settings) == [entry]


def test_write_valid_maps_json_writes_the_filtered_entries(tmp_path: Path) -> None:
    out_path = tmp_path / "valid_maps.json"

    maps_io.write_valid_maps_json([_entry(title="A")], out_path)

    document = json.loads(out_path.read_text(encoding="utf-8"))
    assert document["maps"][0]["title"] == "A"
