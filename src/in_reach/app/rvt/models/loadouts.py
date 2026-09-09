"""ReachLoadout / ReachLoadoutPalette (game_variants/components/loadouts.h), edited on
ui/main_window/page_loadout_palette.ui + ui/widgets/LoadoutForm.ui.
"""
from pydantic import BaseModel, Field

from .enums import Ability, LoadoutPaletteTier, Weapon


class Loadout(BaseModel):
    visible: bool = False
    name_index: int = Field(default=-1, ge=-1, le=80)  # index into an 82-entry preset flavor-name list (Noble Team, Spartan-IIs, callsigns, ...) hardcoded in ui/widgets/LoadoutForm.ui's loadoutName combobox; -1 = "[No Name]". Flavor text only, not reproduced here as an enum -- see that file for the full list.
    weapon_primary: Weapon = Weapon.unchanged
    weapon_secondary: Weapon = Weapon.unchanged
    ability: Ability = Ability.unchanged
    grenade_count: int = Field(default=0, ge=0, le=15)  # plain 4-bit count -- NOT the PlayerTraits.offense.grenade_count enum, despite the shared name


class LoadoutPalette(BaseModel):
    tier: LoadoutPaletteTier
    loadouts: list[Loadout] = Field(default_factory=lambda: [Loadout() for _ in range(5)], min_length=5, max_length=5)
