"""Named color themes, loaded from ``in_reach/ide/themes/*.yml``.

QPalette-based rather than a hand-rolled QSS stylesheet: PyQt6's native widgets already respect
QPalette roles (Window/Base/Text/Highlight/etc.) automatically, so a theme here is just a small
dict of hex colors mapped onto those roles. The Fusion style is forced whenever a theme is
applied -- native platform styles only partially honour a custom QPalette, which would make
switching themes look inconsistent depending on the user's own Windows theme.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QStyleFactory

THEMES_DIR = Path(__file__).resolve().parent / "themes"
DEFAULT_THEME_NAME = "Light"

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


def _theme_files() -> list[Path]:
    if not THEMES_DIR.is_dir():
        return []
    return sorted(THEMES_DIR.glob("*.yml"))


def _read_theme_yaml(path: Path) -> dict | None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return data if isinstance(data, dict) else None


def list_themes() -> list[str]:
    """Every theme's display ``name`` (e.g. ``["Light", "Dark", "Whiley"]``), in filename order."""
    names = []
    for path in _theme_files():
        data = _read_theme_yaml(path)
        if data and data.get("name"):
            names.append(data["name"])
    return names


def load_theme(name: str) -> Theme:
    for path in _theme_files():
        data = _read_theme_yaml(path)
        if data and data.get("name") == name:
            return Theme(
                name=data["name"],
                palette_colors=data.get("palette") or {},
                disabled_text=data.get("disabled_text"),
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
