"""Reads a Forge map variant's (``.mvar``) content header and Forge-label names.

Ported from the v2 prototype's ``app/rvt/map_variant.py`` -- deliberately independent of the native
``_reachvarianttool`` extension (not available in this repo yet, see CLAUDE.md): confirmed
empirically there that loading a ``.mvar`` through that extension raises, since its binding only
understands a *game* variant's own ``mpvr`` chunk, not a map variant's ``mvar``. A ``.mvar``'s
content header, however, is the exact same byte-aligned ``ReachUGCHeader`` shape a game variant's
own ``chdr`` chunk uses, so this is a small, purpose-built binary reader instead -- both this
header parse and the separate, bit-packed Forge-label parse below were verified against real
``.mvar`` files pulled from an MCC install (see each function's own docstring for specifics); this
port carries that verification forward rather than re-deriving it.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from pathlib import Path

CHDR_FOURCC = b"chdr"
MVAR_FOURCC = b"mvar"

# Relative to the start of the `chdr` fourcc -- empirically-verified constants (not values trusted
# from `ugc_header.h`'s struct arithmetic alone; see this module's own history in the v2 prototype
# for how `map_id`'s offset/endianness were pinned down against a real forged map).
_MAP_ID_REL = 0x3C
_TITLE_REL = 0x90
_TITLE_FIELD_BYTES = 128 * 2  # char16_t title[128]
_DESCRIPTION_REL = _TITLE_REL + _TITLE_FIELD_BYTES
_DESCRIPTION_FIELD_BYTES = 128 * 2  # char16_t description[128]

# Ported from ReachVariantTool's own `_mapIDList` (its "Map Permissions" page uses the same table
# to show a map ID as a name) -- predates a few maps MCC added later; an ID missing here just means
# `base_canvas_map` comes back `None`, same as RVT's own "Unknown {id}" fallback.
MAP_ID_NAMES: dict[int, str] = {
    1000: "Sword Base",
    1001: "Unused (DLC Sword Base)",
    1020: "Countdown",
    1035: "Boardwalk",
    1040: "Zealot",
    1055: "Powerhouse",
    1056: "Unused (DLC Powerhouse)",
    1080: "Boneyard",
    1150: "Reflection",
    1200: "Spire",
    1500: "Condemned",
    1510: "Highlands",
    2001: "Anchor 9",
    2002: "Breakpoint",
    2004: "Tempest",
    3006: "Forge World",
    5005: "Campaign Mission 0: NOBLE Actual",
    5010: "Campaign Mission 1: Winter Contingency",
    5020: "Campaign Mission 2: ONI: Sword Base",
    5030: "Campaign Mission 3: Nightfall",
    5035: "Campaign Mission 4: Tip of the Spear",
    5045: "Campaign Mission 5: Long Night of Solace",
    5050: "Campaign Mission 6: Exodus",
    5052: "Campaign Mission 7: New Alexandria",
    5060: "Campaign Mission 8: The Package",
    5070: "Campaign Mission 9: The Pillar of Autumn",
    5080: "Campaign Mission 10: Lone Wolf",
    7000: "Firefight: Overlook",
    7020: "Firefight: Courtyard",
    7030: "Firefight: Outpost",
    7040: "Firefight: Waterfront",
    7060: "Firefight: Beachhead",
    7080: "Firefight: Holdout",
    7110: "Firefight: Corvette",
    7130: "Firefight: Glacier",
    7500: "Firefight: Unearthed",
    10010: "Penance",
    10020: "Battle Canyon",
    10030: "Ridgeline",
    10050: "Breakneck",
    10060: "High Noon",
    10070: "Solitary",
    10080: "Firefight: Installation 04",
}


@dataclass
class MapVariantHeader:
    title: str
    description: str
    map_id: int

    @property
    def base_canvas_map(self) -> str | None:
        return MAP_ID_NAMES.get(self.map_id)


def _decode_widechar_field(data: bytes) -> str:
    """Decodes a fixed-size little-endian UTF-16 field, stopping at the first null code unit --
    same semantics as the game's own null-terminated ``char16_t[128]`` fields."""
    text = data.decode("utf-16-le", errors="replace")
    nul = text.find("\x00")
    return text[:nul] if nul != -1 else text


def parse_mvar_header(path: Path) -> MapVariantHeader:
    """Reads ``path``'s ``chdr`` chunk and returns its title/description/map_id.

    Args:
        path: Path to a ``.mvar`` (or any other Reach UGC file with a ``chdr`` chunk -- a game
            variant ``.bin`` has one too).

    Raises:
        ValueError: ``path`` doesn't exist, can't be read, or has no ``chdr`` chunk.
    """
    try:
        data = path.read_bytes()
    except OSError as e:
        raise ValueError(f"could not read {path}: {e}") from e

    chdr_offset = data.find(CHDR_FOURCC)
    if chdr_offset == -1:
        raise ValueError(f"{path} has no 'chdr' chunk -- not a recognized Reach UGC file")

    map_id_start = chdr_offset + _MAP_ID_REL
    title_start = chdr_offset + _TITLE_REL
    description_start = chdr_offset + _DESCRIPTION_REL
    description_end = description_start + _DESCRIPTION_FIELD_BYTES
    if len(data) < description_end:
        raise ValueError(f"{path} is too short to contain a full chdr chunk")

    map_id = int.from_bytes(data[map_id_start:map_id_start + 4], "little")
    title = _decode_widechar_field(data[title_start:title_start + _TITLE_FIELD_BYTES])
    description = _decode_widechar_field(data[description_start:description_end])
    return MapVariantHeader(title=title, description=description, map_id=map_id)


# ---- Forge label extraction (the `mvar` data chunk, bit-packed) --------------------------------
#
# Unlike the byte-aligned `chdr` chunk above, a map variant's own Forge-label string table lives
# inside its `mvar` data chunk -- the same GameVariantHeader-shaped, bit-packed layout a game
# variant's `mpvr` chunk uses, just under a different fourcc. This is a small, purpose-built bit
# reader ported from ReachVariantEditor's own JS reference implementation (bitstream.js +
# raw/map_variant_mvar.js's MapVariant constructor, GPLv3, github.com/DavidJCobb/
# ReachVariantEditor) -- that JS is itself commented "confirmed accurate via memory inspection of
# haloreach.dll" for exactly the header fields walked below.
#
# Only the bit-widths of every field between the chunk's start and the Forge-label string table are
# reproduced -- fields this module doesn't need the *value* of are skipped by width rather than
# decoded, since the bit reader has to walk past them regardless to reach the string table.
# `activity` is the one exception before the string table: its value gates whether a `hopperID`
# field is present, so it has to be read for real, not just skipped.
class _MvarBitReader:
    """A minimal MSB-first bit reader over a `bytes` buffer, starting at a given byte offset."""

    __slots__ = ("_data", "_bit_pos")

    def __init__(self, data: bytes, start_byte: int) -> None:
        self._data = data
        self._bit_pos = start_byte * 8

    def read_bits(self, count: int) -> int:
        if count <= 0:
            return 0
        result = 0
        remaining = count
        try:
            while remaining > 0:
                byte_pos = self._bit_pos // 8
                shift = self._bit_pos % 8
                bits_avail = 8 - shift
                take = min(bits_avail, remaining)
                masked = self._data[byte_pos] & (0xFF >> shift)
                chunk = masked >> (bits_avail - take)
                result = (result << take) | chunk
                self._bit_pos += take
                remaining -= take
        except IndexError as e:
            raise ValueError("ran past the end of the file while parsing the mvar chunk") from e
        return result

    def skip_bits(self, count: int) -> None:
        self._bit_pos += count

    def read_bytes(self, count: int) -> bytes:
        return bytes(self.read_bits(8) for _ in range(count))

    def skip_widechar_string_stop_early(self, max_chars: int) -> None:
        """A variable-length, null-terminated run of 16-bit code units, capped at ``max_chars`` --
        NOT a fixed-width field padded out to ``max_chars`` (that's this module's byte-aligned
        ``chdr`` title/description fields, a different, unrelated encoding)."""
        for _ in range(max_chars):
            if self.read_bits(16) == 0:
                return

    def skip_string_stop_early(self, max_bytes: int) -> None:
        """Same as :meth:`skip_widechar_string_stop_early`, but 8-bit code units (the author-name
        field inside a `VariantContentAuthor`)."""
        for _ in range(max_bytes):
            if self.read_bits(8) == 0:
                return


def _skip_variant_content_author(r: _MvarBitReader) -> None:
    """`VariantContentAuthor.parseBits()` -- timestamp + xuid (unused here) + a capped,
    null-terminated author name + a 1-bit isOnlineID flag."""
    r.skip_bits(64)  # timestamp
    r.skip_bits(64)  # xuid
    r.skip_string_stop_early(16)  # author name
    r.skip_bits(1)  # isOnlineID


def parse_mvar_forge_labels(path: Path) -> list[str]:
    """Reads ``path``'s ``mvar`` data chunk and returns every Forge label name placed on that map,
    exactly once each, in file order.

    This is a completely separate parse from :func:`parse_mvar_header` above (different chunk,
    different -- bit-packed, not byte-aligned -- encoding); see this module's own "Forge label
    extraction" section comment for where the format comes from.

    Args:
        path: Path to a ``.mvar``.

    Raises:
        ValueError: ``path`` doesn't exist, can't be read, has no ``mvar`` chunk, or the chunk is
            truncated/malformed partway through parsing.
    """
    try:
        data = path.read_bytes()
    except OSError as e:
        raise ValueError(f"could not read {path}: {e}") from e

    mvar_offset = data.find(MVAR_FOURCC)
    if mvar_offset == -1:
        raise ValueError(f"{path} has no 'mvar' chunk -- not a recognized map variant file")

    r = _MvarBitReader(data, mvar_offset)
    try:
        signature = r.read_bytes(4)
        if signature != MVAR_FOURCC:
            raise ValueError(f"{path}: expected 'mvar' signature, got {signature!r}")
        r.skip_bits(32)  # chunk size (not needed -- we already located the chunk by fourcc)
        r.skip_bits(16)  # chunkVersion
        r.skip_bits(16)  # chunkFlags
        r.skip_bits(0x14 * 8)  # SHA1 hash
        r.skip_bits(0x4 * 8)  # hashContentLength

        # GameVariantHeader (bit-packed form) -- same fields chdr's byte-aligned copy carries.
        r.skip_bits(4)  # content type
        r.skip_bits(32)  # file length
        r.skip_bits(64 * 4)  # four unknown uint64s
        activity = r.read_bits(3) - 1  # gates the conditional hopperID field below
        r.skip_bits(3)  # game mode
        r.skip_bits(3)  # engine
        r.skip_bits(32)  # map ID (already have this, byte-aligned, from parse_mvar_header)
        r.skip_bits(8)  # engine category index
        _skip_variant_content_author(r)  # createdBy
        _skip_variant_content_author(r)  # modifiedBy
        r.skip_widechar_string_stop_early(128)  # title (already have this from parse_mvar_header)
        r.skip_widechar_string_stop_early(128)  # description (same)
        if activity == 2:
            r.skip_bits(16)  # hopperID
        # The reference implementation's next branch (extra fields when a game-mode-scoped field
        # equals 1 or 2) checks a variable its own constructor never actually assigns -- dead code
        # that never fires for any real file, deliberately not ported here.

        r.skip_bits(8)  # unk02B0
        r.skip_bits(32)  # unk02DC
        r.skip_bits(32)  # unk02E0
        r.skip_bits(9)  # unk02B2
        r.skip_bits(32)  # unk02B4 (a second copy of the map ID)
        r.skip_bits(1)  # unk02D9
        r.skip_bits(1)  # unk02DA
        r.skip_bits(32 * 6)  # bounding box (6 floats)
        r.skip_bits(32)  # unk02D0
        r.skip_bits(32)  # unk02D4

        string_count = r.read_bits(9)
        offsets: list[int | None] = []
        for _ in range(string_count):
            has_offset = r.read_bits(1)
            offsets.append(r.read_bits(12) if has_offset else None)

        if string_count == 0:
            return []

        data_length = r.read_bits(13)
        is_compressed = r.read_bits(1)
        if is_compressed:
            compressed_size = r.read_bits(13)
            compressed = r.read_bytes(compressed_size)
            # The first 4 bytes are the uncompressed size, written ahead of the actual zlib stream
            # -- not needed here since Python's zlib.decompress() doesn't need a size hint.
            try:
                buffer = zlib.decompress(compressed[4:])
            except zlib.error as e:
                raise ValueError(f"{path}: could not decompress forge label data: {e}") from e
        else:
            buffer = r.read_bytes(data_length)
    except IndexError as e:
        raise ValueError(f"{path}: ran past the end of the file while parsing the mvar chunk") from e

    labels: list[str] = []
    size = len(buffer)
    for offset in offsets:
        if offset is None or offset >= size:
            continue
        end = buffer.find(b"\x00", offset)
        if end == -1:
            end = size
        labels.append(buffer[offset:end].decode("ascii", errors="replace"))
    return labels
