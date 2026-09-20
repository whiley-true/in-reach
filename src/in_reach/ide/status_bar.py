"""VSCode-style bottom status bar. Just a themed strip whose background color comes from the
active theme's own ``status_bar_color`` rather than the palette, since a status bar's accent color
is a deliberate per-theme brand choice (blue for Light/Dark, red for Whiley), not a semantic
QPalette role.

Also the one widget that actually sits at the frameless window's true bottom edge, so it owns
bottom/corner edge-resize hover/press detection itself -- see :class:`~in_reach.ide.main_window.
_ResizableBody`'s own docstring for why that widget, which sits directly above this one, does not.

PROMPT.md: "present branch - last stamped - last saved should be showin in the left of the bottom
bar" -- :meth:`set_vcs_status`/:meth:`clear_vcs_status`'s own ``vcs_label``, originally left-aligned
(alongside a centered "<title> (<folder id>)" project label). A later pass (PROMPT.md: "so what we
have in the middle of the bottom bar, we now want in the quick access bar[;] please then move the
git information to the middle of the bottom bar") moved that project text into the top bar's own
Quick Access pill instead (see :meth:`~in_reach.ide.quick_access.QuickAccessBar.set_label`) and
recentered ``vcs_label`` into the slot it vacated, since nothing else shares the strip's left side
any more.

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
        # PROMPT.md: "please then move the git information to the middle of the bottom bar" --
        # clickable the same way cursor_label/spaces_label are, opening the Git panel rather than a
        # quick-pick. Hidden with no project open (see set_vcs_status), same convention as the
        # right-side segments. Two equal stretches keep it centered in the gap between the (now
        # empty) left side and the right-side cursor/spaces segments -- the same "center between
        # two stretches" trick as the top bar's own Quick Access pill -- in the slot the project
        # label used to occupy before it moved to that pill (see this module's own docstring).
        # The active build profile (see in_reach.app.script_preprocess), on the otherwise empty left
        # edge -- clickable to change it, hidden with no project open or nothing to choose between.
        self.profile_label = _ClickableLabel()
        self.profile_label.hide()
        layout.addWidget(self.profile_label)
        layout.addStretch(1)
        self.vcs_label = _ClickableLabel()
        self.vcs_label.hide()
        layout.addWidget(self.vcs_label)
        layout.addStretch(1)

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

    def set_vcs_status(
        self, branch: str, last_stamp: str | None, last_saved: str, *, on_click: Callable[[], None]
    ) -> None:
        """Shows/refreshes the centered "<branch> - <last stamped> - <last saved>" segment
        (PROMPT.md). ``last_stamp`` is already formatted (e.g. ``"v1.0"``) or ``None`` for "never
        stamped yet"; ``last_saved`` is already a relative/absolute time string -- this method just
        joins and displays them, leaving the actual formatting to the caller (mirroring
        ``set_cursor_info``'s own division of labor)."""
        stamped = last_stamp if last_stamp is not None else "not yet stamped"
        self.vcs_label.setText(f"{branch} - {stamped} - saved {last_saved}")
        self.vcs_label.set_on_click(on_click)
        self.vcs_label.show()

    def clear_vcs_status(self) -> None:
        """Hides the branch/stamp/saved segment -- no project open, or it has no history yet."""
        self.vcs_label.hide()

    def set_profile(self, name: str | None, *, on_click: Callable[[], None]) -> None:
        """Shows the left-edge build-profile segment: ``Profile: <name>``, or ``No profile`` when the
        project has profiles but none is chosen. Clicking it runs ``on_click`` (a quick-pick)."""
        self.profile_label.setText(f"Profile: {name}" if name else "No profile")
        self.profile_label.set_on_click(on_click)
        self.profile_label.show()

    def clear_profile(self) -> None:
        """Hides the build-profile segment -- no project open, or it has no profiles to pick from."""
        self.profile_label.hide()

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

    def clear_cursor_info(self) -> None:
        """Hides the Ln/Col/Spaces segments -- no ``.txt``/``.json`` tab is active."""
        self.cursor_label.hide()
        self.spaces_label.hide()

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
