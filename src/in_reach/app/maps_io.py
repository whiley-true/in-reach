"""Scans a project's map-variant folders (personal + built-in) into the shared ``maps.json``, and
filters that master list down to what one gametype can actually be played on.

Ported, in reduced form, from the v2 prototype's ``app/maps_io.py``. PROMPT.md, across two passes:
the unfiltered master scan writes once, centrally, to ``<in_reach_dir>/maps.json`` (the
``.in-reach`` folder every project shares) rather than duplicating a copy per gametype project --
first as ``<project_folder>/maps.json``, then (once decompiling actually produced a real
``script_settings.json`` to filter against) the leftover ``<project_folder>/maps/master.json``
per-project snapshot was dropped too ("there should be no maps dir anymore") in favor of
:func:`filter_maps_for_gametype`'s real output, ``<project_folder>/settings/valid_maps.json`` (see
:mod:`in_reach.app.rvt.decompile`, which calls both of these once it has a loaded ``.bin``'s
``script_settings`` in hand).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from in_reach.app.map_variant import parse_mvar_forge_labels, parse_mvar_header
from in_reach.app.rvt.models.enums import MapPermissionType
from in_reach.app.rvt.models.script_settings import ScriptSettings

MAP_VARIANT_EXTENSION = ".mvar"
MAPS_FILENAME = "maps.json"
VALID_MAPS_FILENAME = "valid_maps.json"

MAPS_FILE_COMMENT = (
    "Every Forge map variant in-reach found across the personal/standard/hopper map-variant "
    "folders, shared across every project -- regenerated wholesale whenever a project is created. "
    "Do not hand-edit."
)
VALID_MAPS_FILE_COMMENT = (
    "maps.json (in .in-reach/), narrowed down to the maps this gametype can actually be played on "
    "-- see in_reach.app.maps_io.filter_maps_for_gametype. Do not hand-edit."
)

SOURCE_PERSONAL = "personal"
SOURCE_STANDARD = "standard"
SOURCE_HOPPER = "hopper"

# Display/sort order -- personal (the user's own forged maps) first, then the two built-in
# folders, standard before hopper.
_SOURCE_ORDER = {SOURCE_PERSONAL: 0, SOURCE_STANDARD: 1, SOURCE_HOPPER: 2}


@dataclass
class MapEntry:
    filename: str
    source: str  # one of SOURCE_PERSONAL/SOURCE_STANDARD/SOURCE_HOPPER
    title: str
    description: str
    map_id: int
    base_canvas_map: str | None
    forge_labels: list[str] = field(default_factory=list)


def _scan_folder(folder: Path | None, source: str) -> list[MapEntry]:
    """Parses every ``.mvar`` in ``folder``. A missing/non-existent ``folder`` yields no entries; a
    file that fails to parse (corrupt, or not actually a Reach UGC file) is silently skipped.

    A file whose ``chdr`` header parses fine but whose Forge-label table doesn't still gets an
    entry, just with ``forge_labels=[]`` -- excluding a map entirely over a label-parsing hiccup
    would be worse than under-reporting its labels.
    """
    if folder is None or not folder.is_dir():
        return []
    entries = []
    for path in sorted(folder.glob(f"*{MAP_VARIANT_EXTENSION}")):
        try:
            header = parse_mvar_header(path)
        except ValueError:
            continue
        try:
            forge_labels = parse_mvar_forge_labels(path)
        except ValueError:
            forge_labels = []
        entries.append(
            MapEntry(
                filename=path.name,
                source=source,
                title=header.title,
                description=header.description,
                map_id=header.map_id,
                base_canvas_map=header.base_canvas_map,
                forge_labels=forge_labels,
            )
        )
    return entries


def scan_maps(
    *,
    personal_dir: Path | None = None,
    standard_dir: Path | None = None,
    hopper_dir: Path | None = None,
) -> list[MapEntry]:
    """Scans each given folder for ``.mvar`` files and returns their parsed headers.

    Args:
        personal_dir: The resolved personal map-variants folder, if any.
        standard_dir: The resolved standard map-variants folder, if any.
        hopper_dir: The resolved hopper map-variants folder, if any.

    Returns:
        Entries sorted personal-first, then standard, then hopper, by title (case-insensitive)
        within each source.
    """
    entries = (
        _scan_folder(personal_dir, SOURCE_PERSONAL)
        + _scan_folder(standard_dir, SOURCE_STANDARD)
        + _scan_folder(hopper_dir, SOURCE_HOPPER)
    )
    entries.sort(key=lambda e: (_SOURCE_ORDER[e.source], e.title.lower(), e.filename))
    return entries


def _write_entries_json(entries: list[MapEntry], out_path: Path, comment: str) -> Path:
    document = {
        "_comment": comment,
        "maps": [asdict(entry) for entry in entries],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(document, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return out_path


def write_maps_json(entries: list[MapEntry], in_reach_dir: Path) -> Path:
    """Writes ``entries`` to ``<in_reach_dir>/maps.json`` -- the one shared master scan every
    project reads, not duplicated per one.

    Args:
        entries: Scanned entries, as returned by :func:`scan_maps`.
        in_reach_dir: The project's ``.in-reach`` folder.

    Returns:
        The written path.
    """
    return _write_entries_json(entries, in_reach_dir / MAPS_FILENAME, MAPS_FILE_COMMENT)


def read_maps_json(in_reach_dir: Path) -> list[MapEntry]:
    """Reads back ``<in_reach_dir>/maps.json`` (normally to re-filter it into a
    ``valid_maps.json`` -- see :func:`filter_maps_for_gametype` -- without a full folder rescan).

    Returns an empty list if the file doesn't exist or fails to parse, same "never raise" reasoning
    as :func:`~in_reach.app.rvt.settings_io.load_script_settings`.
    """
    path = in_reach_dir / MAPS_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    try:
        return [MapEntry(**entry) for entry in data.get("maps", [])]
    except TypeError:
        return []


def filter_maps_for_gametype(entries: list[MapEntry], script_settings: ScriptSettings) -> list[MapEntry]:
    """Narrows ``entries`` (normally ``maps.json``'s full list) down to the maps this gametype can
    actually be played on, per its own ``script_settings``:

    - ``map_permissions``: an allow-list (``only_these_maps``) or deny-list (``never_these_maps``)
      of base canvas map IDs -- matched against each entry's own ``map_id``.
    - ``forge_labels``: every named label in ``script_settings.forge_labels`` is a real
      requirement -- a label only shows up there at all when the gametype's script actually
      declares/references it, so its mere presence already means the script needs at least one
      matching object on the map. ``map_must_have_at_least`` is *not* used as the "is this
      required" gate: real published gametypes commonly leave it at its default ``0`` even though
      the label is genuinely required. Every required label's name must appear somewhere in the
      map's own ``forge_labels`` -- a map missing even one is excluded; this checks presence only,
      not any count.

    A gametype with no configured restrictions and no forge labels at all returns ``entries``
    unfiltered.

    Args:
        entries: The unfiltered master scan, as returned by :func:`scan_maps`.
        script_settings: The gametype's own decompiled ``ScriptSettings``.

    Returns:
        The entries this gametype can actually be played on.
    """
    permissions = script_settings.map_permissions
    required_labels = {label.name for label in script_settings.forge_labels if label.name}

    result = []
    for entry in entries:
        if permissions.type == MapPermissionType.only_these_maps:
            if entry.map_id not in permissions.map_ids:
                continue
        elif entry.map_id in permissions.map_ids:
            continue

        if required_labels and not required_labels.issubset(entry.forge_labels):
            continue

        result.append(entry)
    return result


def write_valid_maps_json(entries: list[MapEntry], out_path: Path) -> Path:
    """Writes ``entries`` (normally :func:`filter_maps_for_gametype`'s own result) to ``out_path``
    (normally ``<project_folder>/settings/valid_maps.json``)."""
    return _write_entries_json(entries, out_path, VALID_MAPS_FILE_COMMENT)
