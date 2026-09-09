from pathlib import Path

import pytest

from in_reach.ide.search_panel import SearchPanel


@pytest.fixture
def panel(qtbot) -> SearchPanel:
    widget = SearchPanel()
    qtbot.addWidget(widget)
    return widget


def test_starts_disabled_with_no_project(panel: SearchPanel) -> None:
    assert panel.search_edit.isEnabled() is False
    assert panel.replace_edit.isEnabled() is False
    assert panel.replace_all_button.isEnabled() is False
    assert panel.results_list.isEnabled() is False
    assert "No project" in panel.status_label.text()


def test_set_project_folder_enables_the_controls(panel: SearchPanel, tmp_path: Path) -> None:
    panel.set_project_folder(tmp_path)

    assert panel.search_edit.isEnabled() is True
    assert panel.replace_edit.isEnabled() is True
    assert panel.replace_all_button.isEnabled() is True
    assert panel.results_list.isEnabled() is True


def test_set_project_folder_none_disables_again(panel: SearchPanel, tmp_path: Path) -> None:
    panel.set_project_folder(tmp_path)
    panel.set_project_folder(None)

    assert panel.search_edit.isEnabled() is False
    assert "No project" in panel.status_label.text()


def test_typing_a_query_populates_results_live(panel: SearchPanel, tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("find this needle please\n", encoding="utf-8")
    panel.set_project_folder(tmp_path)

    panel.search_edit.setText("needle")

    assert panel.results_list.count() == 1
    assert "notes.txt:1" in panel.results_list.item(0).text()
    assert "1 result" in panel.status_label.text()


def test_result_text_shows_a_path_relative_to_the_project(panel: SearchPanel, tmp_path: Path) -> None:
    nested = tmp_path / "script"
    nested.mkdir(parents=True)
    (nested / "output.txt").write_text("needle\n", encoding="utf-8")
    panel.set_project_folder(tmp_path)

    panel.search_edit.setText("needle")

    assert panel.results_list.item(0).text().startswith(str(Path("script") / "output.txt"))


def test_clearing_the_query_clears_results(panel: SearchPanel, tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("needle\n", encoding="utf-8")
    panel.set_project_folder(tmp_path)
    panel.search_edit.setText("needle")
    assert panel.results_list.count() == 1

    panel.search_edit.setText("")

    assert panel.results_list.count() == 0
    assert panel.status_label.text() == ""


def test_activating_a_result_emits_file_activated_with_its_line(panel: SearchPanel, tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("one\ntwo needle three\n", encoding="utf-8")
    panel.set_project_folder(tmp_path)
    panel.search_edit.setText("needle")
    activated = []
    panel.file_activated.connect(lambda path, line: activated.append((path, line)))

    panel.results_list.itemActivated.emit(panel.results_list.item(0))

    assert activated == [(tmp_path / "notes.txt", 2)]


# -- replace all ------------------------------------------------------------------------------


def test_replace_all_confirms_then_rewrites_matching_files(
    panel: SearchPanel, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "notes.txt").write_text("hello world\n", encoding="utf-8")
    panel.set_project_folder(tmp_path)
    panel.search_edit.setText("hello")
    panel.replace_edit.setText("goodbye")
    monkeypatch.setattr(SearchPanel, "ask_confirm_replace", lambda self, count: True)

    panel.replace_all()

    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "goodbye world\n"
    # Re-searched afterward -- "hello" no longer matches anything.
    assert panel.results_list.count() == 0


def test_replace_all_does_nothing_if_the_confirmation_is_declined(
    panel: SearchPanel, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "notes.txt").write_text("hello world\n", encoding="utf-8")
    panel.set_project_folder(tmp_path)
    panel.search_edit.setText("hello")
    panel.replace_edit.setText("goodbye")
    monkeypatch.setattr(SearchPanel, "ask_confirm_replace", lambda self, count: False)

    panel.replace_all()

    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "hello world\n"


def test_replace_all_with_no_matches_never_prompts(
    panel: SearchPanel, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    panel.set_project_folder(tmp_path)
    panel.search_edit.setText("nothing-matches-this")
    monkeypatch.setattr(
        SearchPanel, "ask_confirm_replace", lambda self, count: pytest.fail("should not have asked")
    )

    panel.replace_all()  # must not raise via the monkeypatched fail()


def test_ask_confirm_replace_passes_the_match_count_into_the_message(
    panel: SearchPanel, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a.txt").write_text("x\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("x\n", encoding="utf-8")
    panel.set_project_folder(tmp_path)
    panel.search_edit.setText("x")
    seen = []

    def fake_question(*args, **kwargs):
        seen.append(args[2])
        from PyQt6.QtWidgets import QMessageBox

        return QMessageBox.StandardButton.No

    monkeypatch.setattr("in_reach.ide.search_panel.QMessageBox.question", fake_question)

    panel.replace_all()

    assert len(seen) == 1
    assert "2 occurrences" in seen[0]


# -- text scale -------------------------------------------------------------------------------


def test_panel_font_is_10_percent_smaller_than_the_app_font(panel: SearchPanel) -> None:
    from PyQt6.QtWidgets import QApplication

    app_size = QApplication.instance().font().pointSizeF()

    assert panel.font().pointSizeF() == pytest.approx(app_size * SearchPanel.TEXT_SCALE)


def test_refresh_font_scale_tracks_a_later_app_font_change(panel: SearchPanel) -> None:
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    original = QFont(app.font())
    try:
        bigger = QFont(original)
        bigger.setPointSizeF(original.pointSizeF() * 2)
        app.setFont(bigger)

        panel.refresh_font_scale()

        assert panel.font().pointSizeF() == pytest.approx(bigger.pointSizeF() * SearchPanel.TEXT_SCALE)
    finally:
        app.setFont(original)
