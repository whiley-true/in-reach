"""Scans a project's map-variant folders (personal + built-in) into ``maps/master.json`` and
``maps.json``.

Ported, in reduced form, from the v2 prototype's ``app/maps_io.py``: that module also filtered
``master.json`` down to ``maps.json`` against a gametype's own ``script_settings.json``
(``map_permissions``/``forge_labels``) -- nothing here has a ``script_settings.json`` yet (this
repo's ``edit/rvt`` starts empty, see :mod:`in_reach.app.new_project`), so :func:`write_maps_json`
only ever writes the unfiltered scan to both files for now. Re-filtering ``maps.json`` down once a
real ``script_settings.json`` exists is future work, ported the same deliberate way this was.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from in_reach.app.map_variant import parse_mvar_forge_labels, parse_mvar_header

MAP_VARIANT_EXTENSION = ".mvar"
MAPS_DIRNAME = "maps"
MAPS_MASTER_FILENAME = "master.json"
MAPS_FILENAME = "maps.json"

MASTER_MAPS_FILE_COMMENT = (
    "Every Forge map variant in-reach found across the personal/standard/hopper map-variant "
    "folders, regenerated wholesale whenever a project is scanned -- do not hand-edit."
)
MAPS_FILE_COMMENT = (
    "This project's maps/master.json -- unfiltered for now (no script_settings.json yet to "
    "filter against). Do not hand-edit."
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


def write_maps_json(entries: list[MapEntry], project_folder: Path) -> tuple[Path, Path]:
    """Writes ``entries`` to both ``<project_folder>/maps/master.json`` (the unfiltered scan) and
    ``<project_folder>/maps.json`` (identical for now -- see this module's own docstring).

    Args:
        entries: Scanned entries, as returned by :func:`scan_maps`.
        project_folder: The gametype project's own folder (the uuid-named folder, not
            ``.in-reach``).

    Returns:
        ``(master_path, maps_path)``.
    """
    master_path = _write_entries_json(
        entries, project_folder / MAPS_DIRNAME / MAPS_MASTER_FILENAME, MASTER_MAPS_FILE_COMMENT
    )
    maps_path = _write_entries_json(entries, project_folder / MAPS_FILENAME, MAPS_FILE_COMMENT)
    return master_path, maps_path
