"""Editing the script in ReachVariantTool and keeping it: the whole loop, against real variants.

A script changed in RVT used to be lost: RVT saved the built ``.bin``, in-reach mirrored its *settings*
into ``settings/``, and the next Apply rebuilt the ``.bin`` from ``script/output.txt`` -- which RVT never
touched. These tests play RVT's part (native-compile a different script into the built ``.bin`` and save
it over the file), run the same resync the IDE's file watcher runs, and check the script comes back into
``output.txt`` and survives the next build. See :mod:`in_reach.app.script_sync`.
"""
import collections
import logging
import re
from pathlib import Path

import pytest

from in_reach.app import new_project, project, script_sync
from in_reach.app.rvt import compile as compile_module
from in_reach.app.rvt import decompile, rvt_bridge
from in_reach.app.rvt.decompile import normalize_script_text
from in_reach.app.script_sync import PullReason

_JUGGERNAUT_BIN = Path(__file__).parent / "resources" / "juggernaut" / "juggernaut.bin"

pytestmark = pytest.mark.skipif(
    not (_JUGGERNAUT_BIN.is_file() and rvt_bridge.is_available()),
    reason="fixture .bin not present, or native _reachvarianttool extension not available on this platform",
)

_MY_SCRIPT = "global.number[1] = 2\n"
_RVT_SCRIPT = "global.number[0] = 5\nif global.number[0] == 1 then\n   game.end_round()\nend\nglobal.number[2] = 7\n"
# A layout native builds with an ``inline:`` block, which is how RVT's own compiler writes it.
_RVT_INLINE_SCRIPT = (
    "for each player do\n"
    "   if current_player.number[0] == 1 then\n      current_player.number[1] += 1\n   end\n"
    "   current_player.number[0] = 2\n"
    "end\n"
)


def _new_project(tmp_path: Path) -> tuple[Path, Path]:
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir(parents=True)
    folder, warning = new_project.create_gametype_project(project_dir, "Pull Test", source_variant=_JUGGERNAUT_BIN)
    assert warning is None
    return project_dir, folder


def _set_script(folder: Path, text: str) -> None:
    script_sync.script_path(folder).write_text(text, encoding="utf-8")


def _apply(project_dir: Path, folder: Path, caplog=None) -> Path:
    result = compile_module._run_compile_in_process(project_dir, folder, save=True)
    assert result.success is True, compile_module.format_build_result(result)
    return Path(result.output_path)


def _rvt_saves(bin_path: Path, script: str | None) -> None:
    """RVT opening the built ``.bin``, (optionally) replacing its script with its own compile of
    ``script``, and saving it over the same file."""
    rvt = rvt_bridge.get_rvt()
    variant = rvt.load(str(bin_path))
    if script is not None:
        result = variant.multiplayer.compile_script(script)
        assert result.success, [m.text for m in list(result.errors) + list(result.fatal_errors)]
    variant.save(str(bin_path))


def _watcher_resync(bin_path: Path, folder: Path) -> tuple[script_sync.ScriptSnapshot | None, script_sync.ScriptSnapshot | None]:
    """What the IDE's file watcher does when the ``.bin`` changes: snapshot, resync, snapshot."""
    before = script_sync.read_snapshot(folder)
    decompile._resync_from_bin_in_process(bin_path, folder)
    return before, script_sync.read_snapshot(folder)


_STRUCTURE = re.compile(r"^(if |altif |alt$|do$|end$|for each |on |inline: |declare |function |$)")


def _statements(text: str) -> collections.Counter:
    return collections.Counter(l.strip() for l in text.splitlines() if not _STRUCTURE.match(l.strip()))


def _built_script(bin_path: Path) -> str:
    return normalize_script_text(rvt_bridge.get_rvt().load(str(bin_path)).decompile_script())


# -- what gets recorded ----------------------------------------------------------------------------------


def test_a_new_project_starts_with_a_snapshot_matching_its_output_txt(tmp_path: Path) -> None:
    _, folder = _new_project(tmp_path)

    snapshot = script_sync.read_snapshot(folder)

    assert snapshot.text == script_sync.read_script(folder)
    assert snapshot.source_sha256 is not None


def test_an_apply_records_the_built_scripts_text_and_output_txts_digest(tmp_path: Path) -> None:
    project_dir, folder = _new_project(tmp_path)
    _set_script(folder, _MY_SCRIPT)

    bin_path = _apply(project_dir, folder)

    snapshot = script_sync.read_snapshot(folder)
    assert snapshot.text == _built_script(bin_path)
    assert "global.number[1] = 2" in snapshot.text
    script_sync.record_build(folder, snapshot.text)  # recording again over an unchanged output.txt ...
    assert script_sync.read_snapshot(folder) == snapshot  # ... gives the digest the Apply recorded


# -- the round trip --------------------------------------------------------------------------------------


def test_a_script_edited_in_rvt_comes_back_and_survives_the_next_apply(tmp_path: Path) -> None:
    project_dir, folder = _new_project(tmp_path)
    _set_script(folder, _MY_SCRIPT)
    bin_path = _apply(project_dir, folder)

    _rvt_saves(bin_path, _RVT_SCRIPT)
    before, after = _watcher_resync(bin_path, folder)
    plan = script_sync.plan_pull(folder, before, after)

    assert plan == script_sync.PullPlan(needed=True, reasons=())  # nothing here to lose: pull silently
    script_sync.pull(folder, after)
    pulled = script_sync.read_script(folder)
    assert "global.number[0] = 5" in pulled and "global.number[2] = 7" in pulled
    assert "global.number[1] = 2" not in pulled  # the script that was in output.txt is gone, by design

    rebuilt = _apply(project_dir, folder)

    # Every statement RVT's script had is in the rebuilt .bin, none of the old script's: what "keep
    # working here" means.
    assert _statements(_built_script(rebuilt)) == _statements(pulled)


def test_the_pulled_script_builds_in_house_rather_than_falling_back_to_native(tmp_path: Path, caplog) -> None:
    """RVT's own compiler lays a script out differently (``inline: if ...``); that text has to parse and
    compile here, or every RVT edit would silently go through the native compiler's own quirks."""
    project_dir, folder = _new_project(tmp_path)
    _set_script(folder, _MY_SCRIPT)
    bin_path = _apply(project_dir, folder)
    _rvt_saves(bin_path, _RVT_INLINE_SCRIPT)
    before, after = _watcher_resync(bin_path, folder)
    script_sync.pull(folder, after)
    assert "inline:" in script_sync.read_script(folder), "the script should be RVT's own, laid out its way"

    with caplog.at_level(logging.INFO, logger="in_reach"):
        _apply(project_dir, folder)

    assert not [record for record in caplog.records if "falling back" in record.getMessage()]


def test_saving_in_rvt_without_touching_the_script_pulls_nothing(tmp_path: Path) -> None:
    project_dir, folder = _new_project(tmp_path)
    _set_script(folder, "-- @if DEV\nglobal.number[1] = 2\n-- @end\n")  # directives a pull would destroy
    bin_path = _apply(project_dir, folder)

    _rvt_saves(bin_path, None)  # e.g. RVT's header or options edited, script left alone
    before, after = _watcher_resync(bin_path, folder)

    assert not script_sync.plan_pull(folder, before, after).needed


def test_our_own_apply_is_not_mistaken_for_an_rvt_edit(tmp_path: Path) -> None:
    """The file watcher fires on in-reach's own writes to the .bin too."""
    project_dir, folder = _new_project(tmp_path)
    _set_script(folder, _MY_SCRIPT)
    bin_path = _apply(project_dir, folder)

    before, after = _watcher_resync(bin_path, folder)

    assert not script_sync.plan_pull(folder, before, after).needed


# -- when a pull would lose something --------------------------------------------------------------------


def test_edits_made_here_since_the_apply_are_flagged_before_rvts_script_replaces_them(tmp_path: Path) -> None:
    project_dir, folder = _new_project(tmp_path)
    _set_script(folder, _MY_SCRIPT)
    bin_path = _apply(project_dir, folder)
    _set_script(folder, _MY_SCRIPT + "global.number[2] = 9\n")  # typed after applying, not yet built

    _rvt_saves(bin_path, _RVT_SCRIPT)
    before, after = _watcher_resync(bin_path, folder)

    assert script_sync.plan_pull(folder, before, after).reasons == (PullReason.UNAPPLIED_EDITS,)


def test_declining_the_pull_leaves_output_txt_and_the_next_apply_uses_it(tmp_path: Path) -> None:
    project_dir, folder = _new_project(tmp_path)
    _set_script(folder, _MY_SCRIPT)
    bin_path = _apply(project_dir, folder)
    _rvt_saves(bin_path, _RVT_SCRIPT)
    _watcher_resync(bin_path, folder)  # ... and the user answers "Keep Mine": nothing is pulled

    rebuilt = _apply(project_dir, folder)

    assert script_sync.read_script(folder) == _MY_SCRIPT
    assert "global.number[1] = 2" in _built_script(rebuilt)
    assert "game.end_round()" not in _built_script(rebuilt)


def test_settings_edited_in_rvt_still_reach_settings_json_alongside_the_script(tmp_path: Path) -> None:
    """The existing mirror of RVT's settings must keep working now that the script comes back too."""
    import json

    project_dir, folder = _new_project(tmp_path)
    _set_script(folder, _MY_SCRIPT)
    bin_path = _apply(project_dir, folder)
    rvt = rvt_bridge.get_rvt()
    variant = rvt.load(str(bin_path))
    variant.multiplayer.compile_script(_RVT_SCRIPT)
    variant.save(str(bin_path))

    decompile._resync_from_bin_in_process(bin_path, folder)

    settings = json.loads((folder / new_project.SETTINGS_DIRNAME / "settings.json").read_text(encoding="utf-8"))
    assert settings["multiplayer"] is not None
    assert "global.number[0] = 5" in script_sync.read_snapshot(folder).text
