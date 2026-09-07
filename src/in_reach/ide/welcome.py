"""The Welcome tab shown when the editor first opens -- modelled after VSCode's own Welcome page.
The right-hand side is deliberately left unfilled for now, per PROMPT.md.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from in_reach.ide import icons

_ICON_SIZE = 16


class WelcomeTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(32)

        left = QVBoxLayout()
        left.setSpacing(4)

        title = QLabel("In-Reach")
        title_font = title.font()
        title_font.setPointSize(title_font.pointSize() + 12)
        title_font.setBold(True)
        title.setFont(title_font)
        left.addWidget(title)

        subtitle = QLabel("Halo Reach Script Manager")
        subtitle_font = subtitle.font()
        subtitle_font.setPointSize(subtitle_font.pointSize() + 2)
        subtitle.setFont(subtitle_font)
        left.addWidget(subtitle)

        left.addSpacing(24)

        start_label = QLabel("Start")
        start_font = start_label.font()
        start_font.setBold(True)
        start_label.setFont(start_font)
        left.addWidget(start_label)

        left.addSpacing(4)

        # Stubbed for now, per PROMPT.md -- mirrors ActivityBar's settings_button no-op pattern.
        self.new_gametype_button = QPushButton(
            icons.icon("new_file", size=_ICON_SIZE), " New Gametype"
        )
        self.new_gametype_button.setFlat(True)
        self.new_gametype_button.setCursor(Qt.CursorShape.PointingHandCursor)
        left.addWidget(self.new_gametype_button, 0, Qt.AlignmentFlag.AlignLeft)

        left.addStretch(1)

        layout.addLayout(left, 1)
        layout.addWidget(QWidget(), 1)
