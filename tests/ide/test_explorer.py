from pathlib import Path

import pytest
from PyQt6.QtCore import Qt

from in_reach.app import env_file, system_verify
from in_reach.ide.explorer import ExplorerPanel


@pytest.fixture
def panel(qtbot) -> ExplorerPanel:
    widget = ExplorerPanel()
    qtbot.addWidget(widget)
    widget.show()  # isVisible() reflects real state only once the whole ancestor chain is shown
    return widget


def test_starts_with_no_project_placeholder_shown_and_tree_hidden(panel: ExplorerPanel) -> None:
    assert panel._no_project_label.isVisible() is True
    assert panel.project_tree.isVisible() is False


def test_set_project_folder_shows_the_tree_rooted_at_it(panel: ExplorerPanel, tmp_path: Path) -> None:
    folder = tmp_path / "project"
    folder.mkdir()
    (folder / "settings.json").write_text("{}", encoding="utf-8")

    panel.set_project_folder(folder)

    assert panel._no_project_label.isVisible() is False
    assert panel.project_tree.isVisible() is True
    assert Path(panel._project_model.rootPath()) == folder


def test_set_project_folder_none_restores_the_placeholder(panel: ExplorerPanel, tmp_path: Path) -> None:
    folder = tmp_path / "project"
    folder.mkdir()
    panel.set_project_folder(folder)

    panel.set_project_folder(None)

    assert panel._no_project_label.isVisible() is True
    assert panel.project_tree.isVisible() is False


def test_a_nonexistent_project_folder_falls_back_to_the_placeholder(panel: ExplorerPanel, tmp_path: Path) -> None:
    panel.set_project_folder(tmp_path / "does-not-exist")

    assert panel._no_project_label.isVisible() is True
    assert panel.project_tree.isVisible() is False


# -- the two personal-folder sections -----------------------------------------------------------


@pytest.fixture
def env_project_dir(tmp_path: Path) -> Path:
    project_dir = tmp_path / ".in-reach"
    project_dir.mkdir()
    (project_dir / ".env").write_text("", encoding="utf-8")
    return project_dir


# Sections start collapsed (see the "collapsible sections" tests below), so a nested tree/
# placeholder's own isVisible() reflects the whole ancestor chain including that collapse -- these
# tests care about the resolved-vs-placeholder state on its own, so they check visibility relative
# to the section's own body instead (see QWidget.isVisibleTo's own docs).


def test_personal_sections_start_with_the_not_resolved_placeholder(
    panel: ExplorerPanel, env_project_dir: Path
) -> None:
    panel.set_env_project_dir(env_project_dir)

    body1 = panel.personal_variants_section.body
    body2 = panel.personal_maps_section.body
    assert panel.personal_variants_placeholder.isVisibleTo(body1) is True
    assert panel.personal_variants_tree.isVisibleTo(body1) is False
    assert panel.personal_maps_placeholder.isVisibleTo(body2) is True
    assert panel.personal_maps_tree.isVisibleTo(body2) is False


def test_personal_sections_resolve_once_the_env_keys_are_set(
    panel: ExplorerPanel, env_project_dir: Path, tmp_path: Path
) -> None:
    variants = tmp_path / "variants"
    variants.mkdir()
    maps = tmp_path / "maps"
    maps.mkdir()
    env_file.update_env_value(env_project_dir / ".env", system_verify.PERSONAL_VARIANTS_KEY, str(variants))
    env_file.update_env_value(env_project_dir / ".env", system_verify.PERSONAL_MAPS_KEY, str(maps))

    panel.set_env_project_dir(env_project_dir)

    body1 = panel.personal_variants_section.body
    body2 = panel.personal_maps_section.body
    assert panel.personal_variants_placeholder.isVisibleTo(body1) is False
    assert panel.personal_variants_tree.isVisibleTo(body1) is True
    assert Path(panel._personal_variants_model.rootPath()) == variants
    assert panel.personal_maps_placeholder.isVisibleTo(body2) is False
    assert panel.personal_maps_tree.isVisibleTo(body2) is True
    assert Path(panel._personal_maps_model.rootPath()) == maps


def test_refresh_personal_folders_picks_up_a_later_verify(
    panel: ExplorerPanel, env_project_dir: Path, tmp_path: Path
) -> None:
    panel.set_env_project_dir(env_project_dir)
    body = panel.personal_variants_section.body
    assert panel.personal_variants_tree.isVisibleTo(body) is False

    variants = tmp_path / "variants"
    variants.mkdir()
    env_file.update_env_value(env_project_dir / ".env", system_verify.PERSONAL_VARIANTS_KEY, str(variants))
    panel.refresh_personal_folders()

    assert panel.personal_variants_tree.isVisibleTo(body) is True


def test_set_env_project_dir_none_clears_both_sections(
    panel: ExplorerPanel, env_project_dir: Path, tmp_path: Path
) -> None:
    variants = tmp_path / "variants"
    variants.mkdir()
    env_file.update_env_value(env_project_dir / ".env", system_verify.PERSONAL_VARIANTS_KEY, str(variants))
    panel.set_env_project_dir(env_project_dir)
    body = panel.personal_variants_section.body
    assert panel.personal_variants_tree.isVisibleTo(body) is True

    panel.set_env_project_dir(None)

    assert panel.personal_variants_placeholder.isVisibleTo(body) is True
    assert panel.personal_variants_tree.isVisibleTo(body) is False


# -- collapsible sections -------------------------------------------------------------------------


def test_personal_sections_start_collapsed(panel: ExplorerPanel) -> None:
    assert panel.personal_variants_section.expanded is False
    assert panel.personal_maps_section.expanded is False
    assert panel.personal_variants_section.body.isVisible() is False


def test_clicking_a_section_header_expands_it(panel: ExplorerPanel, qtbot) -> None:
    qtbot.mouseClick(panel.personal_variants_section._toggle, Qt.MouseButton.LeftButton)

    assert panel.personal_variants_section.expanded is True
    assert panel.personal_variants_section.body.isVisible() is True


# -- clicking a file opens it ----------------------------------------------------------------------


def test_clicking_a_file_in_the_project_tree_emits_file_activated(
    panel: ExplorerPanel, qtbot, tmp_path: Path
) -> None:
    folder = tmp_path / "project"
    folder.mkdir()
    file_path = folder / "notes.txt"
    file_path.write_text("hi", encoding="utf-8")
    panel.set_project_folder(folder)
    model = panel._project_model
    root_index = panel.project_tree.rootIndex()
    qtbot.waitUntil(lambda: model.rowCount(root_index) > 0, timeout=2000)
    file_index = model.index(str(file_path))

    activated: list[Path] = []
    panel.file_activated.connect(activated.append)
    panel._on_tree_clicked(model, file_index)

    assert activated == [file_path]


def test_clicking_a_folder_in_the_project_tree_does_not_emit_file_activated(
    panel: ExplorerPanel, qtbot, tmp_path: Path
) -> None:
    folder = tmp_path / "project"
    (folder / "subfolder").mkdir(parents=True)
    panel.set_project_folder(folder)
    model = panel._project_model
    root_index = panel.project_tree.rootIndex()
    qtbot.waitUntil(lambda: model.rowCount(root_index) > 0, timeout=2000)
    dir_index = model.index(str(folder / "subfolder"))

    activated: list[Path] = []
    panel.file_activated.connect(activated.append)
    panel._on_tree_clicked(model, dir_index)

    assert activated == []


def test_an_invalid_index_does_not_emit_file_activated(panel: ExplorerPanel) -> None:
    from PyQt6.QtCore import QModelIndex

    activated: list[Path] = []
    panel.file_activated.connect(activated.append)

    panel._on_tree_clicked(panel._project_model, QModelIndex())

    assert activated == []


def test_clicking_a_file_in_a_personal_folder_section_also_emits_file_activated(
    panel: ExplorerPanel, qtbot, tmp_path: Path
) -> None:
    project_dir = tmp_path / ".in-reach"
    project_dir.mkdir()
    (project_dir / ".env").write_text("", encoding="utf-8")
    variants = tmp_path / "variants"
    variants.mkdir()
    file_path = variants / "Slayer.bin"
    file_path.write_bytes(b"")
    env_file.update_env_value(project_dir / ".env", system_verify.PERSONAL_VARIANTS_KEY, str(variants))
    panel.set_env_project_dir(project_dir)
    model = panel._personal_variants_model
    root_index = panel.personal_variants_tree.rootIndex()
    qtbot.waitUntil(lambda: model.rowCount(root_index) > 0, timeout=2000)
    file_index = model.index(str(file_path))

    activated: list[Path] = []
    panel.file_activated.connect(activated.append)
    panel._on_tree_clicked(model, file_index)

    assert activated == [file_path]
