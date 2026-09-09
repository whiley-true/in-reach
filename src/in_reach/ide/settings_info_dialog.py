"""The "What is this?" popout behind the Welcome tab's Verify System Settings quadrant.

A plain explainer, not a control -- unlike :class:`~in_reach.ide.verify_dialog.VerifyDialog`, this
never reads or writes the ``.env``. It only exists because the checklist itself is asking for
things (a Tesseract install, half a dozen folder paths, a Steam account) whose purpose isn't
obvious from a bare label like "Halo Reach Hot Reload" -- this is where that gets explained.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout, QWidget

_BODY_TEXT = (
    "in-reach automates parts of Halo: MCC that have no other way in -- Reach exposes no API of "
    "its own, so a few things about this machine need to be known up front:\n\n"
    "Tesseract OCR is what reads Halo: MCC's own in-game menus from the screen. Since there's no "
    "API to ask MCC what's on screen or to drive its menus directly, in-reach reads them the same "
    "way a person would -- by looking -- and OCR is how it turns that screenshot back into text it "
    "can act on.\n\n"
    "The system locations (Steam, the Halo: MCC and Halo: Reach installs, and the standard/hopper "
    "game and map variant folders) are this machine's own install -- shared by every account that "
    "plays Reach on it, and needed to find the game's own official content.\n\n"
    "The user locations (the hot reload folder, your personal game and map variant folders, and "
    "your Steam account) are specific to you -- Reach saves what you create under your own Windows "
    "and Steam profile, so in-reach needs to know which profile is yours to find it."
)


class SettingsInfoDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("What is this?")
        self.setModal(True)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        label = QLabel(_BODY_TEXT)
        label.setWordWrap(True)
        layout.addWidget(label)

        close_button = QPushButton("Close")
        close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignRight)
