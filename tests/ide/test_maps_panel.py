"""Tests for :mod:`in_reach.ide.maps_panel` (PROMPT.md: "under maps section, please add url slugs for
Map Variants, Hopper Variants and User Maps, please also add a button for In-Reach maps (which should
be added to settings and quick launch built-in buttons) ... it should point to .in-reach maps")."""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtWidgets import QMessageBox

from in_reach.app import env_file, system_verify
from in_reach.ide.explorer import ExplorerPanel
from in_reach.ide.main_window import MainWindow
from in_reach.ide.maps_panel import SLUGS, MapsPanel


@pytest.fixture
def panel(qtbot) -> MapsPanel:
    widget = MapsPanel()
    qtbot.addWidget(widget)
    widget.resize(400, 300)
    widget.show()
    return widget


def test_has_a_slug_for_each_of_the_three_map_folders(panel: MapsPanel) -> None:
    assert [heading for heading, _key in SLUGS] == ["Map Variants", "Hopper Variants", "User Maps"]
    assert set(panel.slug_buttons) == {
        system_verify.STANDARD_MAP_VARIANTS_KEY,
        system_verify.HOPPER_MAP_VARIANTS_KEY,
        system_verify.PERSONAL_MAPS_KEY,
    }


def test_slugs_start_unresolved_and_disabled(panel: MapsPanel) -> None:
    for slug in panel.slug_buttons.values():
        assert slug.isEnabled() is False
        # full_text, not text(): the displayed text is middle-elided to the button's width, so how much of it
        # survives depends on the platform's font ("Not set --  em Settings" under Windows' offscreen plugin).
        assert "Verify System Settings" in slug.full_text


def test_set_paths_shows_each_path_as_a_clickable_slug(panel: MapsPanel) -> None:
    panel.set_paths(
        {
            system_verify.STANDARD_MAP_VARIANTS_KEY: r"C:\Steam\haloreach\map_variants",
            system_verify.HOPPER_MAP_VARIANTS_KEY: r"C:\Steam\haloreach\hopper_map_variants",
            system_verify.PERSONAL_MAPS_KEY: r"C:\Users\me\LocalFiles\abc\HaloReach\Map",
        }
    )

    standard = panel.slug_buttons[system_verify.STANDARD_MAP_VARIANTS_KEY]
    assert standard.isEnabled() is True
    assert standard.full_text == r"C:\Steam\haloreach\map_variants"
    assert standard.toolTip() == r"C:\Steam\haloreach\map_variants"
    assert "hopper_map_variants" in panel.slug_buttons[system_verify.HOPPER_MAP_VARIANTS_KEY].toolTip()


def test_a_blank_path_leaves_that_slug_unresolved(panel: MapsPanel) -> None:
    panel.set_paths({system_verify.STANDARD_MAP_VARIANTS_KEY: r"C:\maps", system_verify.PERSONAL_MAPS_KEY: ""})

    assert panel.slug_buttons[system_verify.STANDARD_MAP_VARIANTS_KEY].isEnabled() is True
    assert panel.slug_buttons[system_verify.PERSONAL_MAPS_KEY].isEnabled() is False
    assert panel.slug_buttons[system_verify.HOPPER_MAP_VARIANTS_KEY].isEnabled() is False


def test_a_long_path_is_elided_in_the_middle_but_kept_in_full(panel: MapsPanel) -> None:
    long_path = "C:\\" + "\\".join(["a-very-long-folder-name"] * 8) + "\\map_variants"
    panel.resize(220, 300)
    panel.set_paths({system_verify.STANDARD_MAP_VARIANTS_KEY: long_path})
    panel.repaint()

    slug = panel.slug_buttons[system_verify.STANDARD_MAP_VARIANTS_KEY]

    assert slug.full_text == long_path
    assert slug.text() != long_path
    assert "…" in slug.text()
    assert slug.text().startswith("C:") and slug.text().endswith("_variants")


def test_clicking_a_slug_requests_that_folder(panel: MapsPanel, qtbot) -> None:
    panel.set_paths({system_verify.HOPPER_MAP_VARIANTS_KEY: r"C:\hopper"})

    with qtbot.waitSignal(panel.open_folder_requested) as blocker:
        panel.slug_buttons[system_verify.HOPPER_MAP_VARIANTS_KEY].click()

    assert blocker.args == [system_verify.HOPPER_MAP_VARIANTS_KEY]


def test_the_inreach_maps_button_requests_the_inreach_maps_folder(panel: MapsPanel, qtbot) -> None:
    assert panel.inreach_maps_button.text() == "Open In-Reach Maps"
    assert panel.inreach_maps_button.isEnabled() is True  # always openable, nothing to verify first

    with qtbot.waitSignal(panel.open_folder_requested) as blocker:
        panel.inreach_maps_button.click()

    assert blocker.args == [system_verify.INREACH_MAPS_KEY]


# -- Quick Launch's "Built-in" buttons ------------------------------------------------------------


def test_quick_launch_has_an_open_inreach_maps_built_in_button(qtbot) -> None:
    explorer = ExplorerPanel()
    qtbot.addWidget(explorer)

    assert explorer.inreach_maps_button.text() == "Open In-Reach Maps"
    with qtbot.waitSignal(explorer.open_builtin_folder_requested) as blocker:
        explorer.inreach_maps_button.click()
    assert blocker.args == [system_verify.INREACH_MAPS_KEY]


# -- MainWindow wiring ----------------------------------------------------------------------------


@pytest.fixture
def project_window(qtbot, tmp_path: Path):
    project_dir = tmp_path / ".in-reach"
    project_dir.mkdir()
    (project_dir / ".env").write_text("", encoding="utf-8")
    win = MainWindow(root_dir=tmp_path)
    qtbot.addWidget(win)
    win.show()
    return win


def _capture_opened_folders(window: MainWindow, monkeypatch) -> list[Path]:
    opened: list[Path] = []
    monkeypatch.setattr(window, "open_folder_in_os_explorer", opened.append)
    return opened


def test_inreach_maps_click_opens_dot_in_reach_maps_and_creates_it(
    project_window: MainWindow, tmp_path: Path, monkeypatch
) -> None:
    opened = _capture_opened_folders(project_window, monkeypatch)
    assert not (tmp_path / ".in-reach" / "maps").exists()

    project_window.maps_panel.inreach_maps_button.click()

    assert opened == [tmp_path / ".in-reach" / "maps"]
    assert (tmp_path / ".in-reach" / "maps").is_dir()


def test_quick_launch_inreach_maps_button_opens_the_same_folder(
    project_window: MainWindow, tmp_path: Path, monkeypatch
) -> None:
    opened = _capture_opened_folders(project_window, monkeypatch)

    project_window.explorer_panel.inreach_maps_button.click()

    assert opened == [tmp_path / ".in-reach" / "maps"]


def test_inreach_maps_honours_a_verified_override(project_window: MainWindow, tmp_path: Path, monkeypatch) -> None:
    elsewhere = tmp_path / "somewhere-else"
    env_file.update_env_value(tmp_path / ".in-reach" / ".env", system_verify.INREACH_MAPS_KEY, str(elsewhere))
    opened = _capture_opened_folders(project_window, monkeypatch)

    project_window.maps_panel.inreach_maps_button.click()

    assert opened == [elsewhere]


def test_the_open_inreach_maps_palette_entry_opens_the_same_folder(
    project_window: MainWindow, tmp_path: Path, monkeypatch
) -> None:
    opened = _capture_opened_folders(project_window, monkeypatch)

    next(c for c in project_window.build_command_palette_commands() if c.label == "Open In-Reach Maps").action()

    assert opened == [tmp_path / ".in-reach" / "maps"]


def test_a_slug_opens_its_verified_folder(project_window: MainWindow, tmp_path: Path, monkeypatch) -> None:
    folder = tmp_path / "map_variants"
    folder.mkdir()
    env_file.update_env_value(tmp_path / ".in-reach" / ".env", system_verify.STANDARD_MAP_VARIANTS_KEY, str(folder))
    opened = _capture_opened_folders(project_window, monkeypatch)
    project_window._refresh_maps_panel()

    project_window.maps_panel.slug_buttons[system_verify.STANDARD_MAP_VARIANTS_KEY].click()

    assert opened == [folder]


def test_an_unverified_slug_folder_tells_the_user_to_run_verify(
    project_window: MainWindow, monkeypatch
) -> None:
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: shown.append(args[2]))
    opened = _capture_opened_folders(project_window, monkeypatch)

    project_window._open_builtin_folder(system_verify.HOPPER_MAP_VARIANTS_KEY)

    assert opened == []
    assert len(shown) == 1 and "Verify System Settings" in shown[0]


def test_opening_the_maps_view_refreshes_the_slugs_from_the_env(project_window: MainWindow, tmp_path: Path) -> None:
    folder = tmp_path / "user_maps"
    folder.mkdir()
    env_file.update_env_value(tmp_path / ".in-reach" / ".env", system_verify.PERSONAL_MAPS_KEY, str(folder))
    project_dir = tmp_path / "abcd1234"
    project_dir.mkdir()
    project_window._on_project_opened(project_dir)

    project_window.activity_bar.maps_button.click()

    slug = project_window.maps_panel.slug_buttons[system_verify.PERSONAL_MAPS_KEY]
    assert slug.full_text == str(folder)
    assert slug.isEnabled() is True
