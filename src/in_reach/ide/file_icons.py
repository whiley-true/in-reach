"""Per-extension icons for the Explorer panel's file tree.

Every mapped extension (including ``.txt``/``.md``/``.json`` -- originally left sharing this
codebase's generic codicon "new_file" glyph, which read as "every file looks the same" rather than
a deliberate fallback) gets its own glyph, rendered as literal text rather than a hand-traced SVG:
no vector tracing needed (avoiding the "stray artifact" risk ``icons.py``'s own docstring warns
about for hand-drawn glyph data), and Windows' own Segoe UI Emoji already renders a Unicode emoji
character in full color. ``.json`` is the one non-emoji glyph -- a plain ``"{}"`` in an explicit
color (PROMPT.md asks for yellow) rather than an emoji's own fixed color. Only a genuinely unmapped
extension falls back to the shared generic file glyph now.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QFileIconProvider

from in_reach.ide import icons

_GENERIC_FILE_ICON_NAME = "new_file"
_FOLDER_EMOJI_CLOSED = "\U0001F4C1"  # 📁
_FOLDER_EMOJI_OPEN = "\U0001F4C2"  # 📂

# PROMPT.md: "for the icons please use yellow {} for json" -- close to VS Code's own JSON file
# icon color, rather than an arbitrary yellow.
_JSON_COLOR = "#F5DE19"

# Suffix (lowercase, with the leading dot) -> (glyph text, explicit color or None for an emoji's
# own natural color). Anything not listed here falls back to the generic codicon file glyph
# rather than a blank/default icon.
_GLYPH_BY_SUFFIX = {
    ".txt": ("\U0001F4C4", None),  # 📄 -- plain text
    ".md": ("\U0001F4DD", None),  # 📝 -- markdown/notes
    ".json": ("{}", _JSON_COLOR),  # yellow braces -- structured/config data
    ".mvar": ("\U0001F310", None),  # 🌐 -- a map variant
    ".bin": ("\U0001F3AE", None),  # 🎮 -- a game variant
    ".gitignore": ("\U0001F6AB", None),  # 🚫 -- a file whose entire purpose is exclusion
    ".pkl": ("\U0001F952", None),  # 🥒 -- a pickle
    ".mglo": ("\U0001F607", None),  # 😇 -- closest thing Unicode has to a literal "halo"
}


def _glyph_icon(text: str, size: int = 64, *, color: str | None = None) -> QIcon:
    """Renders ``text`` -- a Unicode emoji, or a short literal string like ``"{}"`` -- as a square
    icon glyph.

    Args:
        text: The character(s) to draw, centered, at most a couple of glyphs wide.
        size: Pixel size of the (square) icon.
        color: An explicit fill color for ``text``, bolded to stay legible at a small size. Left
            ``None`` for an emoji, which already renders in its own full color via the system
            emoji font regardless of the painter's pen color.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    font = painter.font()
    font.setPixelSize(int(size * 0.8))
    if color is not None:
        font.setBold(True)
        painter.setPen(QColor(color))
    painter.setFont(font)
    painter.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return QIcon(pixmap)


def icon_for_suffix(suffix: str) -> QIcon:
    """The icon for a file extension, e.g. ``".bin"`` -> the gamepad emoji icon.

    Args:
        suffix: A file suffix including its leading dot (``Path.suffix``'s own shape), or a bare
            filename like ``".gitignore"`` (``Path("...").suffix`` already returns exactly that for
            a dotfile with no further extension, since there's nothing after its one leading dot).

    Returns:
        The mapped glyph icon, or the shared generic file glyph for anything not in
        :data:`_GLYPH_BY_SUFFIX` (including a bare/missing suffix).
    """
    suffix = suffix.lower()
    mapped = _GLYPH_BY_SUFFIX.get(suffix)
    if mapped is not None:
        text, color = mapped
        return _glyph_icon(text, color=color)
    return icons.icon(_GENERIC_FILE_ICON_NAME, size=16)


def icon_for_path(path: Path) -> QIcon:
    """The icon for a filesystem entry -- a folder emoji for a directory, else
    :func:`icon_for_suffix` off its own suffix (or its bare name, for a dotfile like
    ``.gitignore``)."""
    if path.is_dir():
        return _glyph_icon(_FOLDER_EMOJI_CLOSED)
    suffix = path.suffix if path.suffix else path.name
    return icon_for_suffix(suffix)


class ExplorerIconProvider(QFileIconProvider):
    """Feeds :func:`icon_for_path` to a ``QFileSystemModel`` in place of the platform's own
    (generic, OS-themed) file icons."""

    def icon(self, info) -> QIcon:  # noqa: ANN001 -- QFileInfo | QFileIconProvider.IconType
        if hasattr(info, "filePath"):
            return icon_for_path(Path(info.filePath()))
        return super().icon(info)
