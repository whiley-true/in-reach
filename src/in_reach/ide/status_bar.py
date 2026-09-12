"""VSCode-style bottom status bar. Just a themed strip whose background color comes from the
active theme's own ``status_bar_color`` rather than the palette, since a status bar's accent color
is a deliberate per-theme brand choice (blue for Light/Dark, red for Whiley), not a semantic
QPalette role.

Also the one widget that actually sits at the frameless window's true bottom edge, so it owns
bottom/corner edge-resize hover/press detection itself -- see :class:`~in_reach.ide.main_window.
_ResizableBody`'s own docstring for why that widget, which sits directly above this one, does not.

PROMPT.md: "please remove the dir location string (under the tabs section) and move that
information into the bottom bar (in the centre): it should read test (uuid)" -- the Dashboard's
own project-tabs subheading used to show the active project's folder id there; now it's this bar's
:meth:`set_project_label`, centered rather than left-aligned since nothing else shares the strip.

PROMPT.md (Quick Access Bar work): bottom-right "Ln X, Col Y (N selected)"/"Spaces: N" (or
"Tabs: N", whichever indent style is actually live -- PROMPT.md: "spaces [segment] should
represent what is live in the document at present") segments, shown only while a ``.txt``/
``.json`` tab is active (see ``bottom_bar_example.png``) -- see :meth:`set_cursor_info`/
:meth:`clear_cursor_info`. Each is a plain clickable label wired to a caller-supplied callback
rather than a signal -- one fewer layer for something this local, same "kept as its own method
purely as a test seam" convention used throughout this bar/``main_window.py``.
"""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

from in_reach.app import indent_settings
from in_reach.ide.window_resize import cursor_for_edges, resize_edges

_HEIGHT = 22


class _ClickableLabel(QLabel):
    """A status-bar segment that runs a callback on left-click -- VSCode's own Ln/Col and
    indentation status items both behave this way (open a quick-pick), not a real button."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._on_click: Callable[[], None] | None = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("color: #ffffff; padding: 0px 6px;")

    def set_on_click(self, callback: Callable[[], None] | None) -> None:
        self._on_click = callback

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._on_click is not None:
            self._on_click()
            return
        super().mousePressEvent(event)


class StatusBar(QWidget):
    def __init__(self, window: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window = window
        self.setFixedHeight(_HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("statusBar")
        self.setMouseTracking(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # A fixed-width spacer matching the right-side segments keeps the centered project label
        # actually centered on the whole bar rather than drifting left once those segments show.
        self._left_spacer = QWidget()
        layout.addWidget(self._left_spacer)
        self._project_label = QLabel()
        self._project_label.setStyleSheet("color: #ffffff;")
        layout.addWidget(self._project_label, 1, Qt.AlignmentFlag.AlignCenter)

        self.cursor_label = _ClickableLabel()
        self.cursor_label.hide()
        layout.addWidget(self.cursor_label)
        self.spaces_label = _ClickableLabel()
        self.spaces_label.hide()
        layout.addWidget(self.spaces_label)

    def set_color(self, color_hex: str) -> None:
        # Scoped to #statusBar, not a bare declaration -- see style.TOOLTIP_STYLE's own docstring
        # for why a bare one would risk quietly breaking any tooltip shown by something inside
        # this bar (nothing currently sets one here, but a bare rule is a landmine for the next
        # thing that does).
        self.setStyleSheet(f"QWidget#statusBar {{ background-color: {color_hex}; }}")

    def set_project_label(self, text: str) -> None:
        """Sets the centered "<title> (<folder id>)" text (PROMPT.md), or clears it for ``""``
        once no project is open."""
        self._project_label.setText(text)

    def set_cursor_info(
        self,
        line: int,
        col: int,
        selected: int,
        indent_style: str,
        indent_width: int,
        *,
        on_cursor_click: Callable[[], None],
        on_spaces_click: Callable[[], None],
    ) -> None:
        """Shows/refreshes the bottom-right "Ln X, Col Y (N selected)" and "Spaces: N"/"Tabs: N"
        segments -- ``indent_style`` picks which of those two labels is shown, so this always
        reflects whichever indent style is actually live for the document right now, rather than
        always reading "Spaces" even while Tabs is the active style."""
        text = f"Ln {line}, Col {col}"
        if selected:
            text += f" ({selected} selected)"
        self.cursor_label.setText(text)
        self.cursor_label.set_on_click(on_cursor_click)
        self.cursor_label.show()

        label = "Tabs" if indent_style == indent_settings.STYLE_TABS else "Spaces"
        self.spaces_label.setText(f"{label}: {indent_width}")
        self.spaces_label.set_on_click(on_spaces_click)
        self.spaces_label.show()
        self._left_spacer.setFixedWidth(self.cursor_label.sizeHint().width() + self.spaces_label.sizeHint().width())

    def clear_cursor_info(self) -> None:
        """Hides the Ln/Col/Spaces segments -- no ``.txt``/``.json`` tab is active."""
        self.cursor_label.hide()
        self.spaces_label.hide()
        self._left_spacer.setFixedWidth(0)

    def _edges_at(self, pos) -> Qt.Edge:  # noqa: ANN001 -- QPoint
        if self._window.isMaximized():
            return Qt.Edge(0)
        return resize_edges(pos, self.width(), self.height(), top=False, bottom=True)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            edges = self._edges_at(event.position().toPoint())
            window_handle = self._window.windowHandle()
            if edges and window_handle is not None:
                window_handle.startSystemResize(edges)
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not bool(event.buttons() & Qt.MouseButton.LeftButton):
            edges = self._edges_at(event.position().toPoint())
            self.setCursor(cursor_for_edges(edges)) if edges else self.unsetCursor()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: ANN001 -- QEvent
        self.unsetCursor()
        super().leaveEvent(event)
