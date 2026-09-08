"""The main tab panel: a split-capable tab view (max 2 splits -> 3 side-by-side pane-groups) and,
independently, each pane-group can be split vertically once (max 2 stacked panes per group) -- so
the area tops out at 3 x 2 = 6 panes. Splitting duplicates the source pane's current tab into the
new pane (VSCode's "split editor" behavior) rather than leaving it empty -- for a text-editor tab,
the duplicate shares the same underlying QTextDocument, so both views edit the same buffer. Tabs
are closable and reorderable within a pane, and draggable from any pane into any other, regardless
of which group they belong to.

The panel opens on a single Welcome tab. Double-clicking a tab bar's own empty space creates a new
"Untitled-N.txt" text-editor tab. Every tab tracks unsaved changes (the close button becomes a dot
while dirty; closing a dirty tab prompts Save/Don't Save/Cancel, with Save falling back to a native
Save As dialog the first time), and can be right-clicked for a VSCode-style context menu (close
variants, copy/reveal path actions -- only enabled once a tab has a real file behind it -- pin, and
split).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QMimeData, QPoint, QSize, Qt
from PyQt6.QtGui import QDrag, QDragEnterEvent, QDragMoveEvent, QDropEvent, QMouseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QMenu,
    QMessageBox,
    QSplitter,
    QTabBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from in_reach.app.new_project import is_generated_file
from in_reach.ide import icons, schema_check, style
from in_reach.ide.editor import TextEditorWidget
from in_reach.ide.welcome import WelcomeTab

_MIME_TYPE = "application/x-inreach-tab"
_MAX_H_SPLITS = 2  # -> up to 3 pane-groups side by side
_MAX_V_SPLITS = 1  # -> up to 2 panes stacked within one group
_SPLIT_ICON_COLOR = "#808080"
_TAB_CLOSE_ICON_COLOR = "#808080"
_TAB_CLOSE_ICON_SIZE = 14


class _SaveChoice(Enum):
    SAVE = "save"
    DISCARD = "discard"
    CANCEL = "cancel"


@dataclass
class _TabState:
    path: Path | None = None
    pinned: bool = False


def _is_modified(widget: QWidget | None) -> bool:
    return isinstance(widget, TextEditorWidget) and widget.document().isModified()


def _on_editor_modified(widget: TextEditorWidget, modified: bool) -> None:
    pane = getattr(widget, "_owner_pane", None)
    if pane is None:
        return
    index = pane.indexOf(widget)
    if index >= 0:
        pane._update_close_icon(index)


def _connect_modification_tracking(editor: TextEditorWidget) -> None:
    editor.document().modificationChanged.connect(
        lambda modified, w=editor: _on_editor_modified(w, modified)
    )


class _DragTabBar(QTabBar):
    """A QTabBar that starts a cross-pane drag (carrying the owning pane's id + tab index) once
    the mouse leaves the tab bar's own bounds while dragging a tab -- reordering *within* the bar
    is left entirely to Qt's own built-in movable-tab handling (``setMovable(True)``), so any drag
    that stays inside the bar falls through to the base implementation untouched. Double-clicking
    the bar's own empty space (past the last tab) creates a new placeholder tab."""

    def __init__(self, pane: "TabPane") -> None:
        super().__init__(pane)
        self._pane = pane
        self._drag_start_index: int | None = None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_index = self.tabAt(event.position().toPoint())
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.tabAt(event.position().toPoint()) < 0:
            # Double-clicked the bar's own empty tail past the last tab, rather than any tab
            # itself -- a single click there is left alone since it's also the first half of every
            # ordinary drag/press interaction with the bar.
            self._pane._area.new_tab_in(self._pane)
            return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        index = self._drag_start_index
        if (
            index is not None
            and index >= 0
            and bool(event.buttons() & Qt.MouseButton.LeftButton)
            and not self.rect().contains(event.position().toPoint())
        ):
            self._drag_start_index = None
            self._start_drag(index)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_start_index = None
        super().mouseReleaseEvent(event)

    def _start_drag(self, index: int) -> None:
        mime = QMimeData()
        mime.setData(_MIME_TYPE, f"{id(self._pane)}:{index}".encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)


class TabPane(QTabWidget):
    """One pane of the main panel area -- a closable, reorderable tab strip that accepts a tab
    dragged in from a sibling pane, with a corner widget offering both a horizontal and a vertical
    split button."""

    def __init__(self, area: "MainPanelArea", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._area = area
        self.group: "_PaneGroup | None" = None  # set by _PaneGroup.add_pane()
        self.card: QWidget | None = None  # set by _PaneGroup.add_pane()
        self._tab_state: dict[QWidget, _TabState] = {}
        self.setTabBar(_DragTabBar(self))
        self.setMovable(True)
        self.setTabsClosable(True)
        self.tabCloseRequested.connect(self._maybe_close)
        self.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabBar().customContextMenuRequested.connect(self._show_tab_context_menu)
        self.setAcceptDrops(True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        # Neither of these is styling per se -- they suppress native chrome that QTabBar::tab's own
        # QSS (border: none included) can't reach, since it's painted by QTabBar itself rather than
        # per-tab: documentMode drops the native pane/tab-bar frame, and drawBase specifically drops
        # the base line Fusion otherwise still paints across the top of the tab row regardless.
        self.setDocumentMode(True)
        self.tabBar().setDrawBase(False)
        self.setStyleSheet(style.MAIN_TAB_STYLE)
        # Whenever the tabs don't fit their natural size -- too many for the width, whether that
        # shows up as scroll arrows or as elided/shrunk tab labels -- QTabBar recomputes a *shorter*
        # preferred row height from its own overflow-handling metrics instead of our tabs' actual
        # padding/margin box model, and the corner widget's slot (which QTabBar positions directly,
        # bypassing its own setFixedSize) gets forced to match that shorter height, squashing the
        # split buttons. Pinning the tab bar to its natural (tabs-fit-comfortably) height keeps the
        # row -- and the corner slot -- from ever shrinking, in every overflow state.
        bar_height = self.fontMetrics().height() + 20
        self.tabBar().setFixedHeight(bar_height)
        # Sized to match the tab bar's own scroll-arrow buttons (which fill the full row height)
        # rather than some arbitrary smaller constant, so the two button pairs read as the same
        # weight of control instead of the split buttons looking like a shrunken afterthought.
        button_size = bar_height
        icon_size = max(button_size - 14, 16)

        self.vsplit_button = QToolButton()
        self.vsplit_button.setIcon(icons.icon("split_vertical", color=_SPLIT_ICON_COLOR, size=icon_size))
        self.vsplit_button.setIconSize(QSize(icon_size, icon_size))
        self.vsplit_button.setFixedSize(button_size, button_size)
        self.vsplit_button.setToolTip("Split panel down")
        self.vsplit_button.setAutoRaise(True)
        self.vsplit_button.clicked.connect(lambda: self._area.vsplit_from(self))

        self.split_button = QToolButton()
        self.split_button.setIcon(icons.icon("split", color=_SPLIT_ICON_COLOR, size=icon_size))
        self.split_button.setIconSize(QSize(icon_size, icon_size))
        self.split_button.setFixedSize(button_size, button_size)
        self.split_button.setToolTip("Split panel right")
        self.split_button.setAutoRaise(True)
        self.split_button.clicked.connect(lambda: self._area.split_from(self))

        corner = QWidget()
        corner_layout = QHBoxLayout(corner)
        corner_layout.setContentsMargins(0, 0, 0, 0)
        corner_layout.setSpacing(0)
        corner_layout.addWidget(self.vsplit_button)
        corner_layout.addWidget(self.split_button)
        self.setCornerWidget(corner, Qt.Corner.TopRightCorner)

    # -- tab tracking (dirty state / file path / pinned) -----------------------------------

    def _track_tab(self, index: int, widget: QWidget, state: "_TabState | None" = None) -> None:
        self._tab_state[widget] = state or _TabState()
        widget._owner_pane = self  # read back dynamically by _on_editor_modified
        self._update_close_icon(index)

    def _tab_state_for(self, widget: QWidget) -> _TabState:
        return self._tab_state.setdefault(widget, _TabState())

    def _update_close_icon(self, index: int) -> None:
        button = self.tabBar().tabButton(index, QTabBar.ButtonPosition.RightSide)
        if button is None:
            return
        name = "tab_dirty" if _is_modified(self.widget(index)) else "win_close"
        button.setIcon(icons.icon(name, color=_TAB_CLOSE_ICON_COLOR, size=_TAB_CLOSE_ICON_SIZE))

    # -- closing, with unsaved-changes handling ---------------------------------------------

    def _close_tab(self, index: int) -> None:
        widget = self.widget(index)
        self.removeTab(index)
        if widget is not None:
            self._tab_state.pop(widget, None)
            widget.deleteLater()
        self._area.on_pane_emptied(self)

    def _maybe_close(self, index: int) -> bool:
        """Closes the tab at ``index``, prompting to save first if it's dirty. Returns whether it
        ended up closed (``False`` if the user cancelled, or a Save As was itself cancelled)."""
        widget = self.widget(index)
        if widget is None:
            return False
        if _is_modified(widget):
            choice = self._ask_save_choice(self.tabText(index))
            if choice == _SaveChoice.CANCEL:
                return False
            if choice == _SaveChoice.SAVE and not self._save_tab(index):
                return False
        self._close_tab(index)
        return True

    def _ask_save_choice(self, label: str) -> _SaveChoice:
        """Kept as its own method (rather than inlined) purely so tests can monkeypatch it instead
        of driving a real modal QMessageBox."""
        box = QMessageBox(self)
        box.setWindowTitle("in-reach")
        box.setText(f"Do you want to save the changes you made to {label}?")
        save_button = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Don't Save", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save_button)
        box.exec()
        role = box.buttonRole(box.clickedButton())
        if role == QMessageBox.ButtonRole.AcceptRole:
            return _SaveChoice.SAVE
        if role == QMessageBox.ButtonRole.DestructiveRole:
            return _SaveChoice.DISCARD
        return _SaveChoice.CANCEL

    def _ask_save_path(self, default_dir: Path, suggested_name: str) -> Path | None:
        """Also its own method for the same test-seam reason as ``_ask_save_choice``."""
        chosen, _selected_filter = QFileDialog.getSaveFileName(
            self, "Save As", str(default_dir / suggested_name)
        )
        return Path(chosen) if chosen else None

    def _save_tab(self, index: int) -> bool:
        widget = self.widget(index)
        state = self._tab_state_for(widget)
        path = state.path
        if path is None:
            path = self._ask_save_path(self._area.root_dir, self.tabText(index))
            if path is None:
                return False
        text = widget.toPlainText()
        # PROMPT.md: "if a file has a schema, and a user tries to save the file with an incorrect
        # value, then the save should fail" -- checked before the write, not after, so a rejected
        # save never touches disk at all.
        schema_error = schema_check.validate_before_save(path, text)
        if schema_error is not None:
            QMessageBox.critical(self, "in-reach", f"Couldn't save {path.name}:\n{schema_error}")
            return False
        try:
            path.write_text(text, encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "in-reach", f"Couldn't save {path.name}:\n{exc}")
            return False
        state.path = path
        self.setTabText(index, path.name)
        widget.document().setModified(False)
        if self._area.on_file_saved is not None:
            self._area.on_file_saved(path)
        return True

    # -- File menu entry points (New File/Open File/Save/Save As/Save All/Close Editor) ---------

    def save_current(self) -> bool:
        """"Save" -- saves the current tab, prompting for a path only if it doesn't have one yet.
        A no-op (returns ``False``) if this pane has no tabs at all."""
        if self.count() == 0:
            return False
        return self._save_tab(self.currentIndex())

    def save_current_as(self) -> bool:
        """"Save As" -- always prompts for a path, even if the current tab already has one."""
        if self.count() == 0:
            return False
        index = self.currentIndex()
        state = self._tab_state_for(self.widget(index))
        previous_path = state.path
        state.path = None
        if self._save_tab(index):
            return True
        state.path = previous_path  # restore -- the prompt was cancelled, or the write failed
        return False

    def save_all(self) -> None:
        """"Save All" -- saves every modified tab in this pane that already has a path; a tab with
        no path yet (never saved) is left alone rather than popping a Save As prompt per tab."""
        for index in range(self.count()):
            widget = self.widget(index)
            if _is_modified(widget) and self._tab_state_for(widget).path is not None:
                self._save_tab(index)

    def open_file(self, path: Path) -> None:
        """"Open File" (the File menu, and clicking a file in the Explorer panel) -- adds ``path``
        as a new tab, reading its content in. Switches to the existing tab instead of duplicating
        it if ``path`` is already open in this pane."""
        for index in range(self.count()):
            if self._tab_state_for(self.widget(index)).path == path:
                self.setCurrentIndex(index)
                return
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            QMessageBox.critical(self, "in-reach", f"Couldn't open {path.name}:\n{exc}")
            return
        editor = TextEditorWidget(path=path)
        editor.setPlainText(text)
        # PROMPT.md: "the autogenerated files should not be editable" -- build/'s own compiled
        # output and *.autogenerated.json snapshots are overwritten wholesale on every successful
        # build/resync, so an edit made here would just silently vanish rather than doing anything.
        generated = is_generated_file(path)
        editor.setReadOnly(generated)
        _connect_modification_tracking(editor)
        # PROMPT.md: "they have a padlock symbol in the tab" -- a generated file's read-only status
        # never changes for the tab's own lifetime, unlike the dirty-state icon on its close
        # button, so this is set once here rather than needing its own refresh hook.
        if generated:
            new_index = self.addTab(editor, icons.lock_icon(), path.name)
        else:
            new_index = self.addTab(editor, path.name)
        self._track_tab(new_index, editor, state=_TabState(path=path))
        self.setCurrentIndex(new_index)

    def open_file_at_line(self, path: Path, line_number: int) -> None:
        """"Jump to this result" -- the Search panel's own way into a file: :meth:`open_file`
        ``path`` (or switch to its already-open tab), then move the cursor to ``line_number`` and
        scroll it into view.

        Args:
            path: The file to open.
            line_number: 1-based line to jump to -- a search match's own numbering, matching how
                every editor/IDE numbers lines for a human rather than 0-based indexing.
        """
        self.open_file(path)
        widget = self.widget(self.currentIndex())
        if not isinstance(widget, TextEditorWidget):
            return
        block = widget.document().findBlockByNumber(max(0, line_number - 1))
        cursor = widget.textCursor()
        cursor.setPosition(block.position())
        widget.setTextCursor(cursor)
        widget.centerCursor()

    def close_current(self) -> bool:
        """"Close Editor" -- closes the current tab, same prompt-if-dirty behavior as its own close
        button. A no-op (returns ``False``) if this pane has no tabs at all."""
        if self.count() == 0:
            return False
        return self._maybe_close(self.currentIndex())

    def _close_many(self, widgets: list[QWidget]) -> None:
        for widget in widgets:
            index = self.indexOf(widget)
            if index >= 0:
                self._maybe_close(index)

    def _close_others(self, keep_index: int) -> None:
        keep_widget = self.widget(keep_index)
        targets = [
            self.widget(i)
            for i in range(self.count())
            if self.widget(i) is not keep_widget and not self._tab_state_for(self.widget(i)).pinned
        ]
        self._close_many(targets)

    def _close_to_the_right(self, index: int) -> None:
        targets = [
            self.widget(i)
            for i in range(index + 1, self.count())
            if not self._tab_state_for(self.widget(i)).pinned
        ]
        self._close_many(targets)

    def _close_saved(self) -> None:
        targets = [
            self.widget(i)
            for i in range(self.count())
            if not _is_modified(self.widget(i)) and not self._tab_state_for(self.widget(i)).pinned
        ]
        self._close_many(targets)

    def _close_all(self) -> None:
        targets = [
            self.widget(i) for i in range(self.count()) if not self._tab_state_for(self.widget(i)).pinned
        ]
        self._close_many(targets)

    # -- pin ---------------------------------------------------------------------------------

    def _toggle_pin(self, index: int) -> None:
        widget = self.widget(index)
        state = self._tab_state_for(widget)
        state.pinned = not state.pinned
        if state.pinned:
            pinned_before = sum(
                1
                for i in range(self.count())
                if self.widget(i) is not widget and self._tab_state_for(self.widget(i)).pinned
            )
            current_index = self.indexOf(widget)
            if current_index != pinned_before:
                self.tabBar().moveTab(current_index, pinned_before)

    # -- copy/reveal path actions -------------------------------------------------------------

    def _copy_path(self, widget: QWidget) -> None:
        path = self._tab_state_for(widget).path
        if path is not None:
            QApplication.clipboard().setText(str(path))

    def _copy_relative_path(self, widget: QWidget) -> None:
        path = self._tab_state_for(widget).path
        if path is None:
            return
        try:
            relative = path.relative_to(self._area.root_dir)
        except ValueError:
            relative = path
        QApplication.clipboard().setText(str(relative))

    def _reveal_in_os_explorer(self, path: Path | None) -> None:
        if path is None:
            return
        try:
            subprocess.run(["explorer", "/select,", str(path)], check=False)
        except OSError:
            pass

    def _reveal_in_explorer_view(self) -> None:
        if self._area.reveal_in_explorer is not None:
            self._area.reveal_in_explorer()

    # -- split (from the tab context menu, acting on a specific -- not necessarily active -- tab)

    def _split_tab(self, index: int, *, vertical: bool) -> None:
        self.setCurrentIndex(index)
        if vertical:
            self._area.vsplit_from(self)
        else:
            self._area.split_from(self)

    # -- context menu --------------------------------------------------------------------------

    def _show_tab_context_menu(self, pos: QPoint) -> None:
        index = self.tabBar().tabAt(pos)
        if index < 0:
            return
        widget = self.widget(index)
        state = self._tab_state_for(widget)
        has_path = state.path is not None

        menu = QMenu(self)
        menu.addAction("Close", lambda: self._maybe_close(index))
        menu.addAction("Close Others", lambda: self._close_others(index))
        menu.addAction("Close to the Right", lambda: self._close_to_the_right(index))
        menu.addAction("Close Saved", self._close_saved)
        menu.addAction("Close All", self._close_all)
        menu.addSeparator()

        menu.addAction("Copy Path", lambda: self._copy_path(widget)).setEnabled(has_path)
        menu.addAction("Copy Relative Path", lambda: self._copy_relative_path(widget)).setEnabled(has_path)
        menu.addSeparator()

        menu.addAction(
            "Reveal in File Explorer", lambda: self._reveal_in_os_explorer(state.path)
        ).setEnabled(has_path)
        menu.addAction("Reveal in Explorer View", self._reveal_in_explorer_view).setEnabled(has_path)
        menu.addSeparator()

        menu.addAction("Unpin" if state.pinned else "Pin", lambda: self._toggle_pin(index))
        menu.addSeparator()

        can_hsplit = self._area.split_count < _MAX_H_SPLITS
        can_vsplit = self.group is None or self.group.vsplit_count < _MAX_V_SPLITS
        menu.addAction("Split Right", lambda: self._split_tab(index, vertical=False)).setEnabled(can_hsplit)
        menu.addAction("Split Down", lambda: self._split_tab(index, vertical=True)).setEnabled(can_vsplit)

        menu.exec(self.tabBar().mapToGlobal(pos))

    # -- drag/drop between panes ---------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(_MIME_TYPE):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasFormat(_MIME_TYPE):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        mime = event.mimeData()
        if not mime.hasFormat(_MIME_TYPE):
            super().dropEvent(event)
            return

        pane_id_str, index_str = bytes(mime.data(_MIME_TYPE)).decode("utf-8").split(":")
        source = self._area.find_pane(int(pane_id_str))
        index = int(index_str)
        if source is None or source is self:
            # A same-pane drag never reaches here -- see _DragTabBar's own docstring -- but guard
            # against it anyway rather than duplicating the tab.
            event.ignore()
            return

        label = source.tabText(index)
        content = source.widget(index)
        state = source._tab_state.pop(content, _TabState())
        source.removeTab(index)
        new_index = self.addTab(content, label)
        self._track_tab(new_index, content, state=state)
        self.setCurrentIndex(new_index)
        self._area.on_pane_emptied(source)
        event.acceptProposedAction()


class _PaneGroup(QWidget):
    """One horizontal slot of the main panel area -- a vertical splitter holding one or two
    :class:`TabPane`s (a second one added via a pane's "split vertical" button)."""

    def __init__(self, area: "MainPanelArea") -> None:
        super().__init__()
        self._area = area
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setStyleSheet(style.GAP_SPLITTER_HANDLE_STYLE)
        self.splitter.setHandleWidth(style.PANEL_GAP)
        # A pane dragged down to (or past) its neighbor's edge must not be able to collapse it to
        # zero height -- only the tab-close/auto-close path should ever remove a pane.
        self.splitter.setChildrenCollapsible(False)
        layout.addWidget(self.splitter)

        self.panes: list[TabPane] = []

    @property
    def vsplit_count(self) -> int:
        return len(self.panes) - 1

    def add_pane(self, pane: TabPane) -> None:
        pane.group = self
        pane.card = style.wrap_tab_widget(pane, flush_top=True)
        self.splitter.addWidget(pane.card)
        self.panes.append(pane)
        self._equalize()

    def remove_pane(self, pane: TabPane) -> None:
        self.panes.remove(pane)
        card = pane.card
        card.setParent(None)
        card.deleteLater()
        self._equalize()

    def _equalize(self) -> None:
        count = self.splitter.count()
        if count <= 0:
            return
        total = max(self.splitter.height(), count * 150)
        self.splitter.setSizes([total // count] * count)


class MainPanelArea(QWidget):
    """Holds one or more :class:`_PaneGroup` instances side by side in a horizontal splitter, up
    to :data:`_MAX_H_SPLITS` horizontal splits, each in turn holding up to one vertical split."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        root_dir: Path | None = None,
        reveal_in_explorer: Callable[[], None] | None = None,
        on_project_opened: Callable[[Path], None] | None = None,
        on_settings_changed: Callable[[], None] | None = None,
        on_file_saved: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.root_dir = root_dir or Path.cwd()
        self.reveal_in_explorer = reveal_in_explorer
        self.on_project_opened = on_project_opened
        self.on_settings_changed = on_settings_changed
        self.on_file_saved = on_file_saved
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setStyleSheet(style.GAP_SPLITTER_HANDLE_STYLE)
        self._splitter.setHandleWidth(style.PANEL_GAP)
        # Same reasoning as _PaneGroup.splitter above -- in particular, this is what stops the
        # leftmost pane-group from being drag-resized down to zero width (effectively hiding it).
        self._splitter.setChildrenCollapsible(False)
        layout.addWidget(self._splitter)

        self.groups: list[_PaneGroup] = []
        first_group = self._new_group()
        first_pane = self._new_pane()
        welcome = self._new_welcome_tab()
        welcome_index = first_pane.addTab(welcome, "Welcome")
        first_pane._track_tab(welcome_index, welcome)
        first_group.add_pane(first_pane)
        self._add_group(first_group)
        self._next_tab_number = 1

    @property
    def panes(self) -> list[TabPane]:
        return [pane for group in self.groups for pane in group.panes]

    @property
    def active_pane(self) -> TabPane:
        """The pane the File menu's New File/Open File/Save/Close Editor actions target.

        Always the first pane for now -- this area doesn't yet track which pane last had keyboard
        focus across a multi-pane split, so a File-menu action always lands in the same place
        regardless of which split the user was just looking at.
        """
        return self.panes[0]

    @property
    def split_count(self) -> int:
        """Horizontal split count -- ``len(self.groups) - 1``."""
        return len(self.groups) - 1

    def save_all(self) -> None:
        """"Save All" across every pane, not just the active one."""
        for pane in self.panes:
            pane.save_all()

    def _new_pane(self) -> TabPane:
        return TabPane(self)

    def _new_group(self) -> _PaneGroup:
        return _PaneGroup(self)

    def _new_welcome_tab(self) -> WelcomeTab:
        welcome = WelcomeTab(root_dir=self.root_dir)
        if self.on_project_opened is not None:
            welcome.project_opened.connect(self.on_project_opened)
        if self.on_settings_changed is not None:
            welcome.settings_changed.connect(self.on_settings_changed)
        return welcome

    def _add_group(self, group: _PaneGroup) -> None:
        self._splitter.addWidget(group)
        self.groups.append(group)
        self._equalize_groups()
        self._update_split_buttons()

    def _equalize_groups(self) -> None:
        count = self._splitter.count()
        if count <= 0:
            return
        total = max(self._splitter.width(), count * 200)
        self._splitter.setSizes([total // count] * count)

    def _update_split_buttons(self) -> None:
        can_hsplit = self.split_count < _MAX_H_SPLITS
        for group in self.groups:
            can_vsplit = group.vsplit_count < _MAX_V_SPLITS
            for pane in group.panes:
                pane.split_button.setEnabled(can_hsplit)
                pane.vsplit_button.setEnabled(can_vsplit)

    def _duplicate_current_tab(self, source: TabPane, target: TabPane) -> None:
        """Splitting a pane duplicates its current tab into the new pane, rather than leaving the
        new pane empty -- matching e.g. VSCode's "split editor" behavior. A text-editor tab's
        duplicate shares the same QTextDocument as the source, so both views edit the same buffer
        and stay in sync (including dirty state) for free."""
        index = source.currentIndex()
        if index < 0:
            return
        label = source.tabText(index)
        widget = source.widget(index)
        source_state = source._tab_state_for(widget)

        generated = False
        if isinstance(widget, TextEditorWidget):
            duplicate: QWidget = TextEditorWidget()
            duplicate.setDocument(widget.document())
            # set_path() *after* setDocument() -- it attaches the JSON highlighter (if any) to
            # whatever document is current at the time, which needs to be the shared one both
            # views actually edit, not the throwaway blank document TextEditorWidget() started with.
            duplicate.set_path(source_state.path)
            # A duplicate is its own QWidget, not sharing widget-level (as opposed to document-
            # level) state with the source -- read-only doesn't carry over on its own, so a split
            # view of a generated file would otherwise silently become editable.
            generated = widget.isReadOnly()
            duplicate.setReadOnly(generated)
            _connect_modification_tracking(duplicate)
        else:
            duplicate = self._new_welcome_tab()

        if generated:
            new_index = target.addTab(duplicate, icons.lock_icon(), label)
        else:
            new_index = target.addTab(duplicate, label)
        target._track_tab(new_index, duplicate, state=_TabState(path=source_state.path))

    def split_from(self, source: TabPane) -> None:
        """Horizontal split: adds a new pane-group beside ``source``'s own group, seeded with a
        duplicate of ``source``'s current tab."""
        if self.split_count >= _MAX_H_SPLITS:
            return
        new_group = self._new_group()
        new_pane = self._new_pane()
        self._duplicate_current_tab(source, new_pane)
        new_group.add_pane(new_pane)
        self._add_group(new_group)

    def vsplit_from(self, source: TabPane) -> None:
        """Vertical split: adds a new pane stacked within ``source``'s own group, seeded with a
        duplicate of ``source``'s current tab."""
        group = source.group
        if group is None or group.vsplit_count >= _MAX_V_SPLITS:
            return
        new_pane = self._new_pane()
        self._duplicate_current_tab(source, new_pane)
        group.add_pane(new_pane)
        self._update_split_buttons()

    def new_tab_in(self, pane: TabPane) -> None:
        """Adds a fresh "Untitled-N.txt" text-editor tab to ``pane`` -- called when a click lands
        on the tab bar's own empty space rather than any existing tab. The shared counter keeps
        labels unique across every pane rather than restarting per-pane."""
        label = f"Untitled-{self._next_tab_number}.txt"
        self._next_tab_number += 1
        editor = TextEditorWidget()
        _connect_modification_tracking(editor)
        new_index = pane.addTab(editor, label)
        pane._track_tab(new_index, editor)
        pane.setCurrentIndex(new_index)

    def find_pane(self, pane_id: int) -> TabPane | None:
        for pane in self.panes:
            if id(pane) == pane_id:
                return pane
        return None

    def on_pane_emptied(self, pane: TabPane) -> None:
        """Called after a tab is dragged or closed out of ``pane`` -- removes it (and its group, if
        that was the group's last pane) unless it's the very last pane in the whole area."""
        if pane.count() != 0 or len(self.panes) <= 1:
            return

        group = pane.group
        group.remove_pane(pane)
        if group.panes:
            group._equalize()
        else:
            self.groups.remove(group)
            group.setParent(None)
            group.deleteLater()
            self._equalize_groups()
        self._update_split_buttons()
