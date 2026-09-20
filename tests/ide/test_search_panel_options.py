"""SearchPanel's VSCode-style search options (PROMPT.md: search.png) -- match case/whole word/regex,
the collapsible replace row (preserve case, replace all), and the collapsible files-to-include/
exclude details (including "Search only in Open Editors")."""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtCore import Qt

from in_reach.ide.search_panel import SearchPanel


@pytest.fixture
def panel(qtbot) -> SearchPanel:
    widget = SearchPanel()
    qtbot.addWidget(widget)
    return widget


def _project(tmp_path: Path) -> Path:
    (tmp_path / "settings").mkdir()
    (tmp_path / "settings" / "settings.json").write_text('{"Needle": 1}\nneedles\n', encoding="utf-8")
    (tmp_path / "notes.txt").write_text("a needle here\n", encoding="utf-8")
    return tmp_path


# -- option toggles -------------------------------------------------------------------------------


def test_option_toggles_exist_with_vscode_tooltips(panel: SearchPanel) -> None:
    assert panel.match_case_button.toolTip() == "Match Case"
    assert panel.whole_word_button.toolTip() == "Match Whole Word"
    assert panel.regex_button.toolTip() == "Use Regular Expression"
    assert panel.preserve_case_button.toolTip() == "Preserve Case"
    assert panel.only_open_editors_button.toolTip() == "Search only in Open Editors"
    for button in (
        panel.match_case_button,
        panel.whole_word_button,
        panel.regex_button,
        panel.preserve_case_button,
        panel.only_open_editors_button,
    ):
        assert button.isCheckable()


def test_match_case_toggle_reruns_the_search(panel: SearchPanel, tmp_path: Path) -> None:
    panel.set_project_folder(_project(tmp_path))
    panel.search_edit.setText("needle")
    insensitive = panel.results_list.count()

    panel.match_case_button.setChecked(True)

    assert insensitive == 3  # "Needle", "needles", "needle"
    assert panel.results_list.count() == 2  # "Needle" no longer matches


def test_whole_word_toggle_drops_substring_hits(panel: SearchPanel, tmp_path: Path) -> None:
    panel.set_project_folder(_project(tmp_path))
    panel.search_edit.setText("needle")

    panel.whole_word_button.setChecked(True)

    assert panel.results_list.count() == 2  # "needles" no longer matches


def test_regex_toggle_treats_the_query_as_a_pattern(panel: SearchPanel, tmp_path: Path) -> None:
    panel.set_project_folder(_project(tmp_path))
    panel.search_edit.setText(r"need\w+")
    assert panel.results_list.count() == 0

    panel.regex_button.setChecked(True)

    assert panel.results_list.count() >= 1


def test_invalid_regex_shows_a_message_instead_of_results(panel: SearchPanel, tmp_path: Path) -> None:
    panel.set_project_folder(_project(tmp_path))
    panel.regex_button.setChecked(True)

    panel.search_edit.setText("(")

    assert panel.results_list.count() == 0
    assert "Invalid regular expression" in panel.status_label.text()


def test_status_reports_result_and_file_counts(panel: SearchPanel, tmp_path: Path) -> None:
    panel.set_project_folder(_project(tmp_path))

    panel.search_edit.setText("needle")

    assert panel.status_label.text() == "3 results in 2 files"


def test_option_buttons_sit_inside_the_query_box(panel: SearchPanel) -> None:
    for button in (panel.match_case_button, panel.whole_word_button, panel.regex_button):
        assert button.parent() is panel.search_edit
    assert panel.preserve_case_button.parent() is panel.replace_edit
    assert panel.only_open_editors_button.parent() is panel.include_edit


def test_typed_text_is_kept_clear_of_the_docked_buttons(panel: SearchPanel) -> None:
    margins = panel.search_edit.textMargins()

    assert margins.right() >= sum(
        b.sizeHint().width() for b in (panel.match_case_button, panel.whole_word_button, panel.regex_button)
    )


# -- replace row ----------------------------------------------------------------------------------


def test_replace_row_is_collapsed_until_the_chevron_is_toggled(panel: SearchPanel) -> None:
    panel.show()
    assert panel.replace_edit.isVisible() is False
    assert panel.replace_all_button.isVisible() is False

    panel.expand_replace_button.click()

    assert panel.replace_edit.isVisible() is True
    assert panel.replace_all_button.isVisible() is True
    assert panel.expand_replace_button.arrowType() == Qt.ArrowType.DownArrow

    panel.expand_replace_button.click()

    assert panel.replace_edit.isVisible() is False
    assert panel.expand_replace_button.arrowType() == Qt.ArrowType.RightArrow


def test_preserve_case_toggle_drives_replace_all(panel: SearchPanel, tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("CAT Cat cat\n", encoding="utf-8")
    panel.set_project_folder(tmp_path)
    panel.ask_confirm_replace = lambda _count: True  # type: ignore[method-assign]
    panel.search_edit.setText("cat")
    panel.replace_edit.setText("dog")
    panel.preserve_case_button.setChecked(True)

    panel.replace_all()

    assert (tmp_path / "a.txt").read_text(encoding="utf-8").strip() == "DOG Dog dog"


def test_replace_all_respects_the_match_options(panel: SearchPanel, tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("cat concat\n", encoding="utf-8")
    panel.set_project_folder(tmp_path)
    panel.ask_confirm_replace = lambda _count: True  # type: ignore[method-assign]
    panel.whole_word_button.setChecked(True)
    panel.search_edit.setText("cat")
    panel.replace_edit.setText("dog")

    panel.replace_all()

    assert (tmp_path / "a.txt").read_text(encoding="utf-8").strip() == "dog concat"


# -- search details (files to include / exclude) --------------------------------------------------


def test_details_are_hidden_until_toggled(panel: SearchPanel) -> None:
    panel.show()
    assert panel.include_edit.isVisible() is False
    assert panel.exclude_edit.isVisible() is False

    panel.details_button.click()

    assert panel.include_edit.isVisible() is True
    assert panel.exclude_edit.isVisible() is True
    assert panel.only_open_editors_button.isVisible() is True

    panel.details_button.click()

    assert panel.include_edit.isVisible() is False


def test_include_and_exclude_boxes_show_example_placeholder_text(panel: SearchPanel) -> None:
    for edit in (panel.include_edit, panel.exclude_edit):
        assert "*.json" in edit.placeholderText()
        assert "src/a/file" in edit.placeholderText()


def test_include_glob_narrows_results(panel: SearchPanel, tmp_path: Path) -> None:
    panel.set_project_folder(_project(tmp_path))
    panel.search_edit.setText("needle")

    panel.include_edit.setText("*.txt")

    assert panel.results_list.count() == 1
    assert "notes.txt" in panel.results_list.item(0).text()


def test_exclude_glob_narrows_results(panel: SearchPanel, tmp_path: Path) -> None:
    panel.set_project_folder(_project(tmp_path))
    panel.search_edit.setText("needle")

    panel.exclude_edit.setText("*.json")

    assert panel.results_list.count() == 1
    assert "notes.txt" in panel.results_list.item(0).text()


def test_only_open_editors_limits_the_search_to_the_provided_paths(panel: SearchPanel, tmp_path: Path) -> None:
    root = _project(tmp_path)
    panel.set_project_folder(root)
    panel.set_open_paths_provider(lambda: [root / "notes.txt"])
    panel.search_edit.setText("needle")

    panel.only_open_editors_button.setChecked(True)

    assert panel.results_list.count() == 1
    assert "notes.txt" in panel.results_list.item(0).text()
    assert "open editors" in panel.status_label.text()


def test_only_open_editors_with_nothing_open_finds_nothing(panel: SearchPanel, tmp_path: Path) -> None:
    panel.set_project_folder(_project(tmp_path))
    panel.search_edit.setText("needle")

    panel.only_open_editors_button.setChecked(True)

    assert panel.results_list.count() == 0


def test_only_open_editors_provider_is_read_fresh_on_every_search(panel: SearchPanel, tmp_path: Path) -> None:
    root = _project(tmp_path)
    panel.set_project_folder(root)
    open_now: list[Path] = []
    panel.set_open_paths_provider(lambda: list(open_now))
    panel.only_open_editors_button.setChecked(True)
    panel.search_edit.setText("needle")
    assert panel.results_list.count() == 0

    open_now.append(root / "notes.txt")
    panel.search_edit.setText("needle ")  # any edit re-runs the search
    panel.search_edit.setText("needle")

    assert panel.results_list.count() == 1


def test_new_controls_disable_with_no_project(panel: SearchPanel, tmp_path: Path) -> None:
    panel.set_project_folder(tmp_path)
    panel.set_project_folder(None)

    for widget in (
        panel.match_case_button,
        panel.whole_word_button,
        panel.regex_button,
        panel.include_edit,
        panel.exclude_edit,
    ):
        assert widget.isEnabled() is False
