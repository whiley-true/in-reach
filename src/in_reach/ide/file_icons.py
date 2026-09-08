"""Per-extension icons for the Explorer panel's file tree.

Two different sources, deliberately: ``.txt``/``.md``/``.json`` reuse this codebase's existing
codicon-derived "new_file" glyph (see ``icons.py``'s own docstring on why only *verified* real path
data gets traced into an SVG glyph here -- there's no second, per-type codicon glyph already
vetted in this repo, and fabricating new path data risks exactly the "stray artifact" that
docstring warns against). Everything PROMPT.md asked for by emoji (map/game-variant/gitignore/
pickle/Megalo script) is rendered as the literal Unicode character instead -- no vector tracing
needed, and Windows' own Segoe UI Emoji already renders them in full color.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QFileIconProvider

from in_reach.ide import icons

_GENERIC_FILE_ICON_NAME = "new_file"
_FOLDER_EMOJI_CLOSED = "\U0001F4C1"  # 📁
_FOLDER_EMOJI_OPEN = "\U0001F4C2"  # 📂

# Suffix (lowercase, with the leading dot) -> emoji. Anything not listed here falls back to the
# generic codicon file glyph rather than a blank/default icon.
_EMOJI_BY_SUFFIX = {
    ".mvar": "\U0001F310",  # 🌐 -- a map variant
    ".bin": "\U0001F3AE",  # 🎮 -- a game variant
    ".gitignore": "\U0001F6AB",  # 🚫 -- a file whose entire purpose is exclusion
    ".pkl": "\U0001F952",  # 🥒 -- a pickle
    ".mglo": "\U0001F607",  # 😇 -- closest thing Unicode has to a literal "halo"
}

_CODICON_SUFFIXES = {".txt", ".md", ".json"}


def _emoji_icon(emoji: str, size: int = 64) -> QIcon:
    """Renders a single Unicode character as a square icon, via the system emoji font."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    font = painter.font()
    font.setPixelSize(int(size * 0.8))
    painter.setFont(font)
    painter.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, emoji)
    painter.end()
    return QIcon(pixmap)


def icon_for_suffix(suffix: str) -> QIcon:
    """The icon for a file extension, e.g. ``".bin"`` -> the gamepad emoji icon.

    Args:
        suffix: A file suffix including its leading dot (``Path.suffix``'s own shape), or a bare
            filename like ``".gitignore"`` (``Path("...").suffix`` already returns exactly that for
            a dotfile with no further extension, since there's nothing after its one leading dot).

    Returns:
        The mapped emoji icon, or the shared generic file glyph for anything unmapped (including
        ``.txt``/``.md``/``.json``, and a bare/missing suffix).
    """
    suffix = suffix.lower()
    emoji = _EMOJI_BY_SUFFIX.get(suffix)
    if emoji is not None:
        return _emoji_icon(emoji)
    return icons.icon(_GENERIC_FILE_ICON_NAME, size=16)


def icon_for_path(path: Path) -> QIcon:
    """The icon for a filesystem entry -- a folder emoji for a directory, else
    :func:`icon_for_suffix` off its own suffix (or its bare name, for a dotfile like
    ``.gitignore``)."""
    if path.is_dir():
        return _emoji_icon(_FOLDER_EMOJI_CLOSED)
    suffix = path.suffix if path.suffix else path.name
    return icon_for_suffix(suffix)


class ExplorerIconProvider(QFileIconProvider):
    """Feeds :func:`icon_for_path` to a ``QFileSystemModel`` in place of the platform's own
    (generic, OS-themed) file icons."""

    def icon(self, info) -> QIcon:  # noqa: ANN001 -- QFileInfo | QFileIconProvider.IconType
        if hasattr(info, "filePath"):
            return icon_for_path(Path(info.filePath()))
        return super().icon(info)
