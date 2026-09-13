"""The Quick Access Bar: a VSCode-style pill centered in the top bar.

``Ctrl+P`` opens it as a file-name search (:meth:`QuickAccessBar.open_search`) across the active
project's own files (see :mod:`in_reach.app.quick_open`); ``Ctrl+Shift+P`` opens it as a
``>``-prefixed command palette (:meth:`QuickAccessBar.open_command_palette`); typing ``>`` as the
very first character of an open search converts it into the palette live. Two more entry points
back the bottom status bar's own clickable segments: :meth:`QuickAccessBar.open_goto_line` (Ln/Col)
and :meth:`QuickAccessBar.open_action_list` (Spaces' fixed 4-item indentation menu).

A :class:`Command` can either run an ``action`` (a leaf) or hold ``children`` -- selecting one of
those re-populates the list with them instead of closing (so "Set Theme" -> Enter shows
Light/Dark/Whiley), matching the user's own "they press enter to see the possible options" request.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QHideEvent, QKeyEvent
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from in_reach.app import quick_open

_COMMAND_PREFIX = ">"
_OVERLAY_WIDTH = 480
_OVERLAY_MAX_RESULTS = 200
#: The always-visible pill defaults to 12x its own natural (text+padding) width -- originally 3x,
#: widened another 4x (PROMPT.md: "make the search bar *4 wider, it looks way too small") -- so it
#: reads as an actual search bar rather than a small button. The pill's *own* sizeHint() still
#: drives this (rather than a hardcoded pixel count), so it scales with whatever font the label is
#: rendered in.
_PILL_WIDTH_MULTIPLIER = 12
_PILL_STYLE = (
    "QPushButton { background-color: palette(base); color: palette(placeholder-text);"
    " border: 1px solid palette(mid); border-radius: 4px; padding: 2px 12px; text-align: left; }"
    "QPushButton:hover { background-color: palette(alternate-base); }"
)
_OVERLAY_STYLE = (
    "QWidget#quickAccessOverlay { background-color: palette(window); border: 1px solid palette(mid);"
    " border-radius: 6px; }"
)
_HEADING_STYLE = "color: palette(placeholder-text); padding: 2px 4px;"


@dataclass
class Command:
    label: str
    action: Callable[[], None] | None = None
    children: "list[Command] | None" = None
    #: Displayed in a dimmer color to the right of the label -- e.g. the currently active theme.
    detail: str = ""


@dataclass
class _SearchResult:
    label: str
    path: Path | None = None
    command: Command | None = None


class _QuickAccessLineEdit(QLineEdit):
    """Forwards Up/Down/Enter/Escape to the owning overlay's list -- the line edit keeps keyboard
    focus the whole time (VSCode's own quick-pick behavior), so arrow-key list navigation has to be
    relayed here rather than living on the (unfocused) list widget itself."""

    def __init__(self, overlay: "QuickAccessOverlay") -> None:
        super().__init__(overlay)
        self._overlay = overlay

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Down:
            self._overlay.move_selection(1)
            return
        if key == Qt.Key.Key_Up:
            self._overlay.move_selection(-1)
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._overlay.activate_current()
            return
        if key == Qt.Key.Key_Escape:
            self._overlay.hide()
            return
        super().keyPressEvent(event)


class QuickAccessOverlay(QWidget):
    """The popup itself -- one line edit plus one result list, reused across every mode.

    PROMPT.md: "when clicking on the search bar behaviour is unexpected, we are seeing a drop down
    is spawned containing a text entry box (underneath the search box) -- we want them to be able
    to type in the search box", matching a single VSCode-style box-with-a-list-below-it rather than
    a static pill sitting on top of a second, separate input. :class:`QuickAccessBar` hides its own
    always-visible pill for as long as this overlay is open (see :attr:`on_hidden`, fired from
    :meth:`hideEvent`) and positions this overlay exactly where that pill was, so only ever one box
    is visible at a time -- this one, playing both roles.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("quickAccessOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(_OVERLAY_STYLE)
        self.setFixedWidth(_OVERLAY_WIDTH)
        #: Called (if set) whenever this overlay is hidden, by any means -- Escape, picking a
        #: result, or Qt's own Popup auto-close on losing focus -- so the pill it stood in for can
        #: reappear. See :meth:`hideEvent`.
        self.on_hidden: Callable[[], None] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.heading_label = QLabel()
        self.heading_label.setStyleSheet(_HEADING_STYLE)
        self.heading_label.hide()
        layout.addWidget(self.heading_label)

        self.line_edit = _QuickAccessLineEdit(self)
        layout.addWidget(self.line_edit)

        self.list_widget = QListWidget()
        self.list_widget.itemActivated.connect(lambda _item: self.activate_current())
        self.list_widget.itemClicked.connect(lambda _item: self.activate_current())
        layout.addWidget(self.list_widget)

        self.line_edit.textChanged.connect(self._on_text_changed)

        self._mode = ""
        self._results: list[_SearchResult] = []
        #: Command breadcrumb -- non-empty once a parent command (e.g. "Set Theme") has been
        #: entered, so a leaf's own filtered view can still be reached by label alone.
        self._command_stack: list[Command] = []
        #: Cached so a search opened via Ctrl+P still has commands to show if the user types ">"
        #: (PROMPT.md: typing ">" into an open search bar transforms it into the command palette).
        self._root_commands: list[Command] = []
        self._all_files: list[Path] = []
        self._project_folder: Path | None = None
        self._open_file: Callable[[Path], None] | None = None
        self._on_goto_line: Callable[[int], None] | None = None
        self._max_line = 0

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        if self.on_hidden is not None:
            self.on_hidden()

    # -- opening ----------------------------------------------------------------------------------

    def open_search(
        self,
        project_folder: Path | None,
        files: list[Path],
        open_file: Callable[[Path], None],
        root_commands: list[Command] | None = None,
    ) -> None:
        self._mode = "search"
        self._project_folder = project_folder
        self._all_files = files
        self._open_file = open_file
        self._set_root_commands(root_commands or [])
        self.heading_label.hide()
        self.list_widget.show()
        self.line_edit.setPlaceholderText("Search files by name")
        self._set_text_silently("")
        self._refresh_search()
        self._show()

    def open_command_palette(self, root_commands: list[Command]) -> None:
        self._mode = "command"
        self._command_stack = []
        self.heading_label.hide()
        self.list_widget.show()
        self.line_edit.setPlaceholderText("")
        self._set_root_commands(root_commands)
        self._set_text_silently(_COMMAND_PREFIX)
        self._refresh_commands()
        self._show()

    def open_goto_line(self, max_line: int, on_line_changed: Callable[[int], None]) -> None:
        self._mode = "goto_line"
        self._max_line = max_line
        self._on_goto_line = on_line_changed
        self.heading_label.hide()
        self.list_widget.hide()
        self.line_edit.setPlaceholderText(f"Type a line number to go to (from 1 to {max_line})")
        self._set_text_silently("")
        self._show()

    def open_action_list(self, commands: list[Command], heading: str = "Select Action") -> None:
        self._mode = "action_list"
        self._command_stack = []
        self.heading_label.setText(heading)
        self.heading_label.show()
        self.list_widget.show()
        self.line_edit.setPlaceholderText(heading)
        self._set_root_commands(commands)
        self._set_text_silently("")
        self._refresh_commands()
        self._show()

    def _set_root_commands(self, commands: list[Command]) -> None:
        self._root_commands = commands

    def _show(self) -> None:
        # No selection reset here -- each open_*() already ran its own _refresh_*() just above,
        # which (via _populate_list) selects the first/closest match already, matching the user's
        # own "as they start typing the closest match shows" expectation for Enter-to-pick.
        self.line_edit.setFocus()
        self.show()

    def _set_text_silently(self, text: str) -> None:
        self.line_edit.blockSignals(True)
        self.line_edit.setText(text)
        self.line_edit.blockSignals(False)

    # -- filtering --------------------------------------------------------------------------------

    def _on_text_changed(self, text: str) -> None:
        if self._mode == "search" and text.startswith(_COMMAND_PREFIX):
            # PROMPT.md: typing ">" into an open search bar transforms it into the command palette.
            self._mode = "command"
            self._command_stack = []
            self.line_edit.setPlaceholderText("")
        if self._mode == "search":
            self._refresh_search()
        elif self._mode in ("command", "action_list"):
            self._refresh_commands()
        elif self._mode == "goto_line":
            self._apply_goto_line(text)

    def _refresh_search(self) -> None:
        query = self.line_edit.text()
        matches = quick_open.filter_files(self._all_files, query, root=self._project_folder or Path("."))
        self._results = [
            _SearchResult(label=str(path.relative_to(self._project_folder or path.parent)), path=path)
            for path in matches[:_OVERLAY_MAX_RESULTS]
        ]
        self._populate_list()

    def _current_command_level(self) -> list[Command]:
        return self._command_stack[-1].children if self._command_stack else self._root_commands

    def _refresh_commands(self) -> None:
        text = self.line_edit.text()
        query = text[1:] if text.startswith(_COMMAND_PREFIX) else text
        level = self._current_command_level() or []
        needle = query.strip().lower()
        matched = [c for c in level if needle in c.label.lower()] if needle else list(level)
        self._results = [_SearchResult(label=cmd.label, command=cmd) for cmd in matched]
        self._populate_list()

    def _populate_list(self) -> None:
        self.list_widget.clear()
        for result in self._results:
            text = result.label
            if result.command is not None and result.command.detail:
                text = f"{text}    {result.command.detail}"
            self.list_widget.addItem(QListWidgetItem(text))
        if self._results:
            self.list_widget.setCurrentRow(0)

    def _apply_goto_line(self, text: str) -> None:
        text = text.strip()
        if not text.isdigit():
            return
        line = int(text)
        if 1 <= line <= self._max_line and self._on_goto_line is not None:
            self._on_goto_line(line)

    # -- selection/activation -----------------------------------------------------------------------

    def move_selection(self, delta: int) -> None:
        count = self.list_widget.count()
        if count == 0:
            return
        row = self.list_widget.currentRow()
        row = (row + delta) % count if row != -1 else 0
        self.list_widget.setCurrentRow(row)

    def activate_current(self) -> None:
        row = self.list_widget.currentRow()
        if self._mode == "goto_line":
            self.hide()
            return
        if row < 0 or row >= len(self._results):
            return
        result = self._results[row]
        if result.path is not None and self._open_file is not None:
            self._open_file(result.path)
            self.hide()
            return
        if result.command is not None:
            self._activate_command(result.command)

    def _activate_command(self, command: Command) -> None:
        if command.children:
            self._command_stack.append(command)
            self._set_text_silently(_COMMAND_PREFIX if self._mode == "command" else "")
            self._refresh_commands()
            return
        if command.action is not None:
            command.action()
        self.hide()


class QuickAccessBar(QWidget):
    """The always-visible top-bar pill -- click (or ``Ctrl+P``) opens the overlay in search mode."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        get_project_folder: Callable[[], Path | None],
        open_file: Callable[[Path], None],
        build_root_commands: Callable[[], list[Command]],
        label: str = "Search",
    ) -> None:
        super().__init__(parent)
        self._get_project_folder = get_project_folder
        self._open_file = open_file
        self._build_root_commands = build_root_commands

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # PROMPT.md: "rename the search bar text to be the name of the parent folder where
        # in-reach has been installed" -- the caller passes ``root_dir.name`` (see
        # ``MainWindow.root_dir``'s own docstring: the repo root the ``.in-reach`` project folder
        # lives under), so the pill reads as "which workspace is this?" rather than a generic verb.
        self.button = QPushButton(label)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.setStyleSheet(_PILL_STYLE)
        self.button.clicked.connect(self.open_search)
        self.button.setFixedWidth(self.button.sizeHint().width() * _PILL_WIDTH_MULTIPLIER)
        layout.addWidget(self.button)

        self.overlay = QuickAccessOverlay(self)
        self.overlay.on_hidden = self.button.show

    def _position_overlay(self) -> None:
        """Hides the pill and drops the overlay in exactly the screen space it just vacated --
        PROMPT.md: only ever one box should be visible/typable at a time (see
        :class:`QuickAccessOverlay`'s own docstring), rather than the overlay reappearing as a
        second box below the still-visible pill. Widened to at least the pill's own width so the
        box-plus-list-below never renders narrower than the bar it replaced."""
        self.button.hide()
        self.overlay.setFixedWidth(max(_OVERLAY_WIDTH, self.width()))
        top_left = self.mapToGlobal(self.rect().topLeft())
        x = top_left.x() - (self.overlay.width() - self.width()) // 2
        self.overlay.move(x, top_left.y())

    def open_search(self) -> None:
        folder = self._get_project_folder()
        files = quick_open.list_project_files(folder) if folder is not None else []
        self.overlay.open_search(folder, files, self._open_file, self._build_root_commands())
        self._position_overlay()

    def open_command_palette(self) -> None:
        self.overlay.open_command_palette(self._build_root_commands())
        self._position_overlay()

    def open_goto_line(self, max_line: int, on_line_changed: Callable[[int], None]) -> None:
        self.overlay.open_goto_line(max_line, on_line_changed)
        self._position_overlay()

    def open_action_list(self, commands: list[Command], heading: str = "Select Action") -> None:
        self.overlay.open_action_list(commands, heading)
        self._position_overlay()
