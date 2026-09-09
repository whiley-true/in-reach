"""Models for GameVariantDataMultiplayer::scriptContent + related script-defined data: Forge
Labels, Map Permissions, Player Rating Parameters, Required Object Types, Scripted Options,
Scripted Player Traits, Scripted Stats, Scripted HUD Widgets. All 8 are bound in
_reachvarianttool and extracted for real by mide/extraction.py's _extract_script_settings().

Gametype code (the compiled Megalo bytecode itself) is deliberately not modeled here at all --
that's the much deeper Megalo trigger/condition/action AST (README.md Engine Roadmap #3), a
different scope than "the settings a gametype author fills in on a form."
"""
from pydantic import BaseModel, Field

from .enums import ConstTeam, MapPermissionType, ScriptedStatFormat, ScriptedStatSort
from .traits import PlayerTraits


class ForgeLabel(BaseModel):
    """Megalo::ReachForgeLabel (game_variants/components/megalo/forge_label.h),
    ui/script_editor/page_forge_labels.ui."""

    name: str = ""
    requires_object_type: bool = False
    required_object_type: int | None = None  # raw index into Megalo::enums::object_type
    required_object_type_name: str | None = None  # resolved via rvt.object_type_name() -- see extraction.py's _object_type_name()
    requires_assigned_team: bool = False
    required_team: ConstTeam = ConstTeam.none  # Megalo::const_team -- a fixed team slot, not (necessarily) the map's own configured team name
    required_team_name: str | None = None  # the map's actual configured team name for that slot (falls back to "Team N"), or "Neutral"/None -- see extraction.py's _resolve_const_team_name()
    requires_number: bool = False
    required_number: int = 0
    map_must_have_at_least: int = Field(default=0, ge=0, le=127)


class MapPermissions(BaseModel):
    """ReachMapPermissions (game_variants/components/map_permissions.h).

    ``type`` defaults to ``never_these_maps`` (a blacklist with nothing blacklisted, i.e. no
    restriction at all) rather than ``only_these_maps``, matching both RVT's own help text ("the
    usual setup is to use a blacklist that doesn't actually have any maps checked") and what a real
    loaded ``.bin`` with untouched map permissions actually extracts as (confirmed against
    ``blank_mp.bin``). This also matters for a bare ``ScriptSettings()`` -- the fallback
    ``edit_io.write_edit_from_variant`` uses for Firefight, which has no ``MultiplayerData``/map
    permissions of its own -- so Firefight projects don't spuriously read as "allowed on zero maps"
    wherever ``in_reach.app.maps_io.filter_maps_for_gametype`` is applied to them."""

    map_ids: list[int] = Field(default_factory=list, max_length=32)
    type: MapPermissionType = MapPermissionType.never_these_maps


class PlayerRatingParams(BaseModel):
    """ReachPlayerRatingParams (game_variants/components/player_rating_params.h) -- the 15-float
    `values` array, given names from that struct's own `indices` enum instead of staying a bare
    list."""

    rating_scale: float = 1.0
    kill_weight: float = 1.0
    assist_weight: float = 1.0
    betrayal_weight: float = 1.0
    death_weight: float = 0.33
    normalize_by_max_kills: float = 1.0
    base: float = 1000.0
    range: float = 1000.0
    loss_scalar: float = 0.96
    custom_stat_0: float = 0.0
    custom_stat_1: float = 0.0
    custom_stat_2: float = 0.0
    custom_stat_3: float = 0.0
    expansion_0: float = 0.0
    expansion_1: float = 0.0
    show_in_scoreboard: bool = False


class RequiredObjectTypes(BaseModel):
    """ReachGameVariantUsedMPObjectTypeList (formats/bitset.h) -- a
    ReachDwordBasedBitset<Megalo::Limits::max_object_types> on GameVariantDataMultiplayer.
    scriptContent.usedMPObjectTypes. No friendly name list exists for object types anywhere in
    the bindings yet, so this is raw indices only."""

    object_type_indices: list[int] = Field(default_factory=list)
    object_type_names: list[str] = Field(default_factory=list)  # parallel to object_type_indices, resolved via rvt.object_type_name()


class ScriptedOptionValue(BaseModel):
    """ReachMegaloOptionValueEntry (game_variants/components/megalo_options.h)."""

    name: str = ""
    desc: str = ""
    value: int = Field(default=0, ge=-512, le=511)  # cobb::bitnumber<10, int16_t>


class ScriptedOption(BaseModel):
    """ReachMegaloOption (game_variants/components/megalo_options.h) -- a gametype author's
    custom option (e.g. "Zombie Damage Multiplier"), either an enum of named values or a numeric
    range."""

    name: str = ""
    desc: str = ""
    is_range: bool = False
    values: list[ScriptedOptionValue] = Field(default_factory=list)  # enum-mode: the selectable named values
    range_default: ScriptedOptionValue | None = None  # range-mode only
    range_min: ScriptedOptionValue | None = None  # range-mode only
    range_max: ScriptedOptionValue | None = None  # range-mode only
    default_value_index: int = 0  # enum-mode: index into `values`
    range_current: int = 0  # range-mode: current numeric value
    current_value_index: int = 0  # enum-mode: index into `values`


class ScriptedPlayerTraits(BaseModel):
    """ReachMegaloPlayerTraits (game_variants/components/player_traits.h) -- a script-defined,
    named set of player traits (e.g. "Zombie Traits"), reusing the same PlayerTraits shape as the
    built-in trait blocks (see traits.py)."""

    name: str = ""
    desc: str = ""
    traits: PlayerTraits = PlayerTraits()


class ScriptedStat(BaseModel):
    """ReachMegaloGameStat (game_variants/components/megalo_game_stats.h) -- a script-defined
    stat shown on the post-game carnage report."""

    name: str = ""
    format: ScriptedStatFormat = ScriptedStatFormat.number
    sort_order: ScriptedStatSort = ScriptedStatSort.ascending
    group_by_team: bool = False


class ScriptedHUDWidget(BaseModel):
    """Megalo::HUDWidgetDeclaration (game_variants/components/megalo/widgets.h)."""

    position: int = Field(default=0, ge=0, le=11)  # values above 11 are invalid and will cause MCC to fail to load/display the variant


class ScriptSettings(BaseModel):
    """Everything under GameVariantDataMultiplayer::scriptContent + the script-facing top-level
    fields. Gametype code (compiled Megalo bytecode) is deliberately not represented here -- see
    this module's docstring.
    """

    forge_labels: list[ForgeLabel] = Field(default_factory=list)
    map_permissions: MapPermissions = MapPermissions()
    player_rating_params: PlayerRatingParams = PlayerRatingParams()
    required_object_types: RequiredObjectTypes = RequiredObjectTypes()
    scripted_options: list[ScriptedOption] = Field(default_factory=list)
    scripted_player_traits: list[ScriptedPlayerTraits] = Field(default_factory=list)
    scripted_stats: list[ScriptedStat] = Field(default_factory=list)
    scripted_hud_widgets: list[ScriptedHUDWidget] = Field(default_factory=list)
