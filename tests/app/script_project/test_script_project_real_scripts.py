"""Real gametypes as script projects: the scripts the decompiler writes must pass the project checks and build.

A rule written from a design note rather than from a real script can reject what the game itself ships. IR007 once treated
every ``true``/``false`` as an unknown name, so ``current_object.set_hidden(true)`` -- what the decompiler writes, and what the
compiler accepts -- failed the check and blocked the build of any project made from a real gametype; IR010 (an unlabelled
``for each object``) was an error though shipped scripts do it. These tests turn every gametype in the fixtures into a
script project, so a rule that is too strict for real code fails here, not in someone's first project.
"""
import glob
from pathlib import Path

import pytest

from in_reach import api
from in_reach.app import new_project, project
from in_reach.app.rvt import rvt_bridge

_FIXTURES = sorted(glob.glob(str(Path(__file__).parents[1] / "rvt" / "resources" / "*" / "*.bin")))

pytestmark = pytest.mark.skipif(
    not (_FIXTURES and rvt_bridge.is_available()),
    reason="fixture .bin files or the native _reachvarianttool extension not available on this platform",
)


def _script_project(tmp_path: Path, bin_path: str) -> Path:
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir(parents=True)
    folder, warning = new_project.create_gametype_project(project_dir, Path(bin_path).stem, source_variant=Path(bin_path))
    assert warning is None
    api.create_script_project(folder)
    return folder


@pytest.mark.parametrize("bin_path", _FIXTURES, ids=[Path(p).stem for p in _FIXTURES])
def test_a_real_gametypes_script_passes_the_project_checks(tmp_path: Path, bin_path: str) -> None:
    folder = _script_project(tmp_path, bin_path)

    checked = api.check(folder)

    assert checked.ok, [str(d) for d in checked.errors]


@pytest.mark.parametrize("bin_path", _FIXTURES, ids=[Path(p).stem for p in _FIXTURES])
def test_a_real_gametypes_script_builds_as_a_project(tmp_path: Path, bin_path: str) -> None:
    folder = _script_project(tmp_path, bin_path)

    built = api.build(folder, dry_run=True)

    assert built.success, [str(d) for d in built.diagnostics if d.severity == "error"]


def test_the_yes_no_arguments_the_decompiler_writes_are_in_these_scripts() -> None:
    """The scripts these tests use really contain the construct the fix is about (or the tests prove nothing)."""
    from in_reach.app.rvt import decompile

    texts = []
    for bin_path in _FIXTURES:
        variant = rvt_bridge.get_rvt().load(bin_path)
        if variant.multiplayer is not None:
            texts.append(decompile.normalize_script_text(variant.decompile_script()))

    assert any("(true)" in t or ", true)" in t or "(false)" in t or ", false)" in t for t in texts)
