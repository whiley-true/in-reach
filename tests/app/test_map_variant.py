from pathlib import Path

import pytest
from mvar_fixtures import build_chdr_bytes, build_full_mvar, build_mvar_forge_label_bytes

from in_reach.app import map_variant


def test_parse_mvar_header_reads_title_description_and_map_id(tmp_path: Path) -> None:
    path = tmp_path / "test.mvar"
    path.write_bytes(build_chdr_bytes(map_id=3006, title="Forge World", description="A big canvas"))

    header = map_variant.parse_mvar_header(path)

    assert header.map_id == 3006
    assert header.title == "Forge World"
    assert header.description == "A big canvas"
    assert header.base_canvas_map == "Forge World"


def test_parse_mvar_header_unknown_map_id_has_no_base_canvas_map(tmp_path: Path) -> None:
    path = tmp_path / "test.mvar"
    path.write_bytes(build_chdr_bytes(map_id=999999, title="Mystery"))

    header = map_variant.parse_mvar_header(path)

    assert header.base_canvas_map is None


def test_parse_mvar_header_tolerates_a_leading_prefix_before_the_chunk(tmp_path: Path) -> None:
    path = tmp_path / "test.mvar"
    path.write_bytes(build_chdr_bytes(map_id=1000, title="Sword Base", prefix=b"\x00" * 32))

    header = map_variant.parse_mvar_header(path)

    assert header.title == "Sword Base"
    assert header.base_canvas_map == "Sword Base"


def test_parse_mvar_header_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        map_variant.parse_mvar_header(tmp_path / "nope.mvar")


def test_parse_mvar_header_without_a_chdr_chunk_raises(tmp_path: Path) -> None:
    path = tmp_path / "test.mvar"
    path.write_bytes(b"not a real file")

    with pytest.raises(ValueError):
        map_variant.parse_mvar_header(path)


def test_parse_mvar_header_truncated_chunk_raises(tmp_path: Path) -> None:
    path = tmp_path / "test.mvar"
    path.write_bytes(map_variant.CHDR_FOURCC + b"\x00" * 10)

    with pytest.raises(ValueError):
        map_variant.parse_mvar_header(path)


# -- Forge label parsing ------------------------------------------------------------------------


def test_parse_mvar_forge_labels_reads_labels_in_order(tmp_path: Path) -> None:
    path = tmp_path / "test.mvar"
    path.write_bytes(build_mvar_forge_label_bytes(["team_only", "ctf_flag", "koth_hill"]))

    assert map_variant.parse_mvar_forge_labels(path) == ["team_only", "ctf_flag", "koth_hill"]


def test_parse_mvar_forge_labels_with_no_labels_is_empty(tmp_path: Path) -> None:
    path = tmp_path / "test.mvar"
    path.write_bytes(build_mvar_forge_label_bytes([]))

    assert map_variant.parse_mvar_forge_labels(path) == []


def test_parse_mvar_forge_labels_without_an_mvar_chunk_raises(tmp_path: Path) -> None:
    path = tmp_path / "test.mvar"
    path.write_bytes(build_chdr_bytes(title="No mvar chunk here"))

    with pytest.raises(ValueError):
        map_variant.parse_mvar_forge_labels(path)


def test_parse_mvar_forge_labels_truncated_chunk_raises(tmp_path: Path) -> None:
    path = tmp_path / "test.mvar"
    path.write_bytes(map_variant.MVAR_FOURCC + b"\x00" * 4)

    with pytest.raises(ValueError):
        map_variant.parse_mvar_forge_labels(path)


def test_a_real_looking_file_parses_both_header_and_labels(tmp_path: Path) -> None:
    path = tmp_path / "test.mvar"
    path.write_bytes(
        build_full_mvar(map_id=3006, title="Forge World", description="", labels=["infection", "inf_spawn"])
    )

    header = map_variant.parse_mvar_header(path)
    labels = map_variant.parse_mvar_forge_labels(path)

    assert header.title == "Forge World"
    assert labels == ["infection", "inf_spawn"]
