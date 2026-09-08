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


def test_write_maps_json_writes_both_master_and_maps_json_identically(tmp_path: Path) -> None:
    entries = maps_io.scan_maps()  # empty is fine -- just exercising the writer
    folder = tmp_path / "project"
    folder.mkdir()
    (folder / "extra.mvar")  # not a real map -- irrelevant, scan_maps() above didn't touch disk

    master_path, maps_path = maps_io.write_maps_json(
        [maps_io.MapEntry("x.mvar", maps_io.SOURCE_PERSONAL, "X", "", 0, None)], folder
    )

    assert master_path == folder / "maps" / "master.json"
    assert maps_path == folder / "maps.json"
    master_doc = json.loads(master_path.read_text(encoding="utf-8"))
    maps_doc = json.loads(maps_path.read_text(encoding="utf-8"))
    assert master_doc["maps"] == maps_doc["maps"]
    assert master_doc["maps"][0]["title"] == "X"


def test_write_maps_json_with_no_entries_writes_an_empty_list(tmp_path: Path) -> None:
    folder = tmp_path / "project"
    folder.mkdir()

    _master, maps_path = maps_io.write_maps_json([], folder)

    assert json.loads(maps_path.read_text(encoding="utf-8"))["maps"] == []
