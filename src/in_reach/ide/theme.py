"""Named color themes, loaded from ``in_reach/ide/themes/themes.json``.

QPalette-based rather than a hand-rolled QSS stylesheet: PyQt6's native widgets already respect
QPalette roles (Window/Base/Text/Highlight/etc.) automatically, so a theme here is just a small
dict of hex colors mapped onto those roles. The Fusion style is forced whenever a theme is
applied -- native platform styles only partially honour a custom QPalette, which would make
switching themes look inconsistent depending on the user's own Windows theme.

All shipped themes live in one ``themes.json`` file (a top-level ``"themes"`` list) rather than
one file per theme -- each entry also carries an ``editable`` flag (always ``false`` for the three
shipped themes today) and a ``status_bar_color``, reserved/used respectively for a future 4th,
user-customizable theme slot. That customization UI isn't implemented yet -- see PROMPT.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QStyleFactory

THEMES_PATH = Path(__file__).resolve().parent / "themes" / "themes.json"
DEFAULT_THEME_NAME = "Light"
DEFAULT_STATUS_BAR_COLOR = "#007acc"

_PALETTE_ROLES = {
    "window": QPalette.ColorRole.Window,
    "window_text": QPalette.ColorRole.WindowText,
    "base": QPalette.ColorRole.Base,
    "alternate_base": QPalette.ColorRole.AlternateBase,
    "tooltip_base": QPalette.ColorRole.ToolTipBase,
    "tooltip_text": QPalette.ColorRole.ToolTipText,
    "text": QPalette.ColorRole.Text,
    "button": QPalette.ColorRole.Button,
    "button_text": QPalette.ColorRole.ButtonText,
    "bright_text": QPalette.ColorRole.BrightText,
    "link": QPalette.ColorRole.Link,
    "highlight": QPalette.ColorRole.Highlight,
    "highlighted_text": QPalette.ColorRole.HighlightedText,
    "mid": QPalette.ColorRole.Mid,
}


@dataclass
class Theme:
    name: str
    palette_colors: dict[str, str] = field(default_factory=dict)
    disabled_text: str | None = None
    status_bar_color: str = DEFAULT_STATUS_BAR_COLOR
    editable: bool = False

    def build_palette(self) -> QPalette:
        palette = QPalette()
        for key, color_hex in self.palette_colors.items():
            role = _PALETTE_ROLES.get(key)
            if role is not None:
                palette.setColor(role, QColor(color_hex))
        if self.disabled_text:
            disabled = QColor(self.disabled_text)
            for role in (
                QPalette.ColorRole.WindowText,
                QPalette.ColorRole.Text,
                QPalette.ColorRole.ButtonText,
            ):
                palette.setColor(QPalette.ColorGroup.Disabled, role, disabled)
        return palette


def _read_themes() -> list[dict]:
    try:
        data = json.loads(THEMES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    themes = data.get("themes") if isinstance(data, dict) else None
    return [entry for entry in themes if isinstance(entry, dict) and entry.get("name")] if themes else []


def list_themes() -> list[str]:
    """Every theme's display ``name`` (e.g. ``["Light", "Dark", "Whiley"]``), in file order."""
    return [entry["name"] for entry in _read_themes()]


def load_theme(name: str) -> Theme:
    for entry in _read_themes():
        if entry["name"] == name:
            return Theme(
                name=entry["name"],
                palette_colors=entry.get("palette") or {},
                disabled_text=entry.get("disabled_text"),
                status_bar_color=entry.get("status_bar_color", DEFAULT_STATUS_BAR_COLOR),
                editable=bool(entry.get("editable", False)),
            )
    raise ValueError(f"No such theme: {name!r} (available: {list_themes()})")


def apply_theme(app: QApplication, theme_name: str) -> Theme:
    """Applies the named theme app-wide and returns the loaded :class:`Theme`.

    Falls back to :data:`DEFAULT_THEME_NAME` for an unknown name rather than raising. Safe to call
    repeatedly (e.g. live-previewing a theme from the first-run dialog).
    """
    try:
        theme = load_theme(theme_name)
    except ValueError:
        theme = load_theme(DEFAULT_THEME_NAME)
    app.setStyle(QStyleFactory.create("Fusion"))
    app.setPalette(theme.build_palette())
    # A per-widget stylesheet rule that references the dynamic palette() QSS function is cached as
    # a "render rule" the first time a widget is polished -- a bare PaletteChange event doesn't
    # invalidate that cache, only a real unpolish/polish cycle does. Without this, an
    # already-constructed widget's background stays frozen at whichever theme was active when it
    # was first shown, which is exactly what the first-run dialog's live theme preview would hit.
    for widget in app.allWidgets():
        widget.style().unpolish(widget)
        widget.style().polish(widget)
    return theme
