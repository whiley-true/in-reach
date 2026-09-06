"""Shared QSS building blocks for the "rounded card" look every top-level panel in the IDE uses --
adapted from the previous mini-IDE prototype's own ``ide/main_window.py`` (see
``D:\\whileyRepos\\sort\\mega-ide\\IDE.md``'s "Panel backgrounds are now a distinct, lighter shade"
and "Editor/terminal tab strips are now visually part of the same rounded card as their content").

Every major region (activity bar, primary sidebar, each split pane, the bottom panel) is its own
bordered, rounded, ``palette(base)``-filled card, with a window-background gap left between cards
(``PANEL_GAP``/``SIDEBAR_CONTENT_GAP``) so the rounding actually reads as rounded rather than
flush against a neighbor.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

PANEL_RADIUS = 6
PANEL_GAP = 8
SIDEBAR_CONTENT_GAP = 16

# A splitter between two already-fully-bordered cards should just be window-background gap, not a
# second boundary line drawn on top of each card's own border.
GAP_SPLITTER_HANDLE_STYLE = "QSplitter::handle { background-color: transparent; }"

# A plain (non-tabbed) panel card -- the primary sidebar.
PANEL_BORDER_STYLE = (
    f"border: 1px solid palette(mid); border-radius: {PANEL_RADIUS}px; background-color: palette(base);"
)

# The outer card a tab widget sits inside -- see wrap_tab_widget()'s own docstring for why the
# QTabWidget itself stays borderless/transparent and this wrapper draws the one full box instead.
_TAB_CARD_STYLE = (
    f"QWidget#tabCard {{ border: 1px solid palette(mid); border-radius: {PANEL_RADIUS}px;"
    " background-color: palette(window); }"
)

# Same card, minus its top edge -- for the main panel (see wrap_tab_widget()'s ``flush_top``):
# editor-style tabs (MAIN_TAB_STYLE) already read as flush with whatever's above them, so a border
# line drawn across the top of the card showed up as a stray rule sitting right above the tab row.
_TAB_CARD_STYLE_FLUSH_TOP = (
    "QWidget#tabCard {"
    " border-left: 1px solid palette(mid); border-right: 1px solid palette(mid);"
    " border-bottom: 1px solid palette(mid); border-top: 0px solid transparent;"
    " border-top-left-radius: 0px; border-top-right-radius: 0px;"
    f" border-bottom-left-radius: {PANEL_RADIUS}px; border-bottom-right-radius: {PANEL_RADIUS}px;"
    " background-color: palette(window); }"
)

# Applied to the main panel's QTabWidget once it's inside a wrap_tab_widget() card. Editor-style
# tabs per vs_tabs.png: the tab strip and every unselected tab share the content pane's own
# palette(base) fill, so an unselected tab reads as flush with the main view rather than as a
# distinct bar -- only the selected tab stands out, via an inset palette(alternate-base) "chip"
# (margin top/bottom shrinks it off the strip's own edges, border-radius rounds all four of its
# corners) drawn around its icon/label rather than filling the whole tab cell.
#
# The strip behind the tab row (QTabWidget/QTabBar) is painted with an explicit palette(base)
# background-color rather than "transparent": a transparent QTabBar sitting over an unstyled
# ancestor lets Qt's QSS engine fall back to its own default (light) widget fill for the
# antialiased pixels just outside a rounded QTabBar::tab's corner arc, which showed up as light
# pixels leaking through the tab corners in the dark/Whiley themes. Painting a real color here
# (and setting WA_StyledBackground on the owning widget -- see TabPane) removes the transparent
# layer that caused it.
MAIN_TAB_STYLE = (
    "QTabWidget::pane { border: none; background-color: palette(base);"
    f" border-bottom-left-radius: {PANEL_RADIUS}px; border-bottom-right-radius: {PANEL_RADIUS}px; }}"
    "QTabWidget { border: none; background-color: palette(base); }"
    "QTabBar { background-color: palette(base); }"
    "QTabBar::tab { background-color: transparent; color: palette(window-text);"
    " border: none; margin: 6px 2px; padding: 4px 10px; border-radius: 4px; }"
    "QTabBar::tab:selected { background-color: palette(alternate-base); }"
    "QTabBar::tab:!selected:hover { background-color: palette(alternate-base); }"
    # Qt's native "tear" indicator -- a jagged/torn-paper affordance drawn at the edge where
    # scrolled-off tabs get cut, hinting there's more content that way -- default-renders as a
    # scalloped wavy edge under Fusion. Flattening it to a plain fill removes that artifact; the
    # scroll arrows already communicate "more tabs this way" on their own.
    "QTabBar::tear { background: palette(base); border: none; }"
)

# Applied to the bottom panel's QTabWidget once it's inside a wrap_tab_widget() card. Unlike
# MAIN_TAB_STYLE above, these keep an actual pill-shaped tab: every tab (selected or not) gets
# rounded top corners from the shared base ``::tab`` rule below, and the ``:selected`` rule only
# overrides background/border on top of that -- so an unselected tab reads as a real (if
# unhighlighted) tab rather than a flat square, and the active one reads as raised above the row.
BOTTOM_TAB_STYLE = (
    "QTabWidget::pane { border: none; background-color: palette(base);"
    f" border-bottom-left-radius: {PANEL_RADIUS}px; border-bottom-right-radius: {PANEL_RADIUS}px; }}"
    "QTabWidget { border: none; background-color: palette(window); }"
    "QTabBar { background-color: palette(window); }"
    "QTabBar::tab { background-color: palette(base); color: palette(window-text);"
    " border: 1px solid transparent; padding: 5px 14px; margin-right: 2px;"
    f" border-top-left-radius: {PANEL_RADIUS}px; border-top-right-radius: {PANEL_RADIUS}px; }}"
    "QTabBar::tab:first { margin-left: 4px; }"
    "QTabBar::tab:selected { background-color: palette(highlight); color: palette(window-text);"
    " border: 1px solid palette(mid); border-bottom: none; }"
    "QTabBar::tab:!selected:hover { background-color: palette(alternate-base); }"
)


def wrap_tab_widget(tab_widget: QTabWidget, *, flush_top: bool = False) -> QWidget:
    """Wraps ``tab_widget`` in a rounded, bordered "card" that encloses its tab strip too, not just
    its content pane -- ``QTabWidget``'s own ``::pane`` subcontrol only ever covers the area below
    the tab row, so a border set there alone would leave the tab strip (and any empty space beside
    a short row of tabs) outside the box. ``tab_widget`` should already carry :data:`MAIN_TAB_STYLE`
    or :data:`BOTTOM_TAB_STYLE` (borderless/transparent) before being wrapped here -- this function
    only draws the outer box.

    Pass ``flush_top=True`` (the main panel's own tab panes) to drop the card's top border/corner
    rounding -- see :data:`_TAB_CARD_STYLE_FLUSH_TOP`.
    """
    card = QWidget()
    card.setObjectName("tabCard")
    card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    # Without an explicit autofill, Qt's paint buffer for this widget can start from an
    # uncleared/undefined canvas before the QSS rounded-rect fill is drawn over it, leaving a thin
    # antialiased fringe of that undefined color right on the rounded corners themselves --
    # visible as stray light pixels there regardless of the active theme.
    card.setAutoFillBackground(True)
    card.setStyleSheet(_TAB_CARD_STYLE_FLUSH_TOP if flush_top else _TAB_CARD_STYLE)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    layout.addWidget(tab_widget)
    return card
