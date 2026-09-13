"""Icon set for the activity bar, top-bar toggle buttons, and window controls.

Real path data from Microsoft's codicon set (MIT-licensed,
https://github.com/microsoft/vscode-codicons/tree/main/src/icons) for the "search"/"settings"/
"sidebar"/"panel" glyphs -- using verified icon paths avoids shipping a hand-drawn glyph with a
stray artifact in it. The window-control glyphs (minimize/maximize/restore/close) are trivial
geometric shapes, deliberately not traced from any icon set, since a plain line/square/X can't
carry that kind of mistake.

Each glyph's fill color is a ``{color}`` template slot rather than hardcoded, so the same path
data can be rendered in whatever color a caller needs.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QByteArray, QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PyQt6.QtSvg import QSvgRenderer

DEFAULT_COLOR = "#cccccc"

_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
_APP_ICON_FILE = "icon-bluegrey-small-windows.svg"
_TOPBAR_ICON_FILE = "icon-bluegrey-micro.svg"
# ReachVariantTool's own real icon (github.com/DavidJCobb/ReachVariantEditor, GPLv3) -- a raster
# PNG, not traced into an SVG glyph like the codicon-derived entries below: there's no vector
# source for it anywhere in that project (only this PNG and a matching .ico). A from-scratch line-
# drawing SVG was tried in its place for a while, but per the user's own call, the sidebar's RVT
# button is back to using this real icon -- QIcon handles a PNG exactly the same way it does the
# SVGs above (app_icon()/topbar_icon()), so it stays consistent with them despite the different
# source format.
_RVT_ICON_FILE = "rvt-icon-128.png"

_SVG_TEMPLATE = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view_box}" fill="{{color}}">{path}</svg>'

# (viewBox, path `d` data)
_ICON_SOURCES = {
    "search": (  # codicon "search"
        "0 0 16 16",
        '<path d="M10.0195 10.7266C9.06578 11.5217 7.83875 12 6.5 12C3.46243 12 1 9.53757 1 6.5C1 3.46243 3.46243 1 6.5 1C9.53757 1 12 3.46243 12 6.5C12 7.83875 11.5217 9.06578 10.7266 10.0195L13.8535 13.1464C14.0488 13.3417 14.0488 13.6583 13.8535 13.8536C13.6583 14.0488 13.3417 14.0488 13.1464 13.8536L10.0195 10.7266ZM11 6.5C11 4.01472 8.98528 2 6.5 2C4.01472 2 2 4.01472 2 6.5C2 8.98528 4.01472 11 6.5 11C8.98528 11 11 8.98528 11 6.5Z"/>',
    ),
    "settings": (  # codicon "gear"
        "0 0 16 16",
        '<path d="M7.99997 6C6.89497 6 5.99997 6.895 5.99997 8C5.99997 9.105 6.89497 10 7.99997 10C9.10497 10 9.99997 9.105 9.99997 8C9.99997 6.895 9.10497 6 7.99997 6ZM7.99997 9C7.44797 9 6.99997 8.552 6.99997 8C6.99997 7.448 7.44797 7 7.99997 7C8.55197 7 8.99997 7.448 8.99997 8C8.99997 8.552 8.55197 9 7.99997 9ZM14.565 9.715L13.279 8.628C13.245 8.599 13.213 8.567 13.184 8.533C12.888 8.186 12.931 7.667 13.279 7.372L14.565 6.285C14.693 6.177 14.742 6.003 14.691 5.844C14.386 4.903 13.882 4.04 13.219 3.308C13.139 3.22 13.027 3.172 12.912 3.172C12.865 3.172 12.818 3.18 12.773 3.196L11.186 3.761C11.144 3.776 11.1 3.788 11.056 3.796C11.006 3.805 10.956 3.81 10.907 3.81C10.515 3.81 10.167 3.532 10.094 3.134L9.79097 1.482C9.76097 1.318 9.63397 1.188 9.46997 1.153C8.98997 1.051 8.49897 1 8.00097 1C7.50297 1 7.01097 1.052 6.53097 1.153C6.36697 1.188 6.23997 1.318 6.20997 1.482L5.90797 3.134C5.89997 3.178 5.88797 3.221 5.87297 3.263C5.75197 3.6 5.43397 3.81 5.09397 3.81C5.00197 3.81 4.90797 3.794 4.81597 3.762L3.22897 3.197C3.18397 3.181 3.13597 3.173 3.08997 3.173C2.97497 3.173 2.86297 3.221 2.78297 3.309C2.11897 4.041 1.61597 4.904 1.30997 5.845C1.25797 6.004 1.30797 6.178 1.43597 6.286L2.72197 7.373C2.75597 7.402 2.78797 7.434 2.81697 7.468C3.11297 7.815 3.06997 8.334 2.72197 8.629L1.43597 9.716C1.30797 9.824 1.25897 9.998 1.30997 10.157C1.61497 11.098 2.11897 11.961 2.78297 12.693C2.86297 12.781 2.97497 12.829 3.08997 12.829C3.13697 12.829 3.18397 12.821 3.22897 12.805L4.81597 12.24C4.85797 12.225 4.90197 12.213 4.94597 12.205C4.99597 12.196 5.04597 12.192 5.09497 12.192C5.48697 12.192 5.83497 12.47 5.90797 12.868L6.20997 14.52C6.23997 14.684 6.36697 14.814 6.53097 14.849C7.01097 14.951 7.50297 15.002 8.00097 15.002C8.49897 15.002 8.99097 14.95 9.46997 14.849C9.63397 14.814 9.76097 14.684 9.79097 14.52L10.094 12.868C10.102 12.824 10.114 12.781 10.129 12.739C10.25 12.402 10.568 12.192 10.908 12.192C11 12.192 11.094 12.208 11.186 12.24L12.772 12.805C12.818 12.821 12.865 12.829 12.911 12.829C13.026 12.829 13.138 12.781 13.218 12.693C13.882 11.961 14.385 11.098 14.69 10.157C14.742 9.998 14.692 9.824 14.564 9.716L14.565 9.715ZM12.728 11.726L11.521 11.296C11.323 11.226 11.117 11.19 10.908 11.19C10.139 11.19 9.44697 11.676 9.18797 12.399C9.15397 12.492 9.12897 12.588 9.11097 12.686L8.88097 13.937C8.59097 13.979 8.29597 14 8.00097 14C7.70597 14 7.41097 13.979 7.11997 13.936L6.89097 12.685C6.73197 11.818 5.97697 11.189 5.09497 11.189C4.98697 11.189 4.87697 11.199 4.76597 11.219C4.66897 11.237 4.57397 11.262 4.47997 11.295L3.27297 11.725C2.90497 11.264 2.61097 10.759 2.39397 10.214L3.36797 9.391C3.74097 9.076 3.96797 8.634 4.00797 8.148C4.04797 7.662 3.89497 7.19 3.57797 6.818C3.51397 6.743 3.44297 6.672 3.36797 6.608L2.39397 5.785C2.61097 5.24 2.90497 4.734 3.27297 4.274L4.47997 4.704C4.67797 4.774 4.88397 4.81 5.09397 4.81C5.86297 4.81 6.55497 4.324 6.81397 3.601C6.84797 3.507 6.87297 3.411 6.89097 3.314L7.11997 2.063C7.41097 2.021 7.70597 1.999 8.00097 1.999C8.29597 1.999 8.59097 2.02 8.88097 2.062L9.10997 3.313C9.26897 4.18 10.024 4.809 10.906 4.809C11.014 4.809 11.124 4.799 11.234 4.779C11.331 4.761 11.427 4.736 11.521 4.703L12.728 4.273C13.096 4.733 13.39 5.239 13.607 5.784L12.634 6.607C12.261 6.922 12.033 7.364 11.994 7.85C11.954 8.336 12.107 8.809 12.424 9.18C12.489 9.256 12.559 9.326 12.635 9.39L13.609 10.213C13.392 10.758 13.098 11.264 12.73 11.724L12.728 11.726Z"/>',
    ),
    "sidebar": (  # codicon "layout-sidebar-left" (Toggle Primary Side Bar)
        "0 0 16 16",
        '<path d="M12.5 1C13.881 1 15 2.119 15 3.5V12.5C15 13.881 13.881 15 12.5 15H3.5C2.119 15 1 13.881 1 12.5V3.5C1 2.119 2.119 1 3.5 1H12.5ZM12.5 14C13.328 14 14 13.328 14 12.5V3.5C14 2.672 13.328 2 12.5 2H7V14H12.5Z"/>',
    ),
    "panel": (  # codicon "layout-panel" (Toggle Panel)
        "0 0 16 16",
        '<path d="M15 12.5C15 13.881 13.881 15 12.5 15H3.5C2.119 15 1 13.881 1 12.5V3.5C1 2.119 2.119 1 3.5 1H12.5C13.881 1 15 2.119 15 3.5V12.5ZM2 10H14V3.5C14 2.672 13.328 2 12.5 2H3.5C2.672 2 2 2.672 2 3.5V10Z"/>',
    ),
    "split": (  # plain two-pane rectangle (left/right), deliberately simple -- no matching codicon
        "0 0 16 16",
        '<path d="M2.5 2C1.67157 2 1 2.67157 1 3.5V12.5C1 13.3284 1.67157 14 2.5 14H13.5C14.3284 14 15 13.3284 15 12.5V3.5C15 2.67157 14.3284 2 13.5 2H2.5ZM2 3.5C2 3.22386 2.22386 3 2.5 3H7V13H2.5C2.22386 13 2 12.7761 2 12.5V3.5ZM9 13V3H13.5C13.7761 3 14 3.22386 14 3.5V12.5C14 12.7761 13.7761 13 13.5 13H9Z"/>',
    ),
    "split_vertical": (  # same two-pane rectangle, transposed to stack top/bottom
        "0 0 16 16",
        '<path d="M2.5 2C1.67157 2 1 2.67157 1 3.5V12.5C1 13.3284 1.67157 14 2.5 14H13.5C14.3284 14 15 13.3284 15 12.5V3.5C15 2.67157 14.3284 2 13.5 2H2.5ZM2 3.5C2 3.22386 2.22386 3 2.5 3H13.5C13.7761 3 14 3.22386 14 3.5V7H2V3.5ZM2 9H14V12.5C14 12.7761 13.7761 13 13.5 13H2.5C2.22386 13 2 12.7761 2 12.5V9Z"/>',
    ),
    "chevron_down": (  # codicon "chevron-down", used for the topbar text1/text2 dropdowns
        "0 0 16 16",
        '<path d="M7.976 10.072l4.357-4.357.62.618L8.284 11h-.618L3 6.333l.619-.618 4.357 4.357z"/>',
    ),
    "explorer": (  # codicon "files" (generic "browse a folder" glyph -- New/Load Project, Recent)
        "0 0 24 24",
        '<path d="M7.5 22.5H17.595C17.07 23.4 16.11 24 15 24H7.5C4.185 24 1.5 21.315 1.5 18V6C1.5 4.89 2.1 3.93 3 3.405V18C3 20.475 5.025 22.5 7.5 22.5ZM21 8.121V18C21 19.6545 19.6545 21 18 21H7.5C5.8455 21 4.5 19.6545 4.5 18V3C4.5 1.3455 5.8455 0 7.5 0H12.879C13.4715 0 14.0505 0.24 14.4705 0.6585L20.3415 6.5295C20.766 6.954 21 7.5195 21 8.121ZM13.5 6.75C13.5 7.164 13.8375 7.5 14.25 7.5H19.1895L13.5 1.8105V6.75ZM19.5 18V9H14.25C13.0095 9 12 7.9905 12 6.75V1.5H7.5C6.672 1.5 6 2.1735 6 3V18C6 18.8265 6.672 19.5 7.5 19.5H18C18.828 19.5 19.5 18.8265 19.5 18Z"/>',
    ),
    "dashboard": (  # PROMPT.md: "please update the icon/svg for dashboards to be something else
        # instead -- maybe use a speedometer design instead" -- a simple gauge dial, needle, and
        # pivot dot, deliberately simple rather than traced from any icon set (same reasoning as
        # "split"/"split_vertical" above). fill="none"/explicit stroke on the dial and needle
        # override the outer <svg>'s own fill="{color}" (see icon()'s own docstring), so those
        # draw as strokes rather than solid-filled wedges.
        "0 0 16 16",
        '<path d="M2.25 12.5A5.75 5.75 0 0 1 13.75 12.5" fill="none" stroke="{color}" stroke-width="1.4" stroke-linecap="round"/>'
        '<path d="M8 12.5L11 8" stroke="{color}" stroke-width="1.4" stroke-linecap="round"/>'
        '<circle cx="8" cy="12.5" r="1.2" fill="{color}"/>'
        '<path d="M5.25 14.5H10.75" stroke="{color}" stroke-width="1.4" stroke-linecap="round"/>',
    ),
    "stats": (  # a plain ascending bar-chart, same "deliberately simple, not traced" reasoning.
        "0 0 16 16",
        '<path d="M2 9H5V14H2V9ZM6.5 5H9.5V14H6.5V5ZM11 2H14V14H11V2Z"/>',
    ),
    "new_file": (  # codicon "new-file" (Welcome tab's "New Gametype" row)
        "0 0 16 16",
        '<path d="M5 14C4.448 14 4 13.552 4 13V3C4 2.448 4.448 2 5 2H8V4.5C8 5.328 8.672 6 9.5 6H12V6.025C12.344 6.056 12.677 6.121 13 6.213V5.414C13 5.016 12.842 4.635 12.561 4.353L9.647 1.439C9.366 1.158 8.984 1 8.586 1H5C3.895 1 3 1.895 3 3V13C3 14.105 3.895 15 5 15H7.261C7.008 14.693 6.791 14.357 6.607 14H5ZM9 2.207L11.793 5H9.5C9.224 5 9 4.776 9 4.5V2.207ZM11.5 7C9.015 7 7 9.015 7 11.5C7 13.985 9.015 16 11.5 16C13.985 16 16 13.985 16 11.5C16 9.015 13.985 7 11.5 7ZM14 12H12V14C12 14.276 11.776 14.5 11.5 14.5C11.224 14.5 11 14.276 11 14V12H9C8.724 12 8.5 11.776 8.5 11.5C8.5 11.224 8.724 11 9 11H11V9C11 8.724 11.224 8.5 11.5 8.5C11.776 8.5 12 8.724 12 9V11H14C14.276 11 14.5 11.224 14.5 11.5C14.5 11.776 14.276 12 14 12Z"/>',
    ),
    "tab_dirty": (  # plain filled dot -- shown instead of the close 'x' on an unsaved tab
        "0 0 16 16",
        '<circle cx="8" cy="8" r="3.5"/>',
    ),
    "compass": (  # PROMPT.md: "please also add a side icon of a bookshelf (titled Locations)",
        # later: "for locations please use a compass icon" -- a ring plus a two-tone needle
        # (the north half solid, the south half translucent, both traced as plain kite-shaped
        # polygons), same "deliberately simple, not traced from any icon set" reasoning as
        # "dashboard"/"stats" above.
        "0 0 16 16",
        '<circle cx="8" cy="8" r="6.3" fill="none" stroke="{color}" stroke-width="1.3"/>'
        '<path d="M8 3.2L9.6 8L8 8.9L6.4 8Z" fill="{color}"/>'
        '<path d="M8 12.8L6.4 8L8 7.1L9.6 8Z" fill="{color}" fill-opacity="0.45"/>',
    ),
    "git": (  # PROMPT.md: "a git symbol (stubbed empty panel for now (where we will implement a
        # dulwich gui))" -- a plain three-node branch graph (a main-line commit at top and bottom,
        # a branch point curving off to a third node), same "deliberately simple, not traced from
        # any icon set" reasoning as "compass"/"dashboard" below.
        "0 0 16 16",
        '<circle cx="4" cy="3" r="1.5" fill="{color}"/>'
        '<circle cx="4" cy="13" r="1.5" fill="{color}"/>'
        '<circle cx="12" cy="9" r="1.5" fill="{color}"/>'
        '<path d="M4 4.5V11.5" stroke="{color}" stroke-width="1.3" fill="none"/>'
        '<path d="M4 7.5C4 9 5 9.8 7 9.8C9 9.8 10 9.5 10.6 9.3" fill="none" stroke="{color}" stroke-width="1.3"/>',
    ),
    "bookshelf": (  # PROMPT.md: "a bookshelf with the label Scripts" -- a row of book spines
        # (plain rectangles, varying height) standing on a shelf line, same "deliberately simple"
        # reasoning as "compass"/"dashboard" below.
        "0 0 16 16",
        '<path d="M1.5 13.5H14.5" stroke="{color}" stroke-width="1.2" stroke-linecap="round" fill="none"/>'
        '<rect x="2.3" y="4.2" width="2" height="9" fill="{color}"/>'
        '<rect x="5.1" y="2.6" width="2" height="10.6" fill="{color}"/>'
        '<rect x="7.9" y="5.4" width="2" height="7.8" fill="{color}"/>'
        '<rect x="10.7" y="3.6" width="2" height="9.6" fill="{color}"/>'
        '<rect x="13.2" y="6.6" width="1.2" height="6.6" fill="{color}"/>',
    ),
    "help": (  # PROMPT.md: "please then add a help (?) icon above the settings icon" -- a plain
        # circled question mark, same "deliberately simple" reasoning as "compass" above.
        "0 0 16 16",
        '<circle cx="8" cy="8" r="6.5" fill="none" stroke="{color}" stroke-width="1.3"/>'
        '<path d="M6.2 6.1c0-1.05.85-1.9 1.9-1.9s1.9.72 1.9 1.7c0 .95-.6 1.35-1.15 1.75'
        '-.5.36-.75.6-.75 1.15" fill="none" stroke="{color}" stroke-width="1.2" stroke-linecap="round"/>'
        '<circle cx="8" cy="11.2" r="0.75" fill="{color}"/>',
    ),
    # Window controls: plain geometric shapes only (no glyph tracing needed at all).
    "win_minimize": (
        "0 0 16 16",
        '<path d="M3 8H13V9H3V8Z"/>',
    ),
    "win_maximize": (
        "0 0 16 16",
        '<path d="M3.5 3H12.5C12.7761 3 13 3.22386 13 3.5V12.5C13 12.7761 12.7761 13 12.5 13H3.5C3.22386 13 3 12.7761 3 12.5V3.5C3 3.22386 3.22386 3 3.5 3ZM4 4V12H12V4H4Z"/>',
    ),
    "win_restore": (
        "0 0 16 16",
        '<path d="M5.5 3H12.5C12.7761 3 13 3.22386 13 3.5V10.5C13 10.7761 12.7761 11 12.5 11H11V12.5C11 12.7761 10.7761 13 10.5 13H3.5C3.22386 13 3 12.7761 3 12.5V5.5C3 5.22386 3.22386 5 3.5 5H5V3.5C5 3.22386 5.22386 3 5.5 3ZM6 5H10.5C10.7761 5 11 5.22386 11 5.5V10H12V4H6V5ZM4 6V12H10V6H4Z"/>',
    ),
    "win_close": (
        "0 0 16 16",
        '<path d="M8 7.293L11.646 3.646L12.354 4.354L8.707 8L12.354 11.646L11.646 12.354L8 8.707L4.354 12.354L3.646 11.646L7.293 8L3.646 4.354L4.354 3.646L8 7.293Z"/>',
    ),
}


def icon(name: str, color: str = DEFAULT_COLOR, size: int = 24) -> QIcon:
    """Renders the named glyph to a QIcon at ``size``x``size``.

    Falls back to a blank icon for an unknown ``name`` rather than raising.
    """
    source = _ICON_SOURCES.get(name)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    if source is not None:
        view_box, path = source
        svg = _SVG_TEMPLATE.format(view_box=view_box, path=path).format(color=color)
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)
        painter.end()
    return QIcon(pixmap)


def app_icon() -> QIcon:
    """The full-color logo used as the taskbar/window icon."""
    return QIcon(str(_ASSETS_DIR / _APP_ICON_FILE))


def topbar_icon() -> QIcon:
    """The small mark shown in the top bar's left corner, ahead of the dropdown menus."""
    return QIcon(str(_ASSETS_DIR / _TOPBAR_ICON_FILE))


def rvt_icon(*, enabled: bool = True) -> QIcon:
    """ReachVariantTool's own real icon -- the activity bar's "launch RVT" button.

    Args:
        enabled: When ``False`` (PROMPT.md: "rvt should not be launchable if no project is open
            (the icon should have a dash in front of it)"), overlays a small "no entry"
            circle-and-dash badge in the corner.
    """
    pixmap = QPixmap(str(_ASSETS_DIR / _RVT_ICON_FILE))
    if enabled:
        return QIcon(pixmap)
    badged = _with_disabled_badge(pixmap)
    icon = QIcon()
    # A disabled QToolButton renders its icon's Disabled-mode pixmap, not Normal -- and by
    # default Qt *auto-generates* that Disabled pixmap from Normal by desaturating/fading it,
    # which was quietly washing the red badge out to near-invisibility. Registering the already-
    # badged pixmap for both modes explicitly means the button shows this exact artwork either
    # way, rather than Qt's own generated (and here, illegible) variant.
    icon.addPixmap(badged, QIcon.Mode.Normal)
    icon.addPixmap(badged, QIcon.Mode.Disabled)
    return icon


def _with_disabled_badge(pixmap: QPixmap) -> QPixmap:
    """Overlays a small red circle-and-dash "blocked" badge in the bottom-right corner of
    ``pixmap`` -- a copy, ``pixmap`` itself is left untouched."""
    badged = QPixmap(pixmap)
    size = min(badged.width(), badged.height())
    badge_size = max(6, round(size * 0.55))
    x = badged.width() - badge_size
    y = badged.height() - badge_size

    painter = QPainter(badged)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#e51400"))
    painter.drawEllipse(x, y, badge_size, badge_size)
    painter.setPen(QColor("#ffffff"))
    pen = painter.pen()
    pen.setWidthF(max(1.0, badge_size * 0.16))
    painter.setPen(pen)
    dash_margin = badge_size * 0.28
    dash_y = y + badge_size / 2
    painter.drawLine(round(x + dash_margin), round(dash_y), round(x + badge_size - dash_margin), round(dash_y))
    painter.end()
    return badged


def apply_icon(color: str = DEFAULT_COLOR, size: int = 24, *, enabled: bool = True) -> QIcon:
    """A horizontal-arrow glyph -- the activity bar's own compile/"Apply" button (PROMPT.md:
    "make it so the tick in the side panel was instead a horizontal arrow (representing
    compiling)"; originally a checkmark, see git history for that). Deliberately simple geometric
    shape, same "not traced from any icon set" reasoning as :data:`_ICON_SOURCES`'s own
    "dashboard"/"stats"/"compass" entries -- a mis-plotted polygon here is an easy, easy-to-miss
    mistake, and there's no ready-made codicon for "compile".

    Args:
        enabled: When ``True``, there's something pending to compile -- a plain arrow, no badge.
            When ``False`` (PROMPT.md: "has small green tick (same size as the do not enter sign)
            when there is nothing to compile"), overlays a small green tick badge instead of the
            red "no entry" badge :func:`rvt_icon` uses -- "nothing to compile" is a fine/expected
            state here, not a blocked one, so it reads as a positive confirmation rather than an
            error. Registered for both Normal and Disabled icon modes, same reason as
            :func:`rvt_icon`.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(max(1.4, size * 0.09))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    mid_y = size * 0.5
    painter.drawLine(QPointF(size * 0.18, mid_y), QPointF(size * 0.68, mid_y))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawPolygon(
        QPolygonF(
            [
                QPointF(size * 0.56, size * 0.28),
                QPointF(size * 0.86, mid_y),
                QPointF(size * 0.56, size * 0.72),
            ]
        )
    )
    painter.end()
    if enabled:
        return QIcon(pixmap)
    badged = _with_done_badge(pixmap)
    icon = QIcon()
    icon.addPixmap(badged, QIcon.Mode.Normal)
    icon.addPixmap(badged, QIcon.Mode.Disabled)
    return icon


def _with_done_badge(pixmap: QPixmap) -> QPixmap:
    """Overlays a small green circle-and-tick "all done" badge in the bottom-right corner of
    ``pixmap`` -- a copy, ``pixmap`` itself is left untouched. Same size/position as
    :func:`_with_disabled_badge`'s own red "blocked" badge, just a different color/glyph for a
    fine/expected state (PROMPT.md: "has small green tick (same size as the do not enter sign)")."""
    badged = QPixmap(pixmap)
    size = min(badged.width(), badged.height())
    badge_size = max(6, round(size * 0.55))
    x = badged.width() - badge_size
    y = badged.height() - badge_size

    painter = QPainter(badged)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#2ea043"))
    painter.drawEllipse(x, y, badge_size, badge_size)
    pen = QPen(QColor("#ffffff"))
    pen.setWidthF(max(1.0, badge_size * 0.18))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    cx, cy = x + badge_size / 2, y + badge_size / 2
    painter.drawPolyline(
        QPolygonF(
            [
                QPointF(cx - badge_size * 0.22, cy),
                QPointF(cx - badge_size * 0.04, cy + badge_size * 0.2),
                QPointF(cx + badge_size * 0.26, cy - badge_size * 0.22),
            ]
        )
    )
    painter.end()
    return badged


def lock_icon(size: int = 16) -> QIcon:
    """A padlock glyph -- shown in the tab of a read-only, autogenerated file (PROMPT.md: "they
    have a padlock symbol in the tab and cann[o]t be edited"). A real Unicode lock character, not
    hand-traced SVG path data -- same reasoning as :func:`apply_icon`. Renders in its own full
    color regardless of any painter pen color, same as an emoji anywhere else in this codebase (see
    :mod:`in_reach.ide.file_icons`'s own glyph icons), so this takes no ``color`` argument.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    font = painter.font()
    font.setPixelSize(round(size * 0.85))
    painter.setFont(font)
    painter.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, "🔒")
    painter.end()
    return QIcon(pixmap)


#: PROMPT.md: "a flame icon which can be of different states depending on the status of the
#: players halo install and running detection ... just firewood: player has not verified their
#: install ... after being verified the firewood should have the outline of a flame ... if [Halo:
#: MCC] is running ... the flame should be filled" -- the activity bar's bottom-pinned Halo status
#: indicator (see :meth:`~in_reach.ide.activity_bar.ActivityBar.set_halo_status`).
STATUS_UNVERIFIED = "unverified"
STATUS_VERIFIED = "verified"
STATUS_RUNNING = "running"


def _firewood_path(size: float) -> tuple[QPainterPath, float]:
    """Two logs leaning together in a peak, confined to the icon's own bottom quarter (and the
    stroke width to draw them at) -- present in every :func:`status_icon` state, per PROMPT.md's
    own "just firewood" starting point. Kept well clear of :func:`_flame_path`'s own vertical span
    -- PROMPT.md: "make the different icon statuses a little more obvious" -- so the two never
    visually merge into one blob the way an earlier, taller/overlapping pass did.
    """
    path = QPainterPath()
    log_width = size * 0.13
    for start, end in (
        (QPointF(size * 0.18, size * 0.96), QPointF(size * 0.82, size * 0.74)),
        (QPointF(size * 0.82, size * 0.96), QPointF(size * 0.18, size * 0.74)),
    ):
        segment = QPainterPath()
        segment.moveTo(start)
        segment.lineTo(end)
        path.addPath(segment)
    return path, log_width


def _flame_path(size: float) -> QPainterPath:
    """A large, simple teardrop confined to the icon's own top ~60% -- deliberately simple
    geometry (just two curves, no inner "flicker" notch -- that self-intersected, which left a
    hole in the middle when filled), same reasoning as this module's other hand-drawn glyphs
    (compass/dashboard/help/apply_icon), not traced from any icon set. Sized to read clearly at
    the activity bar's own small icon sizes -- PROMPT.md: "make the different icon statuses a
    little more obvious" -- rather than a smaller, more delicate shape easily lost next to the
    firewood.
    """
    path = QPainterPath()
    path.moveTo(size * 0.50, size * 0.03)
    path.cubicTo(size * 0.90, size * 0.32, size * 0.78, size * 0.58, size * 0.68, size * 0.68)
    path.quadTo(size * 0.50, size * 0.78, size * 0.32, size * 0.68)
    path.cubicTo(size * 0.22, size * 0.58, size * 0.10, size * 0.32, size * 0.50, size * 0.03)
    path.closeSubpath()
    return path


def status_icon(state: str, color: str = DEFAULT_COLOR, size: int = 24) -> QIcon:
    """The activity bar's Halo install/running status indicator.

    Args:
        state: One of :data:`STATUS_UNVERIFIED` (just the firewood -- nothing verified yet),
            :data:`STATUS_VERIFIED` (firewood plus a flame *outline*), or :data:`STATUS_RUNNING`
            (firewood plus a *filled* flame). Falls back to :data:`STATUS_UNVERIFIED` for any
            other value rather than raising.
        color: Stroke/fill color for both the firewood and the flame.
        size: Pixel width/height to render at.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    logs_path, log_width = _firewood_path(size)
    pen = QPen(QColor(color))
    pen.setWidthF(log_width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.strokePath(logs_path, pen)

    if state in (STATUS_VERIFIED, STATUS_RUNNING):
        flame_path = _flame_path(size)
        if state == STATUS_RUNNING:
            painter.fillPath(flame_path, QColor(color))
        else:
            outline_pen = QPen(QColor(color))
            outline_pen.setWidthF(max(1.4, size * 0.09))
            painter.strokePath(flame_path, outline_pen)

    painter.end()
    return QIcon(pixmap)
