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


def test_write_maps_json_writes_master_in_the_project_and_maps_json_in_in_reach(tmp_path: Path) -> None:
    folder = tmp_path / "project"
    folder.mkdir()
    in_reach_dir = tmp_path / ".in-reach"
    in_reach_dir.mkdir()

    master_path, maps_path = maps_io.write_maps_json(
        [maps_io.MapEntry("x.mvar", maps_io.SOURCE_PERSONAL, "X", "", 0, None)], folder, in_reach_dir
    )

    assert master_path == folder / "maps" / "master.json"
    assert maps_path == in_reach_dir / "maps.json"
    master_doc = json.loads(master_path.read_text(encoding="utf-8"))
    maps_doc = json.loads(maps_path.read_text(encoding="utf-8"))
    assert master_doc["maps"] == maps_doc["maps"]
    assert master_doc["maps"][0]["title"] == "X"


def test_write_maps_json_with_no_entries_writes_an_empty_list(tmp_path: Path) -> None:
    folder = tmp_path / "project"
    folder.mkdir()
    in_reach_dir = tmp_path / ".in-reach"
    in_reach_dir.mkdir()

    _master, maps_path = maps_io.write_maps_json([], folder, in_reach_dir)

    assert json.loads(maps_path.read_text(encoding="utf-8"))["maps"] == []


def test_write_maps_json_a_second_call_overwrites_the_shared_in_reach_copy(tmp_path: Path) -> None:
    # PROMPT.md: maps.json is shared across every project now, not duplicated per one -- a second
    # project's own scan should overwrite the one file, not create a second copy.
    first_folder = tmp_path / "first"
    first_folder.mkdir()
    second_folder = tmp_path / "second"
    second_folder.mkdir()
    in_reach_dir = tmp_path / ".in-reach"
    in_reach_dir.mkdir()

    maps_io.write_maps_json(
        [maps_io.MapEntry("a.mvar", maps_io.SOURCE_PERSONAL, "A", "", 0, None)], first_folder, in_reach_dir
    )
    _master, maps_path = maps_io.write_maps_json(
        [maps_io.MapEntry("b.mvar", maps_io.SOURCE_PERSONAL, "B", "", 0, None)], second_folder, in_reach_dir
    )

    maps_doc = json.loads(maps_path.read_text(encoding="utf-8"))
    assert [entry["title"] for entry in maps_doc["maps"]] == ["B"]
