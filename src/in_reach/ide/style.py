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

# Applied to a QTabWidget once it's inside a wrap_tab_widget() card: the content pane fills with
# palette(base) (rounded only on the bottom, so it reads as continuous with the tab strip above
# it), an unselected tab matches that same shade so it reads as a real tab rather than blending
# into the chrome, and the selected tab gets a permanent highlight background with rounded top
# corners so it reads as raised above the row.
#
# The strip behind the tab row (QTabWidget/QTabBar) is painted with an explicit palette(window)
# background-color rather than "transparent": a transparent QTabBar sitting over an unstyled
# ancestor lets Qt's QSS engine fall back to its own default (light) widget fill for the
# antialiased pixels just outside a rounded QTabBar::tab's corner arc, which showed up as light
# pixels leaking through the tab corners in the dark/Whiley themes. Painting a real color here
# (and setting WA_StyledBackground on the owning widget -- see TabPane/BottomPanel) removes the
# transparent layer that caused it.
TAB_PANEL_BORDER_STYLE = (
    "QTabWidget::pane { border: none; background-color: palette(base);"
    f" border-bottom-left-radius: {PANEL_RADIUS}px; border-bottom-right-radius: {PANEL_RADIUS}px; }}"
    "QTabWidget { border: none; background-color: palette(window); }"
    "QTabBar { background-color: palette(window); }"
    "QTabBar::tab { background-color: palette(base); color: palette(window-text);"
    " border: 1px solid transparent; padding: 5px 14px; margin-right: 2px; }"
    "QTabBar::tab:first { margin-left: 4px; }"
    "QTabBar::tab:selected { background-color: palette(highlight); color: palette(window-text);"
    " border: 1px solid palette(mid); border-bottom: none;"
    f" border-top-left-radius: {PANEL_RADIUS}px; border-top-right-radius: {PANEL_RADIUS}px; }}"
    "QTabBar::tab:!selected:hover { background-color: palette(alternate-base); }"
)


def wrap_tab_widget(tab_widget: QTabWidget) -> QWidget:
    """Wraps ``tab_widget`` in a rounded, bordered "card" that encloses its tab strip too, not just
    its content pane -- ``QTabWidget``'s own ``::pane`` subcontrol only ever covers the area below
    the tab row, so a border set there alone would leave the tab strip (and any empty space beside
    a short row of tabs) outside the box. ``tab_widget`` should already carry
    :data:`TAB_PANEL_BORDER_STYLE` (borderless/transparent) before being wrapped here -- this
    function only draws the outer box.
    """
    card = QWidget()
    card.setObjectName("tabCard")
    card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    card.setStyleSheet(_TAB_CARD_STYLE)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    layout.addWidget(tab_widget)
    return card
