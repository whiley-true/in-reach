"""The main tab panel: a split-capable tab view (max 2 splits -> 3 side-by-side pane-groups) and,
independently, each pane-group can be split vertically once (max 2 stacked panes per group) -- so
the area tops out at 3 x 2 = 6 panes. Splitting duplicates the source pane's current tab into the
new pane (VSCode's "split editor" behavior) rather than leaving it empty -- for a text-editor tab,
the duplicate shares the same underlying QTextDocument, so both views edit the same buffer. Tabs
are closable and reorderable within a pane, and draggable from any pane into any other, regardless
of which group they belong to.

The panel opens on a single Welcome tab. Double-clicking a tab bar's own empty space creates a new
"Untitled-N.txt" text-editor tab. Every tab tracks unsaved changes (the close button becomes a dot,
and the tab's own text turns italic, while dirty; closing a dirty tab prompts Save/Don't Save/
Cancel, with Save falling back to a native Save As dialog the first time), and can be right-clicked
for a VSCode-style context menu (close variants, copy/reveal path actions -- only enabled once a
tab has a real file behind it -- pin, and split). A ``.md`` file opens as a rendered, read-only
:class:`~in_reach.ide.markdown_preview.MarkdownPreviewWidget` instead (PROMPT.md: "please make .md
be preview when opened") -- never dirty, never saveable, same as the Welcome tab.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QMimeData, QPoint, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QDrag,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QMouseEvent,
    QPaintEvent,
    QTextDocument,
)
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMenu,
    QMessageBox,
    QStyle,
    QStyleOptionTab,
    QStylePainter,
    QTabBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from in_reach.app.new_project import is_generated_file
from in_reach.ide import file_dialogs, icons, schema_check, style
from in_reach.ide.diff_view import DiffViewWidget
from in_reach.ide.editor import TextEditorWidget
from in_reach.ide.kanban_board import KanbanBoardView
from in_reach.ide.pane_splitter import PaneSplitter
from in_reach.ide.markdown_preview import MarkdownPreviewWidget
from in_reach.ide.welcome import WelcomeTab

_MIME_TYPE = "application/x-inreach-tab"
_MAX_H_SPLITS = 2  # -> up to 3 pane-groups side by side
_MAX_V_SPLITS = 1  # -> up to 2 panes stacked within one group
_SPLIT_ICON_COLOR = "#808080"
_TAB_CLOSE_ICON_COLOR = "#808080"
_TAB_CLOSE_ICON_SIZE = 14
# A little larger than the icon itself for a comfortable click target -- roughly matches the
# footprint Qt's own auto-created close button used before _install_close_button() replaced it.
_TAB_CLOSE_BUTTON_SIZE = 20
#: PROMPT.md: "When right clicking a tab there should be shortcuts for actions" -- shown as plain
#: (non-interactive) hint text next to the two context-menu entries that already have a real,
#: permanent global shortcut elsewhere (``main_window.py``'s own File menu, ``_SHORTCUT_CLOSE_
#: EDITOR``/``_SHORTCUT_SAVE``). Duplicated as plain strings rather than imported -- main_window.py
#: itself imports this module, so importing back from it here would be circular -- and appended
#: straight into the action's own label text (a QMenu right-aligns text after a literal tab
#: character) rather than via ``QAction.setShortcut()``, which would register a second *live*
#: accelerator for the same key sequence and immediately go ambiguous with the File menu's already-
#: registered one the moment this context menu is open.
_SHORTCUT_HINT_CLOSE = "Ctrl+F4"
_SHORTCUT_HINT_SAVE = "Ctrl+S"


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


def _on_editor_save_requested(widget: TextEditorWidget) -> None:
    # PROMPT.md: "make ctrl + S a save shortcut on the keyboard when on text editor". Looked up
    # dynamically via _owner_pane (same as _on_editor_modified above) rather than bound at connect
    # time, since a tab can move to a different pane later (cross-pane drag, split) without this
    # signal ever being reconnected.
    pane = getattr(widget, "_owner_pane", None)
    if pane is None:
        return
    index = pane.indexOf(widget)
    if index >= 0:
        pane._save_tab(index)


def _on_editor_cursor_changed(widget: TextEditorWidget) -> None:
    # Looked up dynamically via _owner_pane, same reasoning as _on_editor_modified above -- and
    # only re-emitted while widget is actually the pane's own visible tab, so a background tab's
    # cursor (e.g. one just reloaded off disk) never overwrites the status bar for whatever tab
    # the user is actually looking at.
    pane = getattr(widget, "_owner_pane", None)
    if pane is not None and widget is pane.currentWidget():
        pane.cursor_info_changed.emit()


def _connect_editor_signals(editor: TextEditorWidget) -> None:
    editor.document().modificationChanged.connect(
        lambda modified, w=editor: _on_editor_modified(w, modified)
    )
    editor.save_requested.connect(lambda w=editor: _on_editor_save_requested(w))
    editor.cursorPositionChanged.connect(lambda w=editor: _on_editor_cursor_changed(w))
    editor.selectionChanged.connect(lambda w=editor: _on_editor_cursor_changed(w))


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

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draws every tab itself (shape, then label) exactly once each, in italic for a dirty tab
        and upright otherwise (PROMPT.md: "if a file has unsaved edits, its tab text should be in
        italics, and become not italic when saved").

        QTabBar has no per-tab font setter of its own (unlike :meth:`setTabTextColor`); the two
        approaches that look obvious both turned out to be unsafe in practice against this app's
        own QSS-styled tab bars (``style.MAIN_TAB_STYLE``/``BOTTOM_TAB_STYLE``, both routed through
        Qt's ``QStyleSheetStyle`` proxy): directly overwriting a style option's own ``fontMetrics``
        crashes outright, and calling :meth:`QWidget.setFont` on the bar itself from inside
        ``initStyleOption()`` re-enters that same override through ``QStyleSheetStyle``'s own
        style-invalidation machinery, recursing until the stack overflows. Changing the *painter's*
        font instead never touches the widget's own styled properties at all, so neither failure
        mode applies.

        This used to let the base implementation paint every tab upright first, then redraw just
        the dirty ones' own shape+label a second time in italic on top -- which visibly
        double-printed the label (upright glyphs from the first pass showing through the italic
        ones from the second, since italic metrics are rarely pixel-identical to upright ones).
        Painting each tab exactly once, choosing its font up front, avoids that entirely.
        """
        painter = QStylePainter(self)
        base_font = QFont(painter.font())
        italic_font = QFont(base_font)
        italic_font.setItalic(True)
        for index in range(self.count()):
            option = QStyleOptionTab()
            self.initStyleOption(option, index)
            painter.drawControl(QStyle.ControlElement.CE_TabBarTabShape, option)
            painter.save()
            painter.setFont(italic_font if _is_modified(self._pane.widget(index)) else base_font)
            painter.drawControl(QStyle.ControlElement.CE_TabBarTabLabel, option)
            painter.restore()


class TabPane(QTabWidget):
    """One pane of the main panel area -- a closable, reorderable tab strip that accepts a tab
    dragged in from a sibling pane, with a corner widget offering both a horizontal and a vertical
    split button."""

    #: Emitted whenever the *currently visible* tab's own cursor position/selection changes, or the
    #: current tab itself switches -- what the bottom status bar's Ln/Col/Spaces segments (PROMPT.md:
    #: Quick Access Bar work) key off of. Never fired for a background tab.
    cursor_info_changed = pyqtSignal()

    def __init__(self, area: "MainPanelArea", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._area = area
        self.group: "_PaneGroup | None" = None  # set by _PaneGroup.add_pane()
        self.card: QWidget | None = None  # set by _PaneGroup.add_pane()
        self._tab_state: dict[QWidget, _TabState] = {}
        self._enforcing_pin_order = False
        self.currentChanged.connect(lambda _index: self.cursor_info_changed.emit())
        self.currentChanged.connect(lambda _index: self._refresh_preview_button())
        self.setTabBar(_DragTabBar(self))
        self.setMovable(True)
        self.tabBar().tabMoved.connect(self._on_tab_moved)
        self.setTabsClosable(True)
        self.tabCloseRequested.connect(self._handle_tab_close_requested)
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

        # PROMPT.md (Notes-as-Markdown): "magnif[y]ing glass icon should appear next to the split
        # panel icons" -- only while the active tab is an editable Markdown one (see
        # :meth:`_refresh_preview_button`), so it doesn't clutter every other file type's tab bar.
        self.preview_button = QToolButton()
        self.preview_button.setIcon(icons.icon("search", color=_SPLIT_ICON_COLOR, size=icon_size))
        self.preview_button.setIconSize(QSize(icon_size, icon_size))
        self.preview_button.setFixedSize(button_size, button_size)
        self.preview_button.setToolTip("Split panel right with a live Markdown preview")
        self.preview_button.setAutoRaise(True)
        self.preview_button.clicked.connect(lambda: self._area.preview_split_from(self))
        self.preview_button.hide()

        corner = QWidget()
        corner_layout = QHBoxLayout(corner)
        corner_layout.setContentsMargins(0, 0, 0, 0)
        corner_layout.setSpacing(0)
        corner_layout.addWidget(self.preview_button)
        corner_layout.addWidget(self.vsplit_button)
        corner_layout.addWidget(self.split_button)
        self.setCornerWidget(corner, Qt.Corner.TopRightCorner)

    # -- tab tracking (dirty state / file path / pinned) -----------------------------------

    def _track_tab(self, index: int, widget: QWidget, state: "_TabState | None" = None) -> None:
        self._tab_state[widget] = state or _TabState()
        widget._owner_pane = self  # read back dynamically by _on_editor_modified
        if isinstance(widget, TextEditorWidget):
            # Idempotent (a cross-pane drag re-tracks the same already-registered widget/document
            # pair here too, not just a genuinely new tab) -- see MainPanelArea.
            # _register_document_user's own docstring for why this needs to happen at all.
            self._area._register_document_user(widget.document(), widget)
        self._install_close_button(index, widget)
        self._update_close_icon(index)
        # A tab tracked with pinned=True (a cross-pane drag of an already-pinned tab -- see
        # dropEvent()) lands wherever addTab() appended it, which can leave it to the right of an
        # unpinned tab in the destination pane -- re-enforce the same "pinned tabs are always
        # leftmost" invariant _toggle_pin()/_on_tab_moved() keep everywhere else.
        self._enforce_pinned_order()

    def _install_close_button(self, index: int, widget: QWidget) -> None:
        """Swaps ``setTabsClosable(True)``'s auto-created close button for a real ``QToolButton``
        we own. Qt's own auto-created button is a private ``QTabBar::CloseButton`` whose
        ``paintEvent`` always draws the style's built-in ``PE_IndicatorTabClose`` glyph and never
        looks at the button's own ``icon()`` -- ``_update_close_icon``'s ``setIcon()`` calls change
        that button's ``icon`` property without ever changing what actually gets painted, so the
        dirty-dot/pin icon swap silently never showed (confirmed by forcing an unmistakable icon on
        the stock button and grabbing it -- the paint never changed). A plain ``QToolButton``
        installed via ``setTabButton`` paints its own ``icon()`` normally, so the rest of
        ``_update_close_icon`` needs no change once this is in front of it.

        A no-op once a tab already has its own button installed (idempotent, like ``_track_tab``
        itself) -- only ever replaces Qt's own stock button the first time."""
        bar = self.tabBar()
        position = QTabBar.ButtonPosition.RightSide
        existing = bar.tabButton(index, position)
        if isinstance(existing, QToolButton):
            return
        button = QToolButton(bar)
        button.setAutoRaise(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedSize(_TAB_CLOSE_BUTTON_SIZE, _TAB_CLOSE_BUTTON_SIZE)
        button.setIconSize(QSize(_TAB_CLOSE_ICON_SIZE, _TAB_CLOSE_ICON_SIZE))
        # Resolves the tab's *current* index at click time (not whatever index was captured here)
        # -- a pin/reorder/drag can move this tab well after this button was installed.
        button.clicked.connect(lambda _checked=False, w=widget: self._handle_tab_close_requested(self.indexOf(w)))
        bar.setTabButton(index, position, button)

    def _tab_state_for(self, widget: QWidget) -> _TabState:
        return self._tab_state.setdefault(widget, _TabState())

    def _release_tab_widget(self, widget: QWidget | None) -> None:
        """Common cleanup for a tab's content widget wherever it's actually being destroyed (never
        for a cross-pane drag, which reparents the same widget rather than destroying it) -- pairs
        with the registration ``_track_tab`` does, so a shared document's own original owner is
        never destroyed while another view still shares it (see ``MainPanelArea.
        _register_document_user``'s own docstring for why that specifically -- not just the
        document -- has to wait)."""
        if widget is None:
            return
        self._tab_state.pop(widget, None)
        if isinstance(widget, TextEditorWidget):
            if not self._area._unregister_document_user(widget.document(), widget):
                # Kept alive rather than destroyed -- see _unregister_document_user's own
                # docstring; MainPanelArea itself deletes it once it's safe to.
                widget.hide()
                widget.setParent(None)
                return
        widget.deleteLater()

    def _refresh_preview_button(self) -> None:
        """Shows :attr:`preview_button` only while the active tab is an editable Markdown one --
        a :class:`~in_reach.ide.editor.TextEditorWidget` opened via ``open_file(...,
        editable_markdown=True)``, identifiable after the fact by its own ``.md`` path (a plain
        :class:`~in_reach.ide.markdown_preview.MarkdownPreviewWidget` tab, opened for every other
        ``.md`` file, is never a ``TextEditorWidget`` in the first place -- see ``open_file``)."""
        widget = self.currentWidget()
        is_editable_markdown = (
            isinstance(widget, TextEditorWidget) and widget.path is not None and widget.path.suffix.lower() == ".md"
        )
        # A floating (popout-window) pane can't split at all -- see split_from's own docstring.
        self.preview_button.setVisible(is_editable_markdown and self.group is not None)

    def _update_close_icon(self, index: int) -> None:
        button = self.tabBar().tabButton(index, QTabBar.ButtonPosition.RightSide)
        # PROMPT.md: "if a file has unsaved edits, its tab text should be in italics, and become
        # not italic when saved" -- _DragTabBar.paintEvent() reads dirty state fresh on every
        # paint, so nothing needs updating there directly; it just needs telling to actually repaint
        # now, since a modificationChanged signal alone doesn't imply the tab bar redraws itself.
        self.tabBar().update()
        if button is None:
            return
        widget = self.widget(index)
        if self._tab_state_for(widget).pinned:
            name = "tab_pin"
        elif _is_modified(widget):
            name = "tab_dirty"
        else:
            name = "win_close"
        button.setIcon(icons.icon(name, color=_TAB_CLOSE_ICON_COLOR, size=_TAB_CLOSE_ICON_SIZE))

    # -- closing, with unsaved-changes handling ---------------------------------------------

    def _handle_tab_close_requested(self, index: int) -> None:
        """The tab bar's built-in close button, clicked -- redirected to unpin instead of close
        for a pinned tab (PROMPT.md: "when a tab is pinned it should have a pin icon instead of an
        x icon, when the pin is clicked it should become unpinned and the pin should convert to a
        x"), since that same button already swaps to the pin icon while pinned (see
        :meth:`_update_close_icon`)."""
        widget = self.widget(index)
        if widget is not None and self._tab_state_for(widget).pinned:
            self._toggle_pin(index)
            return
        self._maybe_close(index)

    def _close_tab(self, index: int) -> None:
        widget = self.widget(index)
        self.removeTab(index)
        self._release_tab_widget(widget)
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
        chosen, _selected_filter = file_dialogs.get_save_file_name(
            self, "Save As", str(default_dir / suggested_name)
        )
        return Path(chosen) if chosen else None

    def _save_tab(self, index: int) -> bool:
        widget = self.widget(index)
        if not isinstance(widget, TextEditorWidget):
            # A Markdown preview (or the Welcome tab) has nothing to save -- there's no source
            # view to edit here, just the rendered document; QTextBrowser.toPlainText() would
            # return that render's own stripped-down text, not the original Markdown source, which
            # would silently corrupt the file if this weren't guarded.
            return False
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

    def open_file(self, path: Path, *, force_reload: bool = False, editable_markdown: bool = False) -> None:
        """"Open File" (the File menu, and clicking a file in the Explorer panel) -- adds ``path``
        as a new tab, reading its content in. Switches to the existing tab instead of duplicating
        it if ``path`` is already open in this pane.

        PROMPT.md: "with the exception of pinned tabs and the welcome page tab: clicking on a file
        that is not open should only open a new tab if the present tab has unsaved changes[;]
        otherwise the present tab should change to the selected file (this is to prevent too many
        tabs from spawning)" -- when ``path`` isn't already open anywhere in this pane, the current
        tab's own content is silently replaced instead of adding a new tab alongside it, unless
        that current tab is pinned, is the Welcome tab, or has unsaved changes (see
        :meth:`_reusable_tab_index`).

        Args:
            path: The file to open.
            force_reload: Re-reads ``path`` from disk and refreshes the already-open tab's content
                even if it's already open (the default, ``False``, just switches to it, leaving
                whatever was loaded when it was first opened) -- for a file that's meant to reflect
                its current on-disk content every time it's (re-)opened, e.g. the Dashboard's own
                "View Output.txt" button, which regenerates the file it opens on every click (see
                :meth:`~in_reach.ide.main_window.MainWindow.view_output_txt`).
            editable_markdown: Opens a ``.md`` file as a real, editable
                :class:`~in_reach.ide.editor.TextEditorWidget` instead of the usual read-only
                :class:`~in_reach.ide.markdown_preview.MarkdownPreviewWidget` (PROMPT.md, "Notes"
                when Notes format is Markdown: "editor should be .md" -- with the magnifying-glass
                split-to-live-preview icon, see
                :meth:`_refresh_preview_button`, this is where an editable Markdown source and its
                live rendered preview both come from). Ignored for any other suffix.
        """
        for index in range(self.count()):
            if self._tab_state_for(self.widget(index)).path == path:
                self.setCurrentIndex(index)
                if force_reload:
                    self._reload_tab(index)
                return
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            QMessageBox.critical(self, "in-reach", f"Couldn't open {path.name}:\n{exc}")
            return

        # PROMPT.md: "please make .md be preview when opened" -- a rendered, read-only view
        # instead of the plain text editor every other file type gets here, unless the caller
        # explicitly asked for an editable one (see editable_markdown's own docstring above).
        if path.suffix.lower() == ".md" and not editable_markdown:
            widget: QWidget = MarkdownPreviewWidget(path=path)
            widget.setMarkdown(text)
            tab_icon = None
        else:
            editor = TextEditorWidget(path=path)
            editor.setPlainText(text)
            # PROMPT.md: "the autogenerated files should not be editable" -- build/'s own compiled
            # output and *.autogenerated.json snapshots are overwritten wholesale on every
            # successful build/resync, so an edit made here would just silently vanish rather than
            # doing anything.
            generated = is_generated_file(path)
            editor.setReadOnly(generated)
            _connect_editor_signals(editor)
            # PROMPT.md: "they have a padlock symbol in the tab" -- a generated file's read-only
            # status never changes for the tab's own lifetime, unlike the dirty-state icon on its
            # close button, so this is set once here rather than needing its own refresh hook.
            tab_icon = icons.lock_icon() if generated else None
            widget = editor

        reuse_index = self._reusable_tab_index()
        if reuse_index is not None:
            old_widget = self.widget(reuse_index)
            self.removeTab(reuse_index)
            self._release_tab_widget(old_widget)
            if tab_icon is not None:
                new_index = self.insertTab(reuse_index, widget, tab_icon, path.name)
            else:
                new_index = self.insertTab(reuse_index, widget, path.name)
        elif tab_icon is not None:
            new_index = self.addTab(widget, tab_icon, path.name)
        else:
            new_index = self.addTab(widget, path.name)
        self._track_tab(new_index, widget, state=_TabState(path=path))
        self.setCurrentIndex(new_index)

    def open_diff(self, rel_path: str, *, old_text: str | None, new_text: str | None) -> None:
        """Opens (or refreshes and switches to, if already open) a side-by-side
        :class:`~in_reach.ide.diff_view.DiffViewWidget` tab for ``rel_path``'s own uncommitted
        change -- PROMPT.md: "when clicking on changes to a file (in the changes tab) a tab should
        appear showing the original on the left and highlighted changes on the right (like vscode
        git)". Called by ``MainWindow.vcs_open_diff`` whenever a file is clicked in the Git panel's
        own "Changes" list.

        Tracked with ``_TabState(path=None)`` deliberately, unlike :meth:`open_file` -- a diff view
        isn't the real file itself (giving it that same :class:`Path` would make this method's own
        dedup below collide with :meth:`open_file`'s: clicking ``rel_path`` in the Explorer while
        its diff tab happens to sit earlier in this pane would silently land on the read-only diff
        instead of the real editable file). Matched by :attr:`~in_reach.ide.diff_view.
        DiffViewWidget.rel_path` instead, a plain widget attribute :meth:`open_file` never looks at,
        so the two can never step on each other.

        Always refreshes an already-open tab's own content before switching to it (unlike
        ``open_file``'s ``force_reload``, which defaults to leaving a re-opened file's stale
        content alone) -- an uncommitted change is live working-tree state, stale the moment
        anything else touches the file, so there's no "intentionally frozen" reading to preserve
        the way there is for `force_reload`'s own default.
        """
        for index in range(self.count()):
            widget = self.widget(index)
            if isinstance(widget, DiffViewWidget) and widget.rel_path == rel_path:
                widget.set_diff(old_text, new_text)
                self.setCurrentIndex(index)
                return
        diff_widget = DiffViewWidget(rel_path=rel_path, old_text=old_text, new_text=new_text)
        label = Path(rel_path).name
        new_index = self.addTab(diff_widget, icons.icon("git", color=_SPLIT_ICON_COLOR), f"{label} (diff)")
        self._track_tab(new_index, diff_widget, state=_TabState(path=None))
        self.setCurrentIndex(new_index)

    def open_head_file(self, rel_path: str, text: str) -> None:
        """Opens (or refreshes and switches to, if already open) a read-only tab showing
        ``rel_path``'s own content at ``HEAD`` -- "Open File (HEAD)" (PROMPT.md: "in the changes it
        should be possible to right click the file and then see: ... open file (HEAD) ...").

        Tracked with ``_TabState(path=None)``, same reasoning as :meth:`open_diff` -- matched by its
        own ``_head_rel_path`` attribute (a plain widget attribute :meth:`open_file` never looks at)
        instead, so it can never collide with a real editable tab for the same file.
        """
        for index in range(self.count()):
            widget = self.widget(index)
            if getattr(widget, "_head_rel_path", None) == rel_path:
                widget.setPlainText(text)
                widget.document().setModified(False)
                self.setCurrentIndex(index)
                return
        editor = TextEditorWidget(path=Path(rel_path))
        editor.setPlainText(text)
        editor.setReadOnly(True)
        editor._head_rel_path = rel_path
        _connect_editor_signals(editor)
        label = f"{Path(rel_path).name} (HEAD)"
        new_index = self.addTab(editor, icons.lock_icon(), label)
        self._track_tab(new_index, editor, state=_TabState(path=None))
        self.setCurrentIndex(new_index)

    def open_commit_diff(
        self, rel_path: str, sha: str, *, old_text: str | None, new_text: str | None
    ) -> None:
        """Opens (or refreshes and switches to, if already open) a single, *unified* (not split)
        :class:`~in_reach.ide.unified_diff_view.UnifiedDiffViewWidget` tab for ``rel_path`` as
        changed by commit ``sha`` -- PROMPT.md: "please make it so that when clicking in history on
        commits - it extends to show a list of files changed (which can then be clicked on to view
        (please note this should be a single (not split) view, see sample.png for styling))".

        Tracked with ``_TabState(path=None)``, same reasoning as :meth:`open_diff`/
        :meth:`open_head_file` -- matched by ``(rel_path, sha)`` together (a single file can appear
        in more than one commit, and different commits' own diffs of it are never the same tab).
        """
        from in_reach.ide.unified_diff_view import UnifiedDiffViewWidget

        for index in range(self.count()):
            widget = self.widget(index)
            if isinstance(widget, UnifiedDiffViewWidget) and widget.rel_path == rel_path and widget.sha == sha:
                widget.set_diff(old_text, new_text)
                self.setCurrentIndex(index)
                return
        diff_widget = UnifiedDiffViewWidget(rel_path=rel_path, sha=sha, old_text=old_text, new_text=new_text)
        label = f"{Path(rel_path).name} ({sha[:8]})"
        new_index = self.addTab(diff_widget, icons.icon("git", color=_SPLIT_ICON_COLOR), label)
        self._track_tab(new_index, diff_widget, state=_TabState(path=None))
        self.setCurrentIndex(new_index)

    def open_commit_file(self, rel_path: str, sha: str, text: str) -> None:
        """Opens (or refreshes and switches to, if already open) a read-only tab showing
        ``rel_path``'s own content as of commit ``sha`` -- "Open File" (PROMPT.md, a later pass:
        "and right click should have the option to open file", the Git panel's own History section
        "Files Changed" list). Same shape as :meth:`open_head_file`, just for an arbitrary commit
        instead of always ``HEAD`` -- tracked with ``_TabState(path=None)``, matched by ``(rel_path,
        sha)`` together, same reasoning as :meth:`open_commit_diff`.
        """
        for index in range(self.count()):
            widget = self.widget(index)
            if getattr(widget, "_commit_file_key", None) == (rel_path, sha):
                widget.setPlainText(text)
                widget.document().setModified(False)
                self.setCurrentIndex(index)
                return
        editor = TextEditorWidget(path=Path(rel_path))
        editor.setPlainText(text)
        editor.setReadOnly(True)
        editor._commit_file_key = (rel_path, sha)
        _connect_editor_signals(editor)
        label = f"{Path(rel_path).name} ({sha[:8]})"
        new_index = self.addTab(editor, icons.lock_icon(), label)
        self._track_tab(new_index, editor, state=_TabState(path=None))
        self.setCurrentIndex(new_index)

    def open_kanban_board(self, store, board_id: int) -> None:
        """Opens (or switches to, if already open in this pane) the Kanban board ``board_id`` as an
        editor tab -- PROMPT.md: "when clicked it should load the default board in the editor view".
        Tracked with ``_TabState(path=None)``, same reasoning as :meth:`open_diff` -- a board isn't a
        file, so it must never collide with :meth:`open_file`'s own path-based dedup; matched by
        :attr:`~in_reach.ide.kanban_board.KanbanBoardView.board_id` instead."""
        for index in range(self.count()):
            widget = self.widget(index)
            if isinstance(widget, KanbanBoardView) and widget.board_id == board_id:
                self.setCurrentIndex(index)
                return
        board = store.get_board(board_id)
        if board is None:
            return
        view = KanbanBoardView(store, board_id)
        new_index = self.addTab(view, icons.icon("kanban", color=_SPLIT_ICON_COLOR), board.name)
        self._track_tab(new_index, view, state=_TabState(path=None))
        self.setCurrentIndex(new_index)

    def _reusable_tab_index(self) -> int | None:
        """The current tab's index, if it's safe for :meth:`open_file` to silently replace with a
        newly-opened file instead of adding a new tab alongside it -- never the Welcome tab or a
        pinned tab, and never a tab with unsaved changes (PROMPT.md, see :meth:`open_file`'s own
        docstring)."""
        if self.count() == 0:
            return None
        index = self.currentIndex()
        widget = self.widget(index)
        if isinstance(widget, WelcomeTab):
            return None
        if self._tab_state_for(widget).pinned:
            return None
        if _is_modified(widget):
            return None
        return index

    def _reload_tab(self, index: int) -> None:
        """Re-reads the tab at ``index`` from disk and refreshes its content in place -- see
        :meth:`open_file`'s own ``force_reload`` docstring. A no-op for a tab with no path, or one
        whose file can no longer be read."""
        widget = self.widget(index)
        path = self._tab_state_for(widget).path
        if path is None:
            return
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return
        if isinstance(widget, TextEditorWidget):
            widget.setPlainText(text)
            widget.document().setModified(False)
        elif isinstance(widget, MarkdownPreviewWidget):
            widget.setMarkdown(text)

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

    def close_all_tabs(self) -> None:
        """"Close All" -- MainWindow's own command-palette entry for the tab context menu's
        identically-named action (see :meth:`_close_all`), exposed here as a real public method so
        it can be reached with no specific tab already right-clicked."""
        self._close_all()

    def split_active_tab_right(self) -> None:
        """"Split Right" (Ctrl+\\, matching VSCode's own default "Split Editor" binding) -- splits
        whichever tab is currently active, same as picking "Split Right" from that tab's own
        context menu (see :meth:`_split_tab`) would, just without needing to right-click it first.
        A no-op if this pane has no tabs, or is already at :data:`_MAX_H_SPLITS`."""
        if self.count() == 0 or self.group is None or self._area.split_count >= _MAX_H_SPLITS:
            return
        self._split_tab(self.currentIndex(), vertical=False)

    def split_active_tab_down(self) -> None:
        """"Split Down" -- same as :meth:`split_active_tab_right`, just the vertical direction (no
        VSCode default binding of its own -- "Split Editor Down" ships unbound there too)."""
        if self.count() == 0 or self.group is None or self.group.vsplit_count >= _MAX_V_SPLITS:
            return
        self._split_tab(self.currentIndex(), vertical=True)

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
        self._enforce_pinned_order()
        self._update_close_icon(self.indexOf(widget))

    def _on_tab_moved(self, _from: int, _to: int) -> None:
        """A plain drag reorder (``setMovable(True)``'s own built-in handling, see _DragTabBar's
        docstring) has no notion of pinned tabs at all, and would happily let the user drag an
        unpinned tab to the left of a pinned one -- re-enforce the invariant after every move,
        whatever moved it."""
        self._enforce_pinned_order()

    def _enforce_pinned_order(self) -> None:
        """Pinned tabs must always occupy the front of the strip, in their own existing relative
        order, with every unpinned tab after them in *its* own existing relative order -- a stable
        partition on the current left-to-right order, not a fixed target position, so this is
        idempotent (a no-op once the invariant already holds, which it will after every call here)
        and never reorders within either group on its own."""
        if self._enforcing_pin_order:
            return
        self._enforcing_pin_order = True
        try:
            widgets = [self.widget(i) for i in range(self.count())]
            pinned = [w for w in widgets if self._tab_state_for(w).pinned]
            unpinned = [w for w in widgets if not self._tab_state_for(w).pinned]
            bar = self.tabBar()
            for target_index, widget in enumerate(pinned + unpinned):
                current_index = self.indexOf(widget)
                if current_index != target_index:
                    bar.moveTab(current_index, target_index)
        finally:
            self._enforcing_pin_order = False

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
        # PROMPT.md: "Please also add a save option (for the jsons (other tab types may later have
        # other options))" -- only ever meaningful for a real TextEditorWidget tab (a Markdown
        # preview/the Welcome tab has no source buffer to write back out, see _save_tab's own
        # guard), so it's disabled rather than shown for every other tab type.
        menu.addAction(
            f"Save\t{_SHORTCUT_HINT_SAVE}", lambda: self._save_tab(index)
        ).setEnabled(isinstance(widget, TextEditorWidget))
        menu.addSeparator()

        menu.addAction(f"Close\t{_SHORTCUT_HINT_CLOSE}", lambda: self._maybe_close(index))
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
        menu.addAction("Reveal in Dashboard View", self._reveal_in_explorer_view).setEnabled(has_path)
        menu.addSeparator()

        menu.addAction("Unpin" if state.pinned else "Pin", lambda: self._toggle_pin(index))
        menu.addSeparator()

        can_hsplit = self.group is not None and self._area.split_count < _MAX_H_SPLITS
        can_vsplit = self.group is not None and self.group.vsplit_count < _MAX_V_SPLITS
        menu.addAction("Split Right", lambda: self._split_tab(index, vertical=False)).setEnabled(can_hsplit)
        menu.addAction("Split Down", lambda: self._split_tab(index, vertical=True)).setEnabled(can_vsplit)
        menu.addSeparator()

        # PROMPT.md: "please also add a move to window option - this should move the tab to a
        # popout window where other tabs can also be dragged to" -- see
        # MainPanelArea.move_tab_to_new_window's own docstring for how the popout window shares
        # this same area's drag-and-drop/document-lifetime machinery.
        menu.addAction("Move to Window", lambda: self._area.move_tab_to_new_window(self, index))

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

        # PaneSplitter, not a real QSplitter -- see pane_splitter.py's own module docstring for why
        # (PROMPT.md: "if i have two tabs open ... and i close the welcome, things crash", which
        # turned out to be a native access violation reproducible from manually dragging a real
        # QSplitterHandle, independent of tab-closing/file type, that no amount of working around
        # QSplitter itself (setOpaqueResize(False), etc.) ever fully stopped).
        self.splitter = PaneSplitter(Qt.Orientation.Vertical)
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
        self.splitter.removeWidget(card)
        card.setParent(None)
        card.deleteLater()
        self._equalize()

    def _equalize(self) -> None:
        count = self.splitter.count()
        if count <= 0:
            return
        total = max(self.splitter.height(), count * 150)
        self.splitter.setSizes([total // count] * count)


class _PopoutWindow(QWidget):
    """A floating top-level window for a single tab moved out via "Move to Window" (PROMPT.md,
    see :meth:`MainPanelArea.move_tab_to_new_window`'s own docstring) -- hosts exactly one
    :class:`TabPane`, which other tabs (from this window or the main one) can be dragged into just
    like any other pane.

    Closing this window (its own titlebar close button, Alt+F4, etc.) never destroys it directly --
    it instead runs every tab in :attr:`pane` through the same prompt-if-dirty close path a single
    tab's own close button uses (cancellable, same as closing any other tab), then ignores that
    *particular* close event itself. Once :attr:`pane` is genuinely empty, ``on_pane_emptied``'s own
    (deliberately one-event-loop-tick-deferred, see its own docstring) teardown calls
    :meth:`force_close` -- the *only* place this window is ever really torn down, whether it emptied
    by every tab being closed this way or by the last one being dragged back out into another pane
    instead. Routing both through the same path avoids re-introducing the exact class of reentrant-
    teardown crash ``on_pane_emptied`` was written to fix in the first place (PROMPT.md: "if i have
    two tabs open ... and i close the welcome, things crash").

    PROMPT.md: "we have a bug where if a the last tab in a popped out window is closed, it stays
    open ... also the close icon is not closing the close window" -- :meth:`force_close` needs its
    own ``_closing`` flag rather than just calling :meth:`close` a second time, because ``close()``
    re-enters this exact :meth:`closeEvent` -- and by the time :meth:`force_close` runs, ``pane`` is
    already empty, so the ``while`` loop below no-ops and execution falls straight through to the
    same unconditional ``event.ignore()`` the first (real, tab-still-open) close used, permanently
    refusing to ever actually close the window. ``_closing`` is what tells this *second* pass to
    accept instead.
    """

    def __init__(self, pane: TabPane, *, title: str) -> None:
        super().__init__(None)  # no parent -- a real top-level window, movable/closable on its own
        self.pane = pane
        self._closing = False
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(style.wrap_tab_widget(pane, flush_top=True))
        self.resize(900, 650)

    def closeEvent(self, event) -> None:  # noqa: ANN001 -- QCloseEvent
        if self._closing:
            event.accept()
            return
        while self.pane.count() > 0:
            if not self.pane._maybe_close(0):
                event.ignore()
                return
        event.ignore()  # see this class's own docstring -- force_close() closes it for real

    def force_close(self) -> None:
        """The only real way this window ever actually closes -- see this class's own docstring
        for why plain :meth:`close` can't do it once :attr:`pane` is already empty."""
        self._closing = True
        self.close()


class MainPanelArea(QWidget):
    """Holds one or more :class:`_PaneGroup` instances side by side in a horizontal splitter, up
    to :data:`_MAX_H_SPLITS` horizontal splits, each in turn holding up to one vertical split."""

    #: Re-emitted whenever *any* pane's own ``cursor_info_changed`` fires (a tab switch, or the
    #: current tab's cursor/selection moving) -- MainWindow connects to this once, rather than to
    #: one specific pane's own signal, since which pane is :attr:`active_pane` can now change over
    #: the panel's lifetime (see that property's own docstring). ``_update_status_cursor_info``
    #: always re-reads :attr:`active_pane` fresh when this fires, so a background pane's own cursor
    #: moving harmlessly recomputes the same (unchanged) status-bar text rather than the active
    #: one's.
    cursor_info_changed = pyqtSignal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        root_dir: Path | None = None,
        reveal_in_explorer: Callable[[], None] | None = None,
        on_project_opened: Callable[[Path], None] | None = None,
        on_settings_changed: Callable[[], None] | None = None,
        on_file_saved: Callable[[Path], None] | None = None,
        project_title: Callable[[], str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.root_dir = root_dir or Path.cwd()
        self.reveal_in_explorer = reveal_in_explorer
        self.on_project_opened = on_project_opened
        self.on_settings_changed = on_settings_changed
        self.on_file_saved = on_file_saved
        #: PROMPT.md: "the top of the popout window should be called the gametype name (so that if
        #: multiple projects with multiple popouts are open it doesnt get confusing)" -- injectable
        #: (MainWindow passes the active project's own title, see :meth:`move_tab_to_new_window`),
        #: same reasoning as ``reveal_in_explorer``/``on_project_opened`` above: this widget stays
        #: framework-agnostic about what "the active project" even means.
        self.project_title = project_title
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # See _PaneGroup.splitter's own comment -- same reasoning applies to this (horizontal,
        # between pane-groups) splitter too.
        self._splitter = PaneSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(style.PANEL_GAP)
        # Same reasoning as _PaneGroup.splitter above -- in particular, this is what stops the
        # leftmost pane-group from being drag-resized down to zero width (effectively hiding it).
        self._splitter.setChildrenCollapsible(False)
        layout.addWidget(self._splitter)

        # PROMPT.md: "when a new file is opened it should load in the LAST ACTIVE/USED tab" -- the
        # pane most recently given keyboard focus (clicking into its content) or switched to a
        # different tab within it; see :attr:`active_pane`/:meth:`_mark_active`/
        # :meth:`_on_focus_changed`.
        self._last_active_pane: TabPane | None = None
        QApplication.instance().focusChanged.connect(self._on_focus_changed)

        # Every QTextDocument any currently-open TextEditorWidget displays, keyed to the set of
        # widgets currently displaying it; _document_owner tracks which one of those widgets
        # originally created it, and _parked_owners holds one kept-alive-but-hidden past its own
        # tab closing (deferred destruction) -- see _register_document_user's own docstring.
        self._document_users: dict[QTextDocument, set[TextEditorWidget]] = {}
        self._document_owner: dict[QTextDocument, TextEditorWidget] = {}
        self._parked_owners: dict[QTextDocument, TextEditorWidget] = {}

        self.groups: list[_PaneGroup] = []
        #: Panes living in a popout window (PROMPT.md: "move to window") rather than any
        #: _PaneGroup/the main splitter -- see :meth:`move_tab_to_new_window`. Kept separate from
        #: ``groups`` (rather than e.g. a group-of-one with no splitter) since a popout is a
        #: completely different top-level window, not another slot in this widget's own layout.
        self._floating_panes: list[TabPane] = []
        #: The popout window hosting each of :attr:`_floating_panes`, keyed by pane -- a plain
        #: Python reference is also what keeps a parent-less top-level QWidget alive at all.
        self._popout_windows: dict[TabPane, "_PopoutWindow"] = {}

        first_group = self._new_group()
        first_pane = self._new_pane()
        welcome = self._new_welcome_tab()
        welcome_index = first_pane.addTab(welcome, "Welcome")
        first_pane._track_tab(welcome_index, welcome)
        first_group.add_pane(first_pane)
        self._add_group(first_group)
        self._next_tab_number = 1
        self._last_active_pane = first_pane

    @property
    def panes(self) -> list[TabPane]:
        return [pane for group in self.groups for pane in group.panes] + self._floating_panes

    @property
    def active_pane(self) -> TabPane:
        """The pane the File menu's New File/Open File/Save/Close Editor actions target -- the
        pane most recently interacted with (a tab switch within it, or a click into its content),
        tracked by :meth:`_mark_active`/:meth:`_on_focus_changed`. Falls back to the first pane if
        the last-active one has since been closed (or nothing has been interacted with yet)."""
        if self._last_active_pane is not None and self._last_active_pane in self.panes:
            return self._last_active_pane
        return self.panes[0]

    def _mark_active(self, pane: TabPane) -> None:
        self._last_active_pane = pane

    # -- shared-document lifetime (split-pane duplicates) -----------------------------------------

    def _register_document_user(self, document: QTextDocument, widget: "TextEditorWidget") -> None:
        """A confirmed, reproducible native crash (PROMPT.md: "if i have two tabs open ... and i
        close the welcome, things crash"), isolated -- via Application Verifier's page heap, and
        eventually a from-scratch, zero-custom-code repro (two bare ``QPlainTextEdit``s, no gutter/
        minimap/breadcrumb/splitter/pane code at all) -- to a genuine PyQt6/Qt6 bug: destroying the
        *specific* editor whose own construction first created a ``QTextDocument`` corrupts that
        document's internal state for every other view still sharing it (this app's split-editor
        duplicate -- module docstring: "the duplicate shares the same underlying QTextDocument, so
        both views edit the same buffer"), *regardless* of the document's own Qt-parent, its own
        deletion state, or how many other views reference it. Destroying any *other* (non-owning)
        view sharing the same document is always safe. (A single ``setDocument()`` call per editor
        instance, never a second one replacing an already-set document, is also required --
        :meth:`~in_reach.ide.editor._PlainTextEditor.__init__`'s own docstring covers that half.)

        Every :class:`TextEditorWidget` tab registers its own document here as soon as it's tracked
        (see ``TabPane._track_tab``); the first registration for a given document also records
        ``widget`` as that document's owner (see :meth:`_unregister_document_user`). A cross-pane
        drag re-registers the same widget/document pair (harmless -- a plain ``set``, not a counter)
        rather than a second, more meaningful share.
        """
        users = self._document_users.get(document)
        if users is None:
            users = set()
            self._document_users[document] = users
            self._document_owner[document] = widget
        users.add(widget)

    def _unregister_document_user(self, document: QTextDocument, widget: "TextEditorWidget") -> bool:
        """Pairs with :meth:`_register_document_user` -- called wherever a tab's content widget
        would normally be destroyed (never for a cross-pane drag, which reparents rather than
        destroys). Returns whether the caller may actually ``deleteLater()`` ``widget`` now.

        Ordinarily ``True`` -- but if ``widget`` is the document's own owner (see
        :meth:`_register_document_user`) and other views still share it, returns ``False`` instead:
        the caller must keep ``widget`` alive (hidden, unparented) rather than destroy it, per this
        method's own docstring. :meth:`~in_reach.ide.tabs.TabPane._release_tab_widget` is the only
        caller, and does exactly that. Once every other sharing view has since closed too, whichever
        one closes last triggers this method to finally ``deleteLater()`` the parked owner itself
        (its own destruction cascades to the document too, since it was never reparented away from
        it) -- the caller never needs to know that happened.
        """
        users = self._document_users.get(document)
        if users is None:
            return True
        users.discard(widget)

        owner = self._document_owner.get(document)
        parked = self._parked_owners.get(document)
        if parked is not None:
            if users - {parked}:
                return True  # still other real views besides the parked owner
            self._document_users.pop(document, None)
            self._document_owner.pop(document, None)
            del self._parked_owners[document]
            parked.deleteLater()
            return True

        if not users:
            self._document_users.pop(document, None)
            self._document_owner.pop(document, None)
            return True

        if owner is widget:
            self._parked_owners[document] = widget
            return False

        return True

    def _on_focus_changed(self, _old: QWidget | None, new: QWidget | None) -> None:
        """Catches keyboard focus landing anywhere *inside* a pane's own current tab (clicking into
        an editor without switching tabs) -- :meth:`_mark_active` alone only fires on an actual tab
        switch, which misses that case entirely."""
        widget = new
        while widget is not None:
            if isinstance(widget, TabPane) and widget in self.panes:
                self._mark_active(widget)
                return
            widget = widget.parentWidget()

    @property
    def split_count(self) -> int:
        """Horizontal split count -- ``len(self.groups) - 1``."""
        return len(self.groups) - 1

    def save_all(self) -> None:
        """"Save All" across every pane, not just the active one."""
        for pane in self.panes:
            pane.save_all()

    def kanban_views(self) -> list[KanbanBoardView]:
        """Every open Kanban board tab, across every pane (popout windows included)."""
        return [
            pane.widget(index)
            for pane in self.panes
            for index in range(pane.count())
            if isinstance(pane.widget(index), KanbanBoardView)
        ]

    def refresh_kanban_tabs(self) -> None:
        """Brings every open Kanban board tab's title in line with its board's current name, and
        closes the tab of any board that no longer exists (deleted from the sidebar panel, say) --
        called by MainWindow whenever the Kanban store changes."""
        for pane in list(self.panes):
            for index in reversed(range(pane.count())):
                widget = pane.widget(index)
                if not isinstance(widget, KanbanBoardView):
                    continue
                board = widget.store.get_board(widget.board_id)
                if board is None:
                    pane._close_tab(index)
                elif pane.tabText(index) != board.name:
                    pane.setTabText(index, board.name)

    def open_file_paths(self) -> set[Path]:
        """Every file path currently open in some tab, across every pane (popout windows
        included) -- what the Search panel's "Search only in Open Editors" toggle searches."""
        paths: set[Path] = set()
        for pane in self.panes:
            for index in range(pane.count()):
                path = pane._tab_state_for(pane.widget(index)).path
                if path is not None:
                    paths.add(path)
        return paths

    def _open_tab_locations(self, paths: set[Path]) -> list[tuple[TabPane, int]]:
        return [
            (pane, index)
            for pane in self.panes
            for index in range(pane.count())
            if pane._tab_state_for(pane.widget(index)).path in paths
        ]

    def save_paths(self, paths: list[Path]) -> None:
        """Saves every already-open tab for one of ``paths`` that has unsaved edits -- used by
        :meth:`~in_reach.ide.main_window.MainWindow._warn_unsaved_settings_before_rvt`'s own "Save
        and Continue" button (PROMPT.md) to clear exactly the dirty settings/script_settings/
        strings.json tabs blocking an RVT launch, without touching unrelated dirty tabs elsewhere."""
        for pane, index in self._open_tab_locations(set(paths)):
            if _is_modified(pane.widget(index)):
                pane._save_tab(index)

    def dirty_tab_names(self, paths: list[Path]) -> list[str]:
        """The (sorted, deduplicated) file names of any already-open tab for one of ``paths`` that
        has unsaved edits -- PROMPT.md: RVT resyncing a project's own settings/script_settings/
        strings.json "with unsaved changes should pop up showing all unsaved changes[.]" Used by
        :meth:`~in_reach.ide.main_window.MainWindow._on_watched_bin_changed` to decide whether that
        resync needs confirming first."""
        names = {
            pane._tab_state_for(pane.widget(index)).path.name
            for pane, index in self._open_tab_locations(set(paths))
            if _is_modified(pane.widget(index))
        }
        return sorted(names)

    def reload_open_tabs(self, paths: list[Path]) -> None:
        """Re-reads every already-open tab for one of ``paths`` from disk in place -- PROMPT.md:
        RVT resyncing a project's own settings/script_settings/strings.json "without saved changes
        should immediately update in place." Every occurrence across every pane is reloaded (not
        just the first), so a duplicate opened via a pane split stays in sync too."""
        for pane, index in self._open_tab_locations(set(paths)):
            pane._reload_tab(index)

    def _open_tab_locations_under(self, folder: Path) -> list[tuple[TabPane, int]]:
        return [
            (pane, index)
            for pane in self.panes
            for index in range(pane.count())
            if (path := pane._tab_state_for(pane.widget(index)).path) is not None and folder in path.parents
        ]

    def dirty_tab_names_under(self, folder: Path) -> list[str]:
        """The (sorted, deduplicated) file names of any already-open tab anywhere under ``folder``
        that has unsaved edits -- used by :meth:`~in_reach.ide.main_window.MainWindow.
        vcs_switch_branch` (PROMPT.md: "it should be possible ... to change and switch
        versions/branches") to warn before a branch switch overwrites files on disk out from under
        an open, unsaved tab."""
        names = {
            pane._tab_state_for(pane.widget(index)).path.name
            for pane, index in self._open_tab_locations_under(folder)
            if _is_modified(pane.widget(index))
        }
        return sorted(names)

    def reload_open_tabs_under(self, folder: Path) -> None:
        """Re-reads every already-open tab anywhere under ``folder`` from disk in place -- run
        after a VCS branch switch (PROMPT.md) rewrites the project's own files on disk, so an
        already-open, already-clean tab reflects the newly checked-out branch instead of silently
        showing stale content until the user happens to reopen it."""
        for pane, index in self._open_tab_locations_under(folder):
            pane._reload_tab(index)

    def _new_pane(self) -> TabPane:
        pane = TabPane(self)
        # Switching tabs within a pane counts as "using" it -- see active_pane's own docstring.
        pane.currentChanged.connect(lambda _index, p=pane: self._mark_active(p))
        pane.cursor_info_changed.connect(self.cursor_info_changed.emit)
        return pane

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
            # document=widget.document(), not a separate setDocument() call after construction --
            # see editor.py's _PlainTextEditor.__init__ docstring for why a *second* setDocument()
            # on the same instance is itself the thing that used to crash here.
            duplicate: QWidget = TextEditorWidget(document=widget.document())
            duplicate.set_path(source_state.path)
            # A duplicate is its own QWidget, not sharing widget-level (as opposed to document-
            # level) state with the source -- read-only doesn't carry over on its own, so a split
            # view of a generated file would otherwise silently become editable.
            generated = widget.isReadOnly()
            duplicate.setReadOnly(generated)
            _connect_editor_signals(duplicate)
        elif isinstance(widget, MarkdownPreviewWidget):
            duplicate = MarkdownPreviewWidget(path=source_state.path)
            duplicate.setMarkdown(widget.toMarkdown())
        elif isinstance(widget, KanbanBoardView):
            # A second live view of the same board -- both redraw off the store's own change
            # notifications, so they stay in step without sharing anything else.
            duplicate = KanbanBoardView(widget.store, widget.board_id)
            new_index = target.addTab(duplicate, icons.icon("kanban", color=_SPLIT_ICON_COLOR), label)
            target._track_tab(new_index, duplicate, state=_TabState(path=None))
            return
        else:
            duplicate = self._new_welcome_tab()

        if generated:
            new_index = target.addTab(duplicate, icons.lock_icon(), label)
        else:
            new_index = target.addTab(duplicate, label)
        target._track_tab(new_index, duplicate, state=_TabState(path=source_state.path))

    def split_from(self, source: TabPane) -> None:
        """Horizontal split: adds a new pane-group beside ``source``'s own group, seeded with a
        duplicate of ``source``'s current tab. A no-op for a floating (popout-window) pane --
        see :meth:`move_tab_to_new_window`'s own docstring -- since a popout doesn't participate in
        this area's own splitter layout at all."""
        if source.group is None or self.split_count >= _MAX_H_SPLITS:
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

    def preview_split_from(self, source: TabPane) -> None:
        """The magnifying-glass icon's own split (PROMPT.md, Notes-as-Markdown: "editor should
        split to show live .md preview on the right hand side") -- a horizontal split like
        :meth:`split_from`, but seeded with a *live* :class:`~in_reach.ide.markdown_preview.
        MarkdownPreviewWidget` following ``source``'s current tab (see :meth:`MarkdownPreviewWidget.
        follow_live`) instead of a plain duplicate. A no-op if ``source``'s current tab isn't an
        editable Markdown one, or the split cap is already reached."""
        index = source.currentIndex()
        widget = source.widget(index) if index >= 0 else None
        path = source._tab_state_for(widget).path if widget is not None else None
        is_editable_markdown = (
            isinstance(widget, TextEditorWidget) and path is not None and path.suffix.lower() == ".md"
        )
        if not is_editable_markdown or source.group is None or self.split_count >= _MAX_H_SPLITS:
            return
        label = source.tabText(index)
        preview = MarkdownPreviewWidget(path=path)
        preview.follow_live(widget)

        new_group = self._new_group()
        new_pane = self._new_pane()
        new_index = new_pane.addTab(preview, f"Preview: {label}")
        new_pane._track_tab(new_index, preview, state=_TabState(path=path))
        new_group.add_pane(new_pane)
        self._add_group(new_group)

    def new_tab_in(self, pane: TabPane) -> None:
        """Adds a fresh "Untitled-N.txt" text-editor tab to ``pane`` -- called when a click lands
        on the tab bar's own empty space rather than any existing tab. The shared counter keeps
        labels unique across every pane rather than restarting per-pane."""
        label = f"Untitled-{self._next_tab_number}.txt"
        self._next_tab_number += 1
        editor = TextEditorWidget()
        _connect_editor_signals(editor)
        new_index = pane.addTab(editor, label)
        pane._track_tab(new_index, editor)
        pane.setCurrentIndex(new_index)

    def open_welcome_tab_in(self, pane: TabPane) -> None:
        """"Load Welcome Tab" (the File menu) -- switches to ``pane``'s own Welcome tab if it
        already has one open, else adds a fresh one, same "switch instead of duplicating" rule
        :meth:`TabPane.open_file` already follows for a real file."""
        for index in range(pane.count()):
            if isinstance(pane.widget(index), WelcomeTab):
                pane.setCurrentIndex(index)
                return
        welcome = self._new_welcome_tab()
        new_index = pane.addTab(welcome, "Welcome")
        pane._track_tab(new_index, welcome)
        pane.setCurrentIndex(new_index)

    def refresh_project_titles(self) -> None:
        """Re-reads every open editor tab's own ancestor-project title and refreshes its
        breadcrumb to match -- called after a project rename (PROMPT.md: "when a project name is
        changed ... the project title should change in the tabs and in the breadcrumb") so an
        already-open tab doesn't keep showing the old title until its file is reopened.

        Also re-``refresh()``es any open Welcome tab (PROMPT.md: "when a project is renamed, it
        needs to be renamed in recents ... and in the welcome window") -- its own Recent list
        reads the same on-disk title back via :func:`~in_reach.app.new_project.read_project_title`,
        but only when :meth:`~in_reach.ide.welcome.WelcomeTab.refresh` actually runs, which a
        rename elsewhere doesn't otherwise trigger."""
        for pane in self.panes:
            for index in range(pane.count()):
                widget = pane.widget(index)
                if isinstance(widget, TextEditorWidget):
                    widget.refresh_project_title()
                elif isinstance(widget, WelcomeTab):
                    widget.refresh()

    def find_pane(self, pane_id: int) -> TabPane | None:
        for pane in self.panes:
            if id(pane) == pane_id:
                return pane
        return None

    def on_pane_emptied(self, pane: TabPane) -> None:
        """Called after a tab is dragged or closed out of ``pane`` -- removes it (and its group, if
        that was the group's last pane) unless it's the very last pane in the whole area.

        The actual removal is deferred one event-loop tick (``QTimer.singleShot(0, ...)``) rather
        than done immediately, in :meth:`_remove_empty_pane`. This is reached synchronously from
        deep inside a tab's own close-button click handler (``_maybe_close`` -> ``_close_tab`` ->
        here), and reparenting/deleting a whole pane-group's widget tree from there reflows this
        area's own splitter *while that click is still being handled* -- confirmed (PROMPT.md: "if
        i have two tabs open (1 on welcome and one on any json) and i close the welcome, things
        crash") to be able to crash Qt's own native text-layout engine outright: an access
        violation inside a *sibling* pane's ``TextEditorWidget.resizeEvent``, caught via
        ``faulthandler``, from the resize that splitter reflow triggers landing mid-event-handling
        like that. Letting the click handler's own call stack unwind back to the event loop first --
        the same reason ``QWidget.deleteLater()`` defers destruction rather than doing it inline --
        avoids it.
        """
        if pane.count() != 0 or len(self.panes) <= 1:
            return
        QTimer.singleShot(0, lambda: self._remove_empty_pane(pane))

    def _remove_empty_pane(self, pane: TabPane) -> None:
        # Re-checked against whatever's true *now*, one event-loop tick after on_pane_emptied's own
        # check above -- e.g. a tab could have been dropped back into `pane` in the meantime, or
        # every other pane could have since closed too.
        if pane.count() != 0 or pane not in self.panes or len(self.panes) <= 1:
            return

        if pane.group is None:
            # A floating (popout-window) pane -- see move_tab_to_new_window's own docstring. Never
            # subject to the main splitter's group-removal bookkeeping below; this is the one place
            # a popout window is actually torn down, whether it emptied by its last tab closing or
            # by that tab being dragged out into another pane (see _PopoutWindow.closeEvent's own
            # docstring for why closing the window itself funnels through here too).
            self._floating_panes.remove(pane)
            window = self._popout_windows.pop(pane, None)
            if window is not None:
                window.force_close()
                window.deleteLater()
            return

        group = pane.group
        group.remove_pane(pane)
        if group.panes:
            group._equalize()
        else:
            self.groups.remove(group)
            self._splitter.removeWidget(group)
            group.setParent(None)
            group.deleteLater()
            self._equalize_groups()
        self._update_split_buttons()

    def move_tab_to_new_window(self, source: TabPane, index: int) -> "_PopoutWindow":
        """"Move to Window" (the tab context menu) -- PROMPT.md: "please also add a move to window
        option - this should move the tab to a popout window where other tabs can also be dragged
        to[; t]he top of the popout window should be called the gametype name".

        The new pane is a fully ordinary :class:`TabPane` sharing this same :class:`MainPanelArea`
        (registered in :attr:`_floating_panes` rather than any :class:`_PaneGroup`) -- so dragging a
        tab between it and any other pane, in this window or the main one, needs no special-casing
        at all: :class:`TabPane`'s own drag/drop only ever looks a source pane up by id via
        :meth:`find_pane`, which walks :attr:`panes` (already extended to include floating ones),
        indifferent to which top-level window either pane actually lives in -- Qt's own drag-and-
        drop already works across top-level windows in the same process for free. Shared documents
        (a split Markdown/text tab), the active-pane tracker, and every dirty-tab-by-path lookup
        used elsewhere all keep working the same way for the same reason.

        Split buttons are hidden on the new pane -- see :meth:`split_from`'s own docstring for why a
        floating pane can never actually split (there's no second slot in a popout window's own
        layout to split into).
        """
        label = source.tabText(index)
        icon = source.tabIcon(index)
        content = source.widget(index)
        state = source._tab_state.pop(content, _TabState())
        source.removeTab(index)

        new_pane = self._new_pane()
        new_pane.split_button.hide()
        new_pane.vsplit_button.hide()
        if icon is not None and not icon.isNull():
            new_index = new_pane.addTab(content, icon, label)
        else:
            new_index = new_pane.addTab(content, label)
        new_pane._track_tab(new_index, content, state=state)
        new_pane.setCurrentIndex(new_index)
        self._floating_panes.append(new_pane)

        title = self.project_title() if self.project_title is not None else "in-reach"
        window = _PopoutWindow(new_pane, title=title)
        self._popout_windows[new_pane] = window
        window.show()

        self.on_pane_emptied(source)
        return window
