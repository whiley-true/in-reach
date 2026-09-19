"""Primary-sidebar view behind the activity bar's map icon (PROMPT.md: "above search please add a map
icon for 'Map Files' (stubbed for now)" -- and, later, "under maps section, please add url slugs for
Map Variants, Hopper Variants and User Maps, please also add a button for In-Reach maps ... it
should point to .in-reach maps").

Lists where each map-variant folder actually lives as a clickable, link-styled "slug" -- the
resolved path itself, elided down the middle when the sidebar's too narrow for all of it -- that
opens the folder in the OS file explorer, plus an "Open In-Reach Maps" button for in-reach's own
maps folder. Like the Dashboard's Quick Launch buttons, this panel only *reports* a click (see
:attr:`MapsPanel.open_folder_requested`); :class:`~in_reach.ide.main_window.MainWindow` owns
resolving and opening the folder, and pushes the current paths in via :meth:`MapsPanel.set_paths`.
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from in_reach.app import system_verify

_UNRESOLVED_TEXT = "Not set -- run Verify System Settings"

#: A link-styled, borderless, left-aligned button -- reads as a URL slug rather than a push button.
_SLUG_STYLE = (
    "QPushButton { border: none; background: transparent; color: palette(link);"
    " text-decoration: underline; text-align: left; padding: 0px; }"
    "QPushButton:disabled { color: palette(mid); text-decoration: none; }"
)

_BUTTON_STYLE = (
    "QToolButton { background-color: palette(button); border: 1px solid palette(mid);"
    " border-radius: 4px; padding: 4px 10px; }"
    "QToolButton:hover { background-color: palette(highlight); color: palette(highlighted-text); }"
    "QToolButton:pressed { background-color: palette(mid); }"
)

#: (heading, system_verify env key) for each slug row -- PROMPT.md's own labels, verbatim.
SLUGS: tuple[tuple[str, str], ...] = (
    ("Map Variants", system_verify.STANDARD_MAP_VARIANTS_KEY),
    ("Hopper Variants", system_verify.HOPPER_MAP_VARIANTS_KEY),
    ("User Maps", system_verify.PERSONAL_MAPS_KEY),
)


class _SlugButton(QPushButton):
    """A link-styled button whose text is a filesystem path, middle-elided to fit its own width
    (the full path stays in the tooltip). A :class:`QPushButton` rather than a tool button --
    ``text-align: left`` is only honoured by the former."""

    def __init__(self) -> None:
        super().__init__()
        self._full_text = ""
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setStyleSheet(_SLUG_STYLE)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    @property
    def full_text(self) -> str:
        return self._full_text

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self.setToolTip(text)
        self._elide()

    def _elide(self) -> None:
        width = max(0, self.width() - 4)
        elided = self.fontMetrics().elidedText(self._full_text, Qt.TextElideMode.ElideMiddle, width)
        self.setText(elided if width else self._full_text)

    def resizeEvent(self, event) -> None:  # noqa: ANN001 -- QResizeEvent
        super().resizeEvent(event)
        self._elide()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self._elide()


class MapsPanel(QWidget):
    #: Emitted with the :mod:`in_reach.app.system_verify` env key of whichever folder was clicked
    #: -- the same signal shape (and the same MainWindow slot) as the Dashboard's own Quick Launch
    #: "Built-in" buttons, see :attr:`~in_reach.ide.explorer.ExplorerPanel.
    #: open_builtin_folder_requested`.
    open_folder_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self.slug_buttons: dict[str, _SlugButton] = {}
        for heading, key in SLUGS:
            label = QLabel(heading)
            label.setStyleSheet("QLabel { font-style: italic; }")
            layout.addWidget(label)
            slug = _SlugButton()
            slug.clicked.connect(lambda _checked=False, k=key: self.open_folder_requested.emit(k))
            layout.addWidget(slug)
            self.slug_buttons[key] = slug
        layout.addSpacing(8)

        # PROMPT.md: "please also add a button for In-Reach maps" -- in-reach's own folder, so
        # (unlike the slugs above) always openable: MainWindow creates it on demand.
        self.inreach_maps_button = QToolButton()
        self.inreach_maps_button.setText("Open In-Reach Maps")
        self.inreach_maps_button.setToolTip("Open in-reach's own maps folder (.in-reach/maps)")
        self.inreach_maps_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.inreach_maps_button.setAutoRaise(False)
        self.inreach_maps_button.setStyleSheet(_BUTTON_STYLE)
        self.inreach_maps_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.inreach_maps_button.clicked.connect(
            lambda: self.open_folder_requested.emit(system_verify.INREACH_MAPS_KEY)
        )
        layout.addWidget(self.inreach_maps_button)
        layout.addStretch(1)

        self.set_paths({})

    def set_paths(self, paths: dict[str, str]) -> None:
        """Shows each slug's current resolved path (keyed by env key) -- a key missing/blank is
        shown as unresolved and its slug disabled, since there's nothing to open yet."""
        for key, slug in self.slug_buttons.items():
            value = paths.get(key, "")
            slug.set_full_text(value or _UNRESOLVED_TEXT)
            slug.setEnabled(bool(value))
