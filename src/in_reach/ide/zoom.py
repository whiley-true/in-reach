"""Ctrl+= / Ctrl+- text-and-component zoom.

An application-wide font scale rather than anything more surgical: nearly every widget in this IDE
(buttons, checkboxes, labels, the tab bar's own height -- see ``tabs.py``'s ``bar_height``) sizes
itself off font metrics rather than a fixed pixel dimension, so scaling the font scales practically
everything drawn from it, text and component alike, for free.

Persisted to the project's own ``.env`` (the same file ``FIRST_USE`` already lives in -- see
``ide/app.py``) under :data:`ZOOM_KEY`, so it survives between runs of the same project rather than
resetting to :data:`DEFAULT_ZOOM` every time the IDE reopens.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from in_reach.app import env_file

ZOOM_KEY = "UI_ZOOM"
# 135% of the plain (100%) app font -- PROMPT.md asks for this as the out-of-the-box size rather
# than true 100%, so a fresh project already opens at the size that scaling was actually tuned
# against. Originally 150%, then reduced 10% (PROMPT.md: "please reduce the default text ui scale
# by 10%") to 1.5 * 0.9. MAX_ZOOM is widened to match -- otherwise this default would sit one step
# from the ceiling, leaving almost no room to zoom in any further.
DEFAULT_ZOOM = 1.35
MIN_ZOOM = 0.7
MAX_ZOOM = 2.0
ZOOM_STEP = 0.1

# The app's own un-zoomed font, captured the first time apply_zoom() runs without an explicit
# base_font -- every zoom level is computed from this fixed baseline rather than whatever the
# previous zoom left app.font() at, so repeated zoom-in/zoom-out cycles can't drift from rounding.
_base_font: QFont | None = None


def _clamp(zoom: float) -> float:
    return round(max(MIN_ZOOM, min(MAX_ZOOM, zoom)), 2)


def get_zoom(env_path: Path) -> float:
    """Reads a project's saved zoom level.

    Args:
        env_path: Path to the project's ``.env`` file.

    Returns:
        The stored value, clamped to ``[``:data:`MIN_ZOOM` ``, ``:data:`MAX_ZOOM` ``]``, or
        :data:`DEFAULT_ZOOM` if nothing's stored yet (or it's unparsable).
    """
    raw = env_file.get_env_values(env_path).get(ZOOM_KEY, "")
    try:
        return _clamp(float(raw)) if raw else DEFAULT_ZOOM
    except ValueError:
        return DEFAULT_ZOOM


def set_zoom(env_path: Path, zoom: float) -> float:
    """Clamps ``zoom`` and writes it back to the project's ``.env``.

    Args:
        env_path: Path to the project's ``.env`` file.
        zoom: The zoom factor to store, e.g. ``1.0`` for no zoom.

    Returns:
        The value actually stored, after clamping.
    """
    clamped = _clamp(zoom)
    env_file.update_env_value(env_path, ZOOM_KEY, f"{clamped:.2f}")
    return clamped


def apply_zoom(app: QApplication, zoom: float, *, base_font: QFont | None = None) -> None:
    """Scales the application font to ``zoom`` and re-polishes every live widget.

    Args:
        app: The running QApplication.
        zoom: The zoom factor to apply, e.g. ``1.0`` for no zoom.
        base_font: Injectable baseline font, for testing -- bypasses the module-level captured
            baseline so a test can assert an exact before/after ratio regardless of what a previous
            test in the same process already zoomed the shared QApplication to. Real callers never
            need to pass this; the baseline is captured automatically the first time it's needed.
    """
    global _base_font
    if base_font is not None:
        reference = base_font
    else:
        if _base_font is None:
            _base_font = QFont(app.font())
        reference = _base_font

    font = QFont(reference)
    font.setPointSizeF(reference.pointSizeF() * zoom)
    app.setFont(font)
    # A per-widget stylesheet rule cached as a "render rule" the first time a widget is polished
    # doesn't pick up a bare font change on its own -- same reasoning (and same fix) as
    # theme.apply_theme()'s own unpolish/polish loop.
    for widget in app.allWidgets():
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.updateGeometry()


def current_scale(app: QApplication) -> float:
    """The zoom ratio the app's live font is actually rendered at right now, versus its baseline.

    A rendered icon (a fixed-size ``QPixmap`` baked once at construction, unlike text which
    reflows for free off the live ``QFont``) has to be told explicitly to re-render at a new size
    -- see ``MainWindow.refresh_icon_colors()``, which multiplies its own base pixel sizes by this
    rather than keeping a second, separately-tracked copy of "the current zoom" of its own.

    Args:
        app: The running QApplication.

    Returns:
        ``app.font().pointSizeF() / <captured baseline>``, or ``1.0`` if no baseline has been
        captured yet (``apply_zoom()`` was never called) -- icons then stay at their plain,
        un-zoomed size rather than dividing by an unset baseline.
    """
    if _base_font is None:
        return 1.0
    baseline = _base_font.pointSizeF()
    if baseline <= 0:
        return 1.0
    return app.font().pointSizeF() / baseline
