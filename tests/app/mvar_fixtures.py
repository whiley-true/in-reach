"""Synthetic ``.mvar`` byte builders for ``test_map_variant.py``/``test_maps_io.py``/
``test_new_project.py`` -- not a test module itself (no ``test_`` prefix, so pytest won't collect
it), just shared fixture-building helpers.

Field offsets/widths mirror :mod:`in_reach.app.map_variant`'s own reader exactly -- see that
module's docstring for where they come from.
"""

from __future__ import annotations

from in_reach.app import map_variant as mv


def build_chdr_bytes(*, map_id: int = 0, title: str = "", description: str = "", prefix: bytes = b"") -> bytes:
    """A minimal buffer containing just a ``chdr`` chunk -- enough for :func:`parse_mvar_header`,
    not a full map variant file (no ``mvar`` chunk -- :func:`parse_mvar_forge_labels` will raise
    for it, same as any file missing that chunk).

    Every field offset (``_MAP_ID_REL`` etc.) is measured from the start of the ``chdr`` fourcc
    itself (see ``map_variant.py``'s own comment), so the fourcc has to be the first 4 bytes of
    this chunk, not written separately ahead of it.
    """
    chunk = bytearray(mv._DESCRIPTION_REL + mv._DESCRIPTION_FIELD_BYTES)
    chunk[0:4] = mv.CHDR_FOURCC
    chunk[mv._MAP_ID_REL:mv._MAP_ID_REL + 4] = int(map_id).to_bytes(4, "little")
    title_bytes = title.encode("utf-16-le")
    chunk[mv._TITLE_REL:mv._TITLE_REL + len(title_bytes)] = title_bytes
    description_bytes = description.encode("utf-16-le")
    chunk[mv._DESCRIPTION_REL:mv._DESCRIPTION_REL + len(description_bytes)] = description_bytes
    return prefix + bytes(chunk)


class _BitWriter:
    """MSB-first bit writer -- the exact inverse of ``map_variant._MvarBitReader``."""

    def __init__(self) -> None:
        self._bits: list[int] = []

    def write_bits(self, value: int, count: int) -> None:
        for i in range(count - 1, -1, -1):
            self._bits.append((value >> i) & 1)

    def write_bytes(self, data: bytes) -> None:
        for byte in data:
            self.write_bits(byte, 8)

    def to_bytes(self) -> bytes:
        bits = self._bits + [0] * (-len(self._bits) % 8)
        out = bytearray(len(bits) // 8)
        for i, bit in enumerate(bits):
            out[i // 8] |= bit << (7 - (i % 8))
        return bytes(out)


def build_mvar_forge_label_bytes(labels: list[str], *, prefix: bytes = b"") -> bytes:
    """A buffer containing just an ``mvar`` chunk, walking the exact same bit-packed field
    sequence :func:`in_reach.app.map_variant.parse_mvar_forge_labels` reads, ending in a real
    (uncompressed) Forge-label string table built from ``labels``."""
    w = _BitWriter()
    w.write_bytes(mv.MVAR_FOURCC)
    w.write_bits(0, 32)  # chunk size (unused by the reader)
    w.write_bits(0, 16)  # chunkVersion
    w.write_bits(0, 16)  # chunkFlags
    w.write_bits(0, 0x14 * 8)  # SHA1 hash
    w.write_bits(0, 0x4 * 8)  # hashContentLength

    w.write_bits(0, 4)  # content type
    w.write_bits(0, 32)  # file length
    w.write_bits(0, 64 * 4)  # four unknown uint64s
    w.write_bits(0, 3)  # activity (raw 0 -> decoded -1, so the hopperID branch is never taken)
    w.write_bits(0, 3)  # game mode
    w.write_bits(0, 3)  # engine
    w.write_bits(0, 32)  # map ID (unused here -- parse_mvar_header reads its own byte-aligned copy)
    w.write_bits(0, 8)  # engine category index

    for _ in range(2):  # createdBy, modifiedBy
        w.write_bits(0, 64)  # timestamp
        w.write_bits(0, 64)  # xuid
        w.write_bits(0, 8)  # author name -- immediate null terminator (empty string)
        w.write_bits(0, 1)  # isOnlineID

    w.write_bits(0, 16)  # title -- immediate null terminator
    w.write_bits(0, 16)  # description -- immediate null terminator

    w.write_bits(0, 8)  # unk02B0
    w.write_bits(0, 32)  # unk02DC
    w.write_bits(0, 32)  # unk02E0
    w.write_bits(0, 9)  # unk02B2
    w.write_bits(0, 32)  # unk02B4
    w.write_bits(0, 1)  # unk02D9
    w.write_bits(0, 1)  # unk02DA
    w.write_bits(0, 32 * 6)  # bounding box
    w.write_bits(0, 32)  # unk02D0
    w.write_bits(0, 32)  # unk02D4

    buffer = b"\x00".join(label.encode("ascii") for label in labels) + (b"\x00" if labels else b"")
    offsets: list[int] = []
    cursor = 0
    for label in labels:
        offsets.append(cursor)
        cursor += len(label) + 1

    w.write_bits(len(labels), 9)  # string_count
    for offset in offsets:
        w.write_bits(1, 1)  # has_offset
        w.write_bits(offset, 12)

    w.write_bits(len(buffer), 13)  # data_length
    w.write_bits(0, 1)  # is_compressed
    w.write_bytes(buffer)

    return prefix + w.to_bytes()


def build_full_mvar(*, map_id: int, title: str, description: str, labels: list[str]) -> bytes:
    """A single buffer with both a ``chdr`` chunk (for :func:`parse_mvar_header`) and an ``mvar``
    chunk (for :func:`parse_mvar_forge_labels`), as a real ``.mvar`` file has both."""
    chdr = build_chdr_bytes(map_id=map_id, title=title, description=description)
    return build_mvar_forge_label_bytes(labels, prefix=chdr)
