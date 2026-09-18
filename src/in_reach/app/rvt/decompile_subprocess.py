"""Entry point for the isolated decompile child process -- see
:mod:`in_reach.app.rvt.decompile`'s own module docstring for why decompiling runs here, in its own
process, rather than directly in whatever process (the GUI included) asked for it.

Invoked as::

    python -m in_reach.app.rvt.decompile_subprocess <into_project|resync> <request_path> <result_path>

``request_path`` is a JSON object written by
:func:`~in_reach.app.rvt.decompile._serialize_decompile_request`
(``bin_path``/``folder``/``category``/``category_icon``/``title``/``description``/``created_at``/
``map_entries``, every value already a plain JSON-safe type). Writes ``{"success": true}`` or
``{"success": false, "error": "..."}`` to ``result_path`` (never stdout -- same reasoning as
:mod:`in_reach.app.rvt.compile_subprocess`) and exits 0 either way; a non-zero exit (or none at all,
e.g. a crash) means this process never got the chance to write a result at all, which
:func:`~in_reach.app.rvt.decompile._run_decompile_isolated` treats as its own reportable failure --
that includes the one failure mode this isolation exists to contain, a native access violation
inside the bundled ``_reachvarianttool`` extension.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from datetime import datetime
from pathlib import Path

from in_reach.app.categories import EngineCategory, EngineIcon
from in_reach.app.maps_io import MapEntry
from in_reach.app.rvt.decompile import _decompile_into_project_in_process, _resync_from_bin_in_process

_MODES = {
    "into_project": _decompile_into_project_in_process,
    "resync": _resync_from_bin_in_process,
}


def main(argv: list[str]) -> int:
    mode = argv[0]
    request_path = Path(argv[1])
    result_path = Path(argv[2])

    request = json.loads(request_path.read_text(encoding="utf-8"))
    category_icon = request["category_icon"]
    created_at = request.get("created_at")

    try:
        _MODES[mode](
            Path(request["bin_path"]),
            Path(request["folder"]),
            category=EngineCategory(request["category"]),
            category_icon=EngineIcon(category_icon) if category_icon is not None else None,
            title=request["title"],
            description=request["description"],
            created_at=datetime.fromisoformat(created_at) if created_at is not None else None,
            map_entries=[MapEntry(**entry) for entry in request["map_entries"]],
        )
    except Exception as exc:  # noqa: BLE001 -- native/pydantic code can raise almost anything
        result_path.write_text(json.dumps({"success": False, "error": str(exc)}), encoding="utf-8")
        return 0

    result_path.write_text(json.dumps({"success": True}), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
