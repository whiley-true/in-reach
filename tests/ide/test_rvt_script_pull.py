"""The IDE side of pulling a script edited in ReachVariantTool back into ``script/output.txt``: what
:meth:`MainWindow._on_watched_bin_changed` does once the resync it runs has recorded that RVT changed the
script -- silently pull, ask first when that would lose something, or leave the file alone. The
bookkeeping is :mod:`in_reach.app.script_sync` (tested in ``tests/app/test_script_sync.py``); the real
native loop is ``tests/app/rvt/test_script_pull_end_to_end.py``. Here the resync is faked, so this runs
without the native extension.
"""
from pathlib import Path

import pytest

from in_reach.app import new_project, script_sync
from in_reach.ide.main_window import MainWindow


@pytest.fixture
def window(qtbot, tmp_path: Path):
    project_dir = tmp_path / ".in-reach"
    project_dir.mkdir()
    (project_dir / ".env").write_text("", encoding="utf-8")
    win = MainWindow(root_dir=tmp_path)
    qtbot.addWidget(win)
    win.show()
    return win


@pytest.fixture
def folder(window: MainWindow, tmp_path: Path) -> Path:
    """An open project whose last build's script was ``built`` and whose ``output.txt`` is ``mine``."""
    project_folder = tmp_path / "abcd1234"
    (project_folder / new_project.SETTINGS_DIRNAME).mkdir(parents=True)
    (project_folder / new_project.SCRIPT_DIRNAME).mkdir()
    script_sync.script_path(project_folder).write_text("mine\n", encoding="utf-8")
    script_sync.record_build(project_folder, "built\n")
    bin_path = new_project.compiled_variant_path(project_folder)
    bin_path.parent.mkdir(parents=True)
    bin_path.write_bytes(b"")
    window._on_project_opened(project_folder)
    return project_folder


def _rvt_saves(monkeypatch: pytest.MonkeyPatch, script: str) -> None:
    """Fakes the resync the watcher runs: RVT's saved ``.bin`` now holds ``script``."""
    monkeypatch.setattr(
        "in_reach.app.rvt.decompile.resync_from_bin",
        lambda bin_path, project_folder, **kwargs: script_sync.record_sync(project_folder, script),
    )


def _prompts(monkeypatch: pytest.MonkeyPatch, answer: bool) -> list[list[str]]:
    asked: list[list[str]] = []
    monkeypatch.setattr(MainWindow, "_confirm_pull_script", lambda self, reasons: asked.append(reasons) or answer)
    return asked


def _watch(window: MainWindow, folder: Path) -> None:
    window._on_watched_bin_changed(str(new_project.compiled_variant_path(folder)))


def _output_txt(folder: Path) -> str:
    return script_sync.read_script(folder)


def test_a_script_changed_in_rvt_replaces_output_txt_without_asking_when_nothing_is_lost(
    window: MainWindow, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _rvt_saves(monkeypatch, "edited in rvt\n")
    asked = _prompts(monkeypatch, answer=False)

    _watch(window, folder)

    assert asked == []
    assert _output_txt(folder) == "edited in rvt\n"


def test_a_save_that_left_the_script_alone_leaves_output_txt_alone(
    window: MainWindow, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _rvt_saves(monkeypatch, "built\n")
    asked = _prompts(monkeypatch, answer=True)

    _watch(window, folder)

    assert asked == []
    assert _output_txt(folder) == "mine\n"


def test_an_open_output_txt_tab_updates_in_place(
    window: MainWindow, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window.main_panel.active_pane.open_file(script_sync.script_path(folder))
    editor = window.main_panel.active_pane.widget(window.main_panel.active_pane.currentIndex())
    _rvt_saves(monkeypatch, "edited in rvt\n")

    _watch(window, folder)

    assert editor.toPlainText() == "edited in rvt\n"


def test_unapplied_edits_are_asked_about_and_kept_when_declined(
    window: MainWindow, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script_sync.script_path(folder).write_text("mine, edited since the build\n", encoding="utf-8")
    _rvt_saves(monkeypatch, "edited in rvt\n")
    asked = _prompts(monkeypatch, answer=False)

    _watch(window, folder)

    assert asked == [[script_sync.PullReason.UNAPPLIED_EDITS.value]]
    assert _output_txt(folder) == "mine, edited since the build\n"


def test_unapplied_edits_are_replaced_when_the_user_agrees(
    window: MainWindow, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script_sync.script_path(folder).write_text("mine, edited since the build\n", encoding="utf-8")
    _rvt_saves(monkeypatch, "edited in rvt\n")
    _prompts(monkeypatch, answer=True)

    _watch(window, folder)

    assert _output_txt(folder) == "edited in rvt\n"


def test_declining_is_remembered_so_the_next_save_does_not_ask_again(
    window: MainWindow, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script_sync.script_path(folder).write_text("mine, edited since the build\n", encoding="utf-8")
    _rvt_saves(monkeypatch, "edited in rvt\n")
    asked = _prompts(monkeypatch, answer=False)
    _watch(window, folder)

    _watch(window, folder)  # RVT saved again with the same script

    assert len(asked) == 1


def test_build_profile_directives_are_asked_about(
    window: MainWindow, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script_sync.script_path(folder).write_text("-- @if DEV\nx = 1\n-- @end\n", encoding="utf-8")
    script_sync.record_build(folder, "built\n")  # this .bin was built from exactly that output.txt
    _rvt_saves(monkeypatch, "edited in rvt\n")
    asked = _prompts(monkeypatch, answer=False)

    _watch(window, folder)

    assert asked == [[script_sync.PullReason.PROFILE_DIRECTIVES.value]]
    assert _output_txt(folder) == "-- @if DEV\nx = 1\n-- @end\n"


def test_unsaved_edits_in_an_open_output_txt_tab_are_asked_about_and_survive_a_decline(
    window: MainWindow, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window.main_panel.active_pane.open_file(script_sync.script_path(folder))
    editor = window.main_panel.active_pane.widget(window.main_panel.active_pane.currentIndex())
    editor.setPlainText("typed but never saved")
    editor.document().setModified(True)
    _rvt_saves(monkeypatch, "edited in rvt\n")
    asked = _prompts(monkeypatch, answer=False)

    _watch(window, folder)

    assert asked == [[script_sync.PullReason.UNSAVED_EDITS.value]]
    assert editor.toPlainText() == "typed but never saved"
    assert _output_txt(folder) == "mine\n"


def test_every_reason_is_listed_in_one_question(
    window: MainWindow, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script_sync.script_path(folder).write_text("-- @if DEV\nx = 1\n-- @end\n-- a note\nedited\n", encoding="utf-8")
    window.main_panel.active_pane.open_file(script_sync.script_path(folder))
    editor = window.main_panel.active_pane.widget(window.main_panel.active_pane.currentIndex())
    editor.document().setModified(True)
    _rvt_saves(monkeypatch, "edited in rvt\n")
    asked = _prompts(monkeypatch, answer=False)

    _watch(window, folder)

    assert asked == [
        [
            script_sync.PullReason.UNAPPLIED_EDITS.value,
            script_sync.PullReason.COMMENTS.value,
            script_sync.PullReason.PROFILE_DIRECTIVES.value,
            script_sync.PullReason.UNSAVED_EDITS.value,
        ]
    ]


def test_nothing_is_pulled_when_the_resync_fails(
    window: MainWindow, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_resync(bin_path, project_folder, **kwargs):
        script_sync.record_sync(project_folder, "half-written")
        raise RuntimeError("RVT was still writing the file")

    monkeypatch.setattr("in_reach.app.rvt.decompile.resync_from_bin", broken_resync)
    asked = _prompts(monkeypatch, answer=True)

    _watch(window, folder)

    assert asked == []
    assert _output_txt(folder) == "mine\n"


def test_a_pull_shows_up_as_an_uncommitted_change_rather_than_committing(
    window: MainWindow, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from in_reach.app import vcs

    vcs.init(folder)
    commits = len(vcs.history(folder))
    _rvt_saves(monkeypatch, "edited in rvt\n")

    _watch(window, folder)

    assert len(vcs.history(folder)) == commits
    assert "script/output.txt" in [change.path for change in vcs.uncommitted_changes(folder)]


def test_the_question_names_what_would_be_lost_and_both_choices(window: MainWindow, monkeypatch: pytest.MonkeyPatch) -> None:
    from PyQt6.QtWidgets import QMessageBox

    shown: dict[str, object] = {}

    def fake_exec(box) -> int:
        shown["text"] = box.text()
        shown["buttons"] = [button.text() for button in box.buttons()]
        box.button_clicked = box.buttons()[0]
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda box: box.button_clicked)

    answer = window._confirm_pull_script(["it would lose this", "and this"])

    assert answer is True  # the first button is "Use RVT's Script"
    assert shown["buttons"] == ["Use RVT's Script", "Keep Mine"]
    assert "- it would lose this" in shown["text"] and "- and this" in shown["text"]
