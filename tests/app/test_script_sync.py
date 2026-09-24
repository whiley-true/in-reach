"""Pulling a script edited in ReachVariantTool back into ``script/output.mgl``: the bookkeeping that
decides *whether* RVT changed the script and *what a pull would cost* -- see
:mod:`in_reach.app.script_sync` for why, and ``tests/app/rvt/test_script_pull_end_to_end.py`` for the real
native round trip.
"""
from pathlib import Path

import pytest

from in_reach.app import new_project, script_preprocess, script_sync
from in_reach.app.script_sync import PullReason, ScriptSnapshot


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    (tmp_path / new_project.SCRIPT_DIRNAME).mkdir()
    return tmp_path


def _write_script(folder: Path, text: str) -> None:
    script_sync.script_path(folder).write_text(text, encoding="utf-8", newline="")


def test_the_script_filename_matches_the_one_decompile_writes() -> None:
    from in_reach.app.rvt import decompile

    assert script_sync.SCRIPT_FILENAME == decompile.SCRIPT_FILENAME


# -- snapshots -----------------------------------------------------------------------------------------


def test_there_is_no_snapshot_until_one_is_recorded(folder: Path) -> None:
    assert script_sync.read_snapshot(folder) is None


def test_a_build_records_the_scripts_text_and_which_output_txt_it_came_from(folder: Path) -> None:
    _write_script(folder, "global.number[0] = 1\n")

    script_sync.record_build(folder, "global.number[0] = 1\r\n")

    snapshot = script_sync.read_snapshot(folder)
    assert snapshot.text == "global.number[0] = 1\n"  # normalized to \n
    assert snapshot.source_sha256 is not None


def test_the_digest_ignores_line_endings(folder: Path) -> None:
    _write_script(folder, "a\r\nb\r\n")
    script_sync.record_build(folder, "x")
    crlf = script_sync.read_snapshot(folder).source_sha256

    _write_script(folder, "a\nb\n")
    script_sync.record_build(folder, "x")

    assert script_sync.read_snapshot(folder).source_sha256 == crlf


def test_a_sync_keeps_the_digest_of_the_last_build(folder: Path) -> None:
    _write_script(folder, "mine\n")
    script_sync.record_build(folder, "built\n")
    digest = script_sync.read_snapshot(folder).source_sha256

    _write_script(folder, "edited afterwards\n")  # must not be mistaken for what the .bin came from
    script_sync.record_sync(folder, "from rvt\n")

    assert script_sync.read_snapshot(folder) == ScriptSnapshot("from rvt\n", digest)


def test_a_sync_with_no_earlier_build_has_no_digest(folder: Path) -> None:
    script_sync.record_sync(folder, "from rvt\n")

    assert script_sync.read_snapshot(folder) == ScriptSnapshot("from rvt\n", None)


@pytest.mark.parametrize("content", ["not json", "[]", '{"nope": 1}'])
def test_a_damaged_snapshot_reads_as_none(folder: Path, content: str) -> None:
    path = script_sync.snapshot_path(folder)
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")

    assert script_sync.read_snapshot(folder) is None


# -- plan_pull -----------------------------------------------------------------------------------------


def _snapshots(folder: Path, *, built: str, rvt: str) -> tuple[ScriptSnapshot, ScriptSnapshot]:
    """The snapshot a build left, then the one an RVT-save resync leaves."""
    script_sync.record_build(folder, built)
    before = script_sync.read_snapshot(folder)
    script_sync.record_sync(folder, rvt)
    return before, script_sync.read_snapshot(folder)


def test_a_save_that_left_the_script_alone_pulls_nothing(folder: Path) -> None:
    _write_script(folder, "mine\n")
    before, after = _snapshots(folder, built="built\n", rvt="built\n")

    assert script_sync.plan_pull(folder, before, after) == script_sync.PullPlan(needed=False)


def test_there_is_nothing_to_compare_against_without_an_earlier_snapshot(folder: Path) -> None:
    _write_script(folder, "mine\n")
    script_sync.record_sync(folder, "from rvt\n")

    assert not script_sync.plan_pull(folder, None, script_sync.read_snapshot(folder)).needed


def test_a_changed_script_over_an_untouched_output_txt_pulls_silently(folder: Path) -> None:
    _write_script(folder, "mine\n")
    before, after = _snapshots(folder, built="built\n", rvt="edited in rvt\n")

    assert script_sync.plan_pull(folder, before, after) == script_sync.PullPlan(needed=True, reasons=())


def test_edits_to_output_txt_since_the_build_are_a_reason_to_ask(folder: Path) -> None:
    _write_script(folder, "mine\n")
    before, after = _snapshots(folder, built="built\n", rvt="edited in rvt\n")
    _write_script(folder, "mine, then edited here too\n")

    plan = script_sync.plan_pull(folder, before, after)

    assert plan == script_sync.PullPlan(needed=True, reasons=(PullReason.UNAPPLIED_EDITS,))


def test_build_profile_directives_are_a_reason_to_ask(folder: Path) -> None:
    _write_script(folder, "-- @if DEV\nglobal.number[0] = 1\n-- @end\n")
    before, after = _snapshots(folder, built="global.number[0] = 1\n", rvt="global.number[0] = 2\n")

    plan = script_sync.plan_pull(folder, before, after)

    assert plan == script_sync.PullPlan(needed=True, reasons=(PullReason.ENV_DIRECTIVES,))


def test_a_constant_placeholder_counts_as_a_directive(folder: Path) -> None:
    _write_script(folder, "global.number[0] = ${LIMIT}\n")
    before, after = _snapshots(folder, built="global.number[0] = 5\n", rvt="global.number[0] = 6\n")

    assert PullReason.ENV_DIRECTIVES in script_sync.plan_pull(folder, before, after).reasons


def test_comments_are_a_reason_to_ask(folder: Path) -> None:
    """RVT's script never has any, so a silent pull would delete the only copy of them."""
    _write_script(folder, "-- why this is 2\nglobal.number[0] = 2\n")
    before, after = _snapshots(folder, built="global.number[0] = 2\n", rvt="global.number[0] = 3\n")

    plan = script_sync.plan_pull(folder, before, after)

    assert plan == script_sync.PullPlan(needed=True, reasons=(PullReason.COMMENTS,))


def test_a_trailing_comment_counts_too(folder: Path) -> None:
    _write_script(folder, "global.number[0] = 2 -- because\n")
    before, after = _snapshots(folder, built="global.number[0] = 2\n", rvt="global.number[0] = 3\n")

    assert PullReason.COMMENTS in script_sync.plan_pull(folder, before, after).reasons


def test_all_the_reasons_are_reported_together(folder: Path) -> None:
    _write_script(folder, "-- @if DEV\nx = 1\n-- @end\n-- a note\n")
    before, after = _snapshots(folder, built="x = 1\n", rvt="x = 2\n")
    _write_script(folder, "-- @if DEV\nx = 1\n-- @end\n-- a note\nedited\n")

    reasons = script_sync.plan_pull(folder, before, after).reasons

    assert reasons == (PullReason.UNAPPLIED_EDITS, PullReason.COMMENTS, PullReason.ENV_DIRECTIVES)


def test_output_txt_that_already_says_what_rvt_says_needs_no_pull(folder: Path) -> None:
    _write_script(folder, "same\n")
    before, after = _snapshots(folder, built="built\n", rvt="same\n")

    assert not script_sync.plan_pull(folder, before, after).needed


def test_a_missing_output_txt_is_simply_replaced(folder: Path) -> None:
    before, after = _snapshots(folder, built="built\n", rvt="edited in rvt\n")

    assert script_sync.plan_pull(folder, before, after) == script_sync.PullPlan(needed=True, reasons=())


# -- pull ----------------------------------------------------------------------------------------------


def test_a_pull_replaces_output_txt_and_records_that_it_now_matches_the_bin(folder: Path) -> None:
    _write_script(folder, "mine\n")
    _, after = _snapshots(folder, built="built\n", rvt="edited in rvt\n")

    script_sync.pull(folder, after)

    assert script_sync.read_script(folder) == "edited in rvt\n"
    assert script_sync.read_snapshot(folder).text == "edited in rvt\n"


def test_after_a_pull_a_later_save_without_script_changes_leaves_output_txt_alone(folder: Path) -> None:
    """The point of recording the pull: otherwise every RVT save afterwards would look like an edit."""
    _write_script(folder, "mine\n")
    _, after = _snapshots(folder, built="built\n", rvt="edited in rvt\n")
    script_sync.pull(folder, after)
    _write_script(folder, "edited in rvt\nthen typed here\n")  # work after the pull
    before = script_sync.read_snapshot(folder)

    script_sync.record_sync(folder, "edited in rvt\n")  # RVT saved again, script untouched

    assert not script_sync.plan_pull(folder, before, script_sync.read_snapshot(folder)).needed
    assert script_sync.read_script(folder) == "edited in rvt\nthen typed here\n"


def test_a_pull_creates_the_script_folder_if_it_is_missing(tmp_path: Path) -> None:
    script_sync.pull(tmp_path, ScriptSnapshot("text\n", None))

    assert script_sync.read_script(tmp_path) == "text\n"


# -- script_preprocess.has_comments / uses_directives --------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("global.number[0] = 1\n", False),
        ("-- a comment\nx = 1\n", True),
        ("x = 1 -- trailing\n", True),
        ('send_incident("a -- b")\n', False),  # inside a string, not a comment
        ("-- @if DEV\nx = 1\n-- @end\n", False),  # directives are uses_directives()'s
        ("-- @if DEV\n-- a real comment\n-- @end\n", True),
        ("", False),
    ],
)
def test_has_comments(source: str, expected: bool) -> None:
    assert script_preprocess.has_comments(source) is expected



@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("global.number[0] = 1\n", False),
        ("-- an ordinary comment\nx = 1\n", False),
        ("-- @if DEV\nx = 1\n-- @end\n", True),
        ("   --   @else\n", True),
        ("global.number[0] = ${LIMIT}\n", True),
        ('send_incident("${NAME}")\n', True),
        ("x = 1 -- @if not at the start of a line\n", False),
        ("", False),
    ],
)
def test_uses_directives(source: str, expected: bool) -> None:
    assert script_preprocess.uses_directives(source) is expected


# -- linked projects ------------------------------------------------------------------------------------


def test_a_linked_project_is_never_pulled_into(folder: Path) -> None:
    """Its script is built from blocks and modules; output.mgl isn't the source, so an RVT change to the built
    script has nowhere to go."""
    _write_script(folder, "mine\n")
    before, after = _snapshots(folder, built="built\n", rvt="edited in rvt\n")
    assert script_sync.plan_pull(folder, before, after).needed  # a single-file project would pull this

    (folder / new_project.SCRIPT_DIRNAME / "project.toml").write_text("", encoding="utf-8")

    assert script_sync.plan_pull(folder, before, after) == script_sync.PullPlan(needed=False)
