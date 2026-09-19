"""Thin ``QFileDialog`` wrappers that force the dialog onto the same screen the IDE's own window
is currently on (PROMPT.md: "please make sure file explorers always open on the same screen as the
ide is running on").

Windows' own native common file dialog remembers its last-used screen position across invocations
(keyed to a per-dialog-type GUID in the registry), independent of which monitor the owning window
is actually on right now -- a native dialog opened once on a secondary monitor keeps reopening
there even after the app itself has since moved to the primary one, or vice versa. Passing a parent
widget (every call site here already did) only fixes *modality*, not that remembered position.
Forcing Qt's own non-native dialog and explicitly centering it on the parent's current screen
sidesteps the OS's remembered state entirely -- the only reliable fix without also reaching into
the registry ourselves.

Every caller already goes through its own test-seam method (``MainWindow.ask_open_folder``,
``MainWindow.ask_export_path``, ``TabPane._ask_save_path``, etc.) rather than touching
``QFileDialog`` directly, so switching what's inside those seams doesn't disturb any existing test.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QFileDialog, QWidget


def _center_on_parent_screen(dialog: QFileDialog, parent: QWidget | None) -> None:
    screen = parent.screen() if parent is not None else None
    if screen is None:
        return
    geometry = dialog.frameGeometry()
    geometry.moveCenter(screen.availableGeometry().center())
    dialog.move(geometry.topLeft())


def get_existing_directory(parent: QWidget | None, caption: str, directory: str = "") -> str:
    """Same signature/return as ``QFileDialog.getExistingDirectory`` -- ``""`` if cancelled."""
    dialog = QFileDialog(parent, caption, directory)
    dialog.setFileMode(QFileDialog.FileMode.Directory)
    dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    _center_on_parent_screen(dialog, parent)
    if dialog.exec() != QFileDialog.DialogCode.Accepted:
        return ""
    selected = dialog.selectedFiles()
    return selected[0] if selected else ""


def get_save_file_name(
    parent: QWidget | None, caption: str, directory: str = "", filter: str = ""  # noqa: A002 -- matches Qt's own param name
) -> tuple[str, str]:
    """Same signature/return as ``QFileDialog.getSaveFileName`` -- ``("", "")`` if cancelled."""
    dialog = QFileDialog(parent, caption, directory, filter)
    dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    _center_on_parent_screen(dialog, parent)
    if dialog.exec() != QFileDialog.DialogCode.Accepted:
        return "", ""
    selected = dialog.selectedFiles()
    return (selected[0] if selected else "", dialog.selectedNameFilter())


def get_open_file_name(
    parent: QWidget | None, caption: str, directory: str = "", filter: str = ""  # noqa: A002
) -> tuple[str, str]:
    """Same signature/return as ``QFileDialog.getOpenFileName`` -- ``("", "")`` if cancelled."""
    dialog = QFileDialog(parent, caption, directory, filter)
    dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    _center_on_parent_screen(dialog, parent)
    if dialog.exec() != QFileDialog.DialogCode.Accepted:
        return "", ""
    selected = dialog.selectedFiles()
    return (selected[0] if selected else "", dialog.selectedNameFilter())
