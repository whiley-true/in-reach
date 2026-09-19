"""Primary-sidebar view behind the activity bar's kanban icon (PROMPT.md: "the icon should open the
side panel and allow the user to choose or create a board and set background colour or custom image
(which is added to the repo)" -- "when clicked it should load the default board in the editor
view").

Lists the active gametype project's own boards from the shared
:class:`~in_reach.app.kanban_db.KanbanStore` (one database, many projects, many boards); this panel
only manages boards -- create/open/rename/delete, which one is the default, and the selected board's
background -- while the board itself is drawn in an editor tab by
:class:`~in_reach.ide.kanban_board.KanbanBoardView`. Opening a board is reported via
:attr:`KanbanPanel.open_board_requested`; :class:`~in_reach.ide.main_window.MainWindow` owns
actually opening the tab, and creates the store lazily the first time the view is shown (see
:meth:`KanbanPanel.set_store`).
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QGridLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from in_reach.app import new_project
from in_reach.app.kanban_db import Board, KanbanStore, Project
from in_reach.ide import file_dialogs
from in_reach.ide.kanban_dialogs import pick_color, swatch_icon

_NO_PROJECT_TEXT = "No project opened yet -- create or load one from the Welcome tab."
_IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All files (*)"


class KanbanPanel(QWidget):
    #: Emitted with a board's id when the user asks to open it in an editor tab.
    open_board_requested = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store: KanbanStore | None = None
        self._project_key: str | None = None
        self._project_title = ""
        self._project: Project | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.status_label = QLabel(_NO_PROJECT_TEXT)
        self.status_label.setWordWrap(True)
        self.status_label.setEnabled(False)
        layout.addWidget(self.status_label)

        self.boards_label = QLabel("Boards")
        self.boards_label.setStyleSheet("QLabel { font-style: italic; }")
        layout.addWidget(self.boards_label)

        self.boards_list = QListWidget()
        self.boards_list.itemActivated.connect(lambda _item: self.open_selected())
        self.boards_list.itemSelectionChanged.connect(self._sync_enabled)
        self.boards_list.currentRowChanged.connect(lambda _row: self._sync_enabled())
        layout.addWidget(self.boards_list, 1)

        grid = QGridLayout()
        grid.setSpacing(4)
        self.new_button = QPushButton("New Board...")
        self.open_button = QPushButton("Open")
        self.rename_button = QPushButton("Rename...")
        self.delete_button = QPushButton("Delete...")
        self.default_button = QPushButton("Set as Default")
        self.new_button.clicked.connect(self.new_board)
        self.open_button.clicked.connect(self.open_selected)
        self.rename_button.clicked.connect(self.rename_selected)
        self.delete_button.clicked.connect(self.delete_selected)
        self.default_button.clicked.connect(self.set_default_selected)
        grid.addWidget(self.new_button, 0, 0)
        grid.addWidget(self.open_button, 0, 1)
        grid.addWidget(self.rename_button, 1, 0)
        grid.addWidget(self.delete_button, 1, 1)
        grid.addWidget(self.default_button, 2, 0, 1, 2)
        layout.addLayout(grid)

        self.background_label = QLabel("Background")
        self.background_label.setStyleSheet("QLabel { font-style: italic; }")
        layout.addWidget(self.background_label)
        background_row = QGridLayout()
        background_row.setSpacing(4)
        self.color_button = QPushButton("Colour...")
        self.image_button = QPushButton("Image...")
        self.clear_background_button = QPushButton("Clear")
        self.color_button.clicked.connect(self.choose_color)
        self.image_button.clicked.connect(self.choose_image)
        self.clear_background_button.clicked.connect(self.clear_background)
        background_row.addWidget(self.color_button, 0, 0)
        background_row.addWidget(self.image_button, 0, 1)
        background_row.addWidget(self.clear_background_button, 0, 2)
        layout.addLayout(background_row)

        self._sync_enabled()

    # -- wiring -----------------------------------------------------------------------------------

    def set_store(self, store: KanbanStore | None) -> None:
        """Points the panel at the shared store (MainWindow creates it lazily) and keeps the list
        in step with any later change made anywhere -- this panel, a board tab, another window."""
        self._store = store
        if store is not None:
            store.add_listener(self.refresh)
        self.refresh()

    def set_project_folder(self, folder: Path | None) -> None:
        """Points the panel at ``folder``'s boards (the active gametype project), or back to the
        "no project" state for ``None``. A project is keyed by its folder's own generated id, so
        renaming its title never orphans its boards."""
        if folder is None:
            self._project_key, self._project_title = None, ""
        else:
            self._project_key = folder.name
            self._project_title = new_project.read_project_title(folder)
        self.refresh()

    @property
    def project(self) -> Project | None:
        return self._project

    def refresh(self) -> None:
        """Re-reads the board list from the store, keeping the current selection if it survives."""
        selected = self.selected_board_id()
        self.boards_list.clear()
        self._project = None
        if self._store is not None and self._project_key is not None:
            self._project = self._store.ensure_project(self._project_key, self._project_title)
            for board in self._store.list_boards(self._project.id):
                self.boards_list.addItem(self._item_for(board))
        self._select_board(selected)
        if self.boards_list.currentRow() < 0 and self.boards_list.count():
            # Nothing (surviving) selected -- land on the default board, so Open/Rename/Background
            # aren't all greyed out for a project that clearly has a board to act on.
            self._select_default_board()
        self._sync_enabled()

    def _select_default_board(self) -> None:
        default = self._store.default_board(self._project.id) if self._store and self._project else None
        self._select_board(default.id if default else None)
        if self.boards_list.currentRow() < 0:
            self.boards_list.setCurrentRow(0)

    def _item_for(self, board: Board) -> QListWidgetItem:
        item = QListWidgetItem(f"{board.name}  (default)" if board.is_default else board.name)
        item.setData(Qt.ItemDataRole.UserRole, board.id)
        image = self._store.resolve_background_image(board) if self._store else None
        if image is not None:
            item.setIcon(QIcon(str(image)))
        elif board.background_color:
            item.setIcon(swatch_icon(board.background_color))
        return item

    def _select_board(self, board_id: int | None) -> None:
        if board_id is None:
            return
        for row in range(self.boards_list.count()):
            if self.boards_list.item(row).data(Qt.ItemDataRole.UserRole) == board_id:
                self.boards_list.setCurrentRow(row)
                return

    def selected_board_id(self) -> int | None:
        item = self.boards_list.currentItem()
        return None if item is None else item.data(Qt.ItemDataRole.UserRole)

    def selected_board(self) -> Board | None:
        board_id = self.selected_board_id()
        return None if board_id is None or self._store is None else self._store.get_board(board_id)

    def _sync_enabled(self) -> None:
        has_project = self._project_key is not None and self._store is not None
        has_board = self.selected_board_id() is not None
        self.status_label.setVisible(self._project_key is None)
        self.boards_label.setText(f"Boards -- {self._project_title}" if self._project_title else "Boards")
        self.boards_list.setEnabled(has_project)
        self.new_button.setEnabled(has_project)
        for button in (
            self.open_button,
            self.rename_button,
            self.delete_button,
            self.default_button,
            self.color_button,
            self.image_button,
            self.clear_background_button,
        ):
            button.setEnabled(has_project and has_board)

    # -- test seams -------------------------------------------------------------------------------

    def _ask_text(self, title: str, label: str, default: str = "") -> str | None:
        text, ok = QInputDialog.getText(self, title, label, text=default)
        return text.strip() if ok and text.strip() else None

    def _confirm_delete(self, board: Board) -> bool:
        result = QMessageBox.question(
            self,
            "in-reach",
            f"Delete the board {board.name!r} and all of its columns and cards? This can't be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return result == QMessageBox.StandardButton.Yes

    def _ask_color(self, initial: str | None) -> str | None:
        return pick_color(self, initial)

    def _ask_image(self) -> Path | None:
        chosen, _filter = file_dialogs.get_open_file_name(self, "Choose a background image", "", _IMAGE_FILTER)
        return Path(chosen) if chosen else None

    def _warn(self, text: str) -> None:
        QMessageBox.warning(self, "in-reach", text)

    # -- actions ----------------------------------------------------------------------------------

    def new_board(self) -> None:
        if self._store is None or self._project is None:
            return
        name = self._ask_text("New Board", "Board name")
        if name is None:
            return
        board = self._store.create_board(self._project.id, name)
        self._select_board(board.id)
        self.open_board_requested.emit(board.id)

    def open_selected(self) -> None:
        board_id = self.selected_board_id()
        if board_id is not None:
            self.open_board_requested.emit(board_id)

    def rename_selected(self) -> None:
        board = self.selected_board()
        if board is None or self._store is None:
            return
        name = self._ask_text("Rename Board", "Board name", board.name)
        if name is not None:
            self._store.rename_board(board.id, name)

    def delete_selected(self) -> None:
        board = self.selected_board()
        if board is None or self._store is None or not self._confirm_delete(board):
            return
        self._store.delete_board(board.id)

    def set_default_selected(self) -> None:
        board_id = self.selected_board_id()
        if board_id is not None and self._store is not None:
            self._store.set_default_board(board_id)

    def choose_color(self) -> None:
        board = self.selected_board()
        if board is None or self._store is None:
            return
        color = self._ask_color(board.background_color)
        if color is not None:
            self._store.set_board_background(board.id, color=color)

    def choose_image(self) -> None:
        board = self.selected_board()
        if board is None or self._store is None:
            return
        image = self._ask_image()
        if image is None:
            return
        try:
            self._store.set_board_background_image(board.id, image)
        except (OSError, KeyError) as exc:
            self._warn(f"Couldn't use that image:\n{exc}")

    def clear_background(self) -> None:
        board_id = self.selected_board_id()
        if board_id is not None and self._store is not None:
            self._store.set_board_background(board_id, color=None)
