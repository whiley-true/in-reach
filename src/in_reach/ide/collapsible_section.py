"""A VSCode-style sidebar section header: an arrow + title, click to toggle, above a divider line
and a body widget that hides/shows with it. Originally built for the Dashboard's own Stats/Quick
Launch/Settings boxes (see :mod:`in_reach.ide.explorer`'s own history), factored out here once the
Git panel needed the exact same treatment (PROMPT.md: "please add section headings to the vcs sub
panel to make it clearer") -- no behavior change for either caller, just a shared home so the two
don't duplicate this widget.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QFrame, QSizePolicy, QToolButton, QVBoxLayout, QWidget

#: PROMPT.md: "please remove the bubble outline" (Dashboard boxes) -- a plain, borderless, bold
#: toggle button reads as a section header without needing a bordered frame around it.
SECTION_HEADER_STYLE = "QToolButton { border: none; background-color: transparent; font-weight: bold; }"


class CollapsibleSection(QWidget):
    """A header (an arrow + title, click to toggle) above a divider line and a body widget that
    hides/shows with it -- VS Code's own sidebar section headers."""

    def __init__(self, title: str, body: QWidget, *, collapsed: bool = True) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._toggle = QToolButton()
        self._toggle.setText(title)
        self._toggle.setCheckable(True)
        self._toggle.setChecked(not collapsed)
        self._toggle.setArrowType(Qt.ArrowType.DownArrow if not collapsed else Qt.ArrowType.RightArrow)
        self._toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle.setAutoRaise(True)
        self._toggle.setStyleSheet(SECTION_HEADER_STYLE)
        self._toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._toggle.toggled.connect(self._on_toggled)
        layout.addWidget(self._toggle)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFrameShadow(QFrame.Shadow.Plain)
        layout.addWidget(divider)

        self.body = body
        self.body.setVisible(not collapsed)
        layout.addWidget(self.body, 1)

    def _on_toggled(self, checked: bool) -> None:
        self._toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        self.body.setVisible(checked)

    def set_title(self, title: str) -> None:
        """Updates the header's own text in place -- e.g. to show a live count alongside the
        section name (VSCode's own "Changes (3)"-style section headers)."""
        self._toggle.setText(title)

    def set_header_font(self, font: QFont) -> None:
        """Overrides the header's own font -- e.g. to size it independently of :attr:`body`'s
        inherited one (see e.g. ``ExplorerPanel.refresh_font_scale``)."""
        self._toggle.setFont(font)

    @property
    def expanded(self) -> bool:
        return self._toggle.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        self._toggle.setChecked(expanded)
