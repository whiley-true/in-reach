"""The popout window behind the Git panel's own "Stamp Release" button (PROMPT.md: "stamping a
release presently says 'Commit Message' instead of 'Release Message' ... also we want to add the
functionality for version numbers using major, minor, patch with stamped releases ... stamping a
version should reveal spin buttons centered at the present number allowing the user to 'bump'
either major minor or patch").

A plain modal dialog: a "Release Message" field (the field :mod:`in_reach.ide.git_panel` used to
label "Commit Message" for this same action) plus three spin boxes -- Major/Minor/Patch -- each
seeded with the project's current version number's own component, so "bumping" one is just clicking
its spin box's up arrow once. Nothing here decides *whether* stamping should be allowed (see
:meth:`in_reach.ide.git_panel.GitPanel.set_stamp_enabled`'s own docstring for the "can't stamp an
uncompiled gametype" gate, and :func:`in_reach.app.vcs.version_already_stamped` for the "same
version already stamped" warning) -- this dialog only ever collects a message and a version number.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

_MAX_VERSION_COMPONENT = 9999


class StampReleaseDialog(QDialog):
    """Collects a release message plus a major/minor/patch version number, seeded from the
    project's current version."""

    def __init__(
        self, major: int, minor: int, patch: int, parent: QWidget | None = None, *, message: str = ""
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Stamp Release")
        self.setModal(True)

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.message_edit = QLineEdit()
        self.message_edit.setPlaceholderText("Release message")
        # PROMPT.md: "if a user aborts the stamp due to not re-stamping the same version, the
        # warning should close and they should be back at their release dialog/window" -- re-opening
        # this dialog after declining that warning (see GitPanel._on_stamp_clicked's own loop) seeds
        # it with whatever the user had already typed, rather than a blank field, so they don't have
        # to retype the message just to bump the version and try again.
        self.message_edit.setText(message)
        form.addRow("Release Message:", self.message_edit)
        layout.addLayout(form)

        version_row = QHBoxLayout()
        self.major_spin = self._version_spin(major)
        self.minor_spin = self._version_spin(minor)
        self.patch_spin = self._version_spin(patch)
        for label_text, spin in (
            ("Major", self.major_spin),
            ("Minor", self.minor_spin),
            ("Patch", self.patch_spin),
        ):
            column = QVBoxLayout()
            label = QLabel(label_text)
            label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            column.addWidget(label)
            column.addWidget(spin)
            version_row.addLayout(column)
        layout.addLayout(version_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.message_edit.setFocus()

    def _version_spin(self, value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(0, _MAX_VERSION_COMPONENT)
        spin.setValue(value)  # "spin buttons centered at the present number"
        spin.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        return spin

    def message(self) -> str:
        return self.message_edit.text().strip()

    def version(self) -> str:
        return f"{self.major_spin.value()}.{self.minor_spin.value()}.{self.patch_spin.value()}"
