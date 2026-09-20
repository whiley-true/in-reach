"""Checks that the module ``build.py`` installed is the one in-reach actually loads.

    python native/verify.py

Exits 0 and prints the module's path if ``in_reach.app.rvt.rvt_bridge`` loads ``_reachvarianttool`` from
``src/in_reach/app/rvt/native/``; otherwise prints why and exits 1. CI runs it between building and testing:
without it a module that failed to load just makes every native test *skip*, and one loaded from a different
copy of the package (a regular install in site-packages, say) would be tested in place of the one just built.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

INSTALL_DIR = Path(__file__).resolve().parent.parent / "src" / "in_reach" / "app" / "rvt" / "native"


def main() -> int:
    from in_reach.app.rvt import rvt_bridge

    try:
        module = rvt_bridge.get_rvt()  # not is_available(): that swallows the reason it failed
    except Exception:  # noqa: BLE001 -- whatever stopped it loading is the message
        traceback.print_exc()
        print("the built module did not load", file=sys.stderr)
        return 1

    loaded = Path(module.__file__).resolve()
    if loaded.parent != INSTALL_DIR.resolve():
        print(f"loaded {loaded}, not the module build.py installed in {INSTALL_DIR}", file=sys.stderr)
        return 1
    print(loaded)
    return 0


if __name__ == "__main__":
    sys.exit(main())
