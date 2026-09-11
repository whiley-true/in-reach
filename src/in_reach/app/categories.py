"""Halo: Reach's own multiplayer gametype "Category" and "Icon" value spaces.

Ported from the v2 prototype's ``app/rvt/models/enums.py`` (``EngineCategory``/``EngineIcon``,
themselves transcribed straight from ReachVariantTool's own combobox setup code -- see that
module's docstring) -- these are fixed, static game data (the same two dropdowns RVT's own
"Metadata" page offers), not anything that needs the native RVT extension or a loaded ``.bin`` to
know, so porting just this enum pair (rather than the pydantic models built on top of them) is
enough to let :mod:`in_reach.app.new_project` offer both fields without that extension.

Category and Icon are a genuinely separate value space in the game itself -- RVT's own two
completely different combobox item lists don't line up (e.g. Icon has "Crosshair"/"Wheel"/"Insane"
entries with no matching Category at all), so picking Icon "Oddball" for a Category "Slayer"
gametype is a real, supported combination, not a mistake. What PROMPT.md asks for is narrower: when
a project's Category *does* have a same-named Icon and the user picked a different one, that's
worth a soft warning (not a hard error) -- see :func:`mismatch_warning`.
"""

from __future__ import annotations

from enum import IntEnum


class EngineCategory(IntEnum):
    """The "Metadata" page's *Category* combobox. ``none`` (Forge/no category) aside, every member
    here also names a same-titled :class:`EngineIcon` member -- see :func:`mismatch_warning`."""

    none = -1
    capture_the_flag = 0
    slayer = 1
    oddball = 2
    king_of_the_hill = 3
    juggernaut = 4
    territories = 5
    assault = 6
    infection = 7
    unknown_vip = 8
    invasion = 9
    stockpile = 10
    race = 12
    headhunter = 13
    action_sack = 16


class EngineIcon(IntEnum):
    """The "Metadata" page's *Icon* combobox -- a superset of :class:`EngineCategory`'s names (the
    gametype categories) plus several purely decorative icons (``crosshair``, ``wheel``, ``insane``,
    ...) that have no corresponding category at all."""

    capture_the_flag = 0
    slayer = 1
    oddball = 2
    king_of_the_hill = 3
    juggernaut = 4
    territories = 5
    assault = 6
    infection = 7
    vip = 8
    invasion = 9
    invasion_slayer = 10
    stockpile = 11
    action_sack = 12
    race_and_rally = 13
    rocket_race = 14
    grifball = 15
    soccer = 16
    headhunter = 17
    crosshair = 18
    wheel = 19
    insane = 20
    bunker = 21
    health = 22
    defend_castle = 23
    arrow_in_box = 24
    infinity = 25
    forerunner_terminal = 26
    eight_ball = 27
    noble_team_insignia = 28
    covenant_insignia = 29
    capture_waypoint = 30


# EngineCategory's own naming diverges from EngineIcon's in exactly two spots -- "unknown_vip"
# (Category) / "vip" (Icon) and "race" (Category) / "race_and_rally" (Icon) both name the same
# real gametype, just spelled differently between the two lists (see each enum's source combobox
# setup code) -- without this, comparing bare member names would flag every VIP/Race project as
# mismatched even when the user picked the obviously-corresponding icon.
_CATEGORY_TO_ICON_NAME = {
    EngineCategory.unknown_vip.name: EngineIcon.vip.name,
    EngineCategory.race.name: EngineIcon.race_and_rally.name,
}

#: PROMPT.md: "one of the categories when creating a new game shows 'Unkown Vip' instead of 'Vip'"
#: -- a plain ``member.name.replace("_", " ").title()`` reads :attr:`EngineCategory.unknown_vip`
#: as "Unknown Vip"; this member-specific override is what :func:`display_name` checks first.
_DISPLAY_NAME_OVERRIDES = {
    EngineCategory.unknown_vip.name: "Vip",
}


def display_name(member: EngineCategory | EngineIcon) -> str:
    """A human-readable label for a category/icon enum member, e.g. ``king_of_the_hill`` ->
    ``"King Of The Hill"``."""
    if isinstance(member, EngineCategory) and member is EngineCategory.none:
        return "None (Forge)"
    override = _DISPLAY_NAME_OVERRIDES.get(member.name)
    if override is not None:
        return override
    return member.name.replace("_", " ").title()


def default_icon_for(category: EngineCategory) -> EngineIcon | None:
    """The icon that corresponds to ``category``, if any -- what a category picker should
    pre-select the icon dropdown to, so the two start out matched rather than defaulting to
    whatever the icon combobox's own first entry happens to be.

    Returns:
        ``None`` for :attr:`EngineCategory.none` -- there's no icon to default to.
    """
    if category is EngineCategory.none:
        return None
    return EngineIcon[_CATEGORY_TO_ICON_NAME.get(category.name, category.name)]


def mismatch_warning(category: EngineCategory, icon: EngineIcon) -> str | None:
    """Reports whether ``icon`` doesn't correspond to ``category`` -- a soft warning, not something
    that should block project creation (see this module's own docstring for why the two are a
    legitimately independent choice in the game itself).

    Args:
        category: The project's chosen :class:`EngineCategory`.
        icon: The project's chosen :class:`EngineIcon`.

    Returns:
        ``None`` if ``category`` is :attr:`EngineCategory.none` (nothing to match against) or
        ``icon`` is the one that corresponds to it. Otherwise a message naming both, for the caller
        to show the user.
    """
    if category is EngineCategory.none:
        return None
    expected_icon_name = _CATEGORY_TO_ICON_NAME.get(category.name, category.name)
    if icon.name == expected_icon_name:
        return None
    return (
        f"Category \"{display_name(category)}\" usually pairs with icon "
        f"\"{display_name(EngineIcon[expected_icon_name])}\", not \"{display_name(icon)}\"."
    )
