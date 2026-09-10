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
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

from in_reach.ide.window_resize import cursor_for_edges, resize_edges

_HEIGHT = 22


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
        self._project_label = QLabel()
        self._project_label.setStyleSheet("color: #ffffff;")
        layout.addWidget(self._project_label, 1, Qt.AlignmentFlag.AlignCenter)

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
