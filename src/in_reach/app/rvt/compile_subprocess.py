"""Entry point for the isolated compile child process -- see
:mod:`in_reach.app.rvt.compile`'s own module docstring for why compiling runs here, in its own
process, rather than directly in whatever process (the GUI included) wants a
:class:`~in_reach.app.rvt.compile.BuildResult`.

Invoked as::

    python -m in_reach.app.rvt.compile_subprocess <project_dir> <folder> <0|1 save> <result_path>

Writes the resulting ``BuildResult`` as JSON to ``result_path`` (never stdout -- see
:func:`~in_reach.app.rvt.compile._run_compile_isolated`'s own docstring for why) and exits 0.
Deliberately does not try to catch every possible exception here: an ordinary Python exception
already can't happen from :func:`~in_reach.app.rvt.compile._run_compile_in_process` per its own
contract (it reports failures as a ``BuildResult`` instead of raising), and the one failure mode
this process boundary actually exists to contain -- a native access violation inside the bundled
``_reachvarianttool`` extension -- kills this process outright regardless of any Python-level
``try``/``except``; the parent (``_run_compile_isolated``) already treats a non-zero/crashed exit
code as its own reportable failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

from in_reach.app.rvt.compile import _run_compile_in_process


def main(argv: list[str]) -> int:
    project_dir = Path(argv[0])
    folder = Path(argv[1])
    save = argv[2] == "1"
    result_path = Path(argv[3])

    result = _run_compile_in_process(project_dir, folder, save=save)
    result_path.write_text(result.model_dump_json(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
