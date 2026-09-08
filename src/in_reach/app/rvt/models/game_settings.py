"""GameSettings -- the pydantic API standard for a game variant's settings.

Top level is exactly three sections: `meta` (lightweight file-level identity, always present
regardless of variant type), `multiplayer` (everything from GameVariantDataMultiplayer, split
into `game_settings` -- the settings tree proper -- and `script_settings`, see script_settings.py),
and `firefight` (GameVariantDataFirefight -- first pass, see the Firefight class's own docstring
for what's covered and what isn't yet).

This is the runtime source of truth for shape and allowed values -- an earlier pass kept a
hand-written, comment-annotated yaml schema (game.yml/game.schema.yml under mide/index/) alongside
this one for cross-reference; that's since been removed, so this module's own field comments are
the only record of that provenance (which .ui file, which C++ header) now.

mide/extraction.py builds a GameSettings from a loaded _reachvarianttool GameVariant.
mide/settings_io.py dumps/loads a GameSettings to/from game/settings.json (one of the files inside a
.mide project directory, see mide/project.py).
"""
from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_serializer, model_validator

from in_reach.app.categories import EngineCategory as ProjectCategory
from in_reach.app.categories import EngineIcon as ProjectIcon

from .enums import (
    AIGrenades,
    AIHearing,
    AILuck,
    AIShootiness,
    AIVision,
    BoolTrait,
    DamageMultiplier,
    DamageResist,
    EngineCategory,
    EngineIcon,
    FirefightSkull,
    FirefightSquad,
    LoadoutPaletteTier,
    TeamDesignatorSwitchType,
    TeamScoringMode,
    VehicleSet,
    WeaponSet,
)
from .loadouts import LoadoutPalette
from .script_settings import ScriptSettings
from .teams import Team
from .traits import PlayerTraits

_EPOCH = datetime.fromtimestamp(0, tz=timezone.utc)


# ---- meta / metadata ----------------------------------------------------------------------


class Meta(BaseModel):
    """Lightweight, always-present file-level identity -- not a GUI page, just what's needed to
    know what a game/settings.json even *is* before looking at anything else in it.

    is_multiplayer determines which of GameSettings.multiplayer/firefight is present at all (see
    that class's own model_validator) -- it's effectively not user-changeable in practice (a
    project's underlying .bin is whatever type it already is; POST /active/{uuid}/settings errors
    if a posted is_multiplayer disagrees with the target project's real one, see
    mide.commands.save_settings_json()'s docstring), but it stays a plain, always-present field
    here rather than being dropped from the schema -- deliberately, so a client can round-trip a
    whole settings.json (e.g. copy one GET response straight into a later POST body) without
    having to strip this field out first."""

    is_forge: bool = False
    is_multiplayer: bool = True
    symmetric: bool = False  # GameVariantDataMultiplayer::symmetric -- no GUI widget for this field anywhere in RVT, only meaningful when is_multiplayer
    title: str = ""  # MultiplayerData.variant_header.title (ui/main_window/page_multiplayer_metadata.ui) -- the REAL title shown in-game/in MCC menus; empty when not is_multiplayer (Firefight has no equivalent header of its own -- falls back to GameVariant.content_header.title)
    description: str = Field(default="", max_length=127)  # MultiplayerData.variant_header.description, same page/header as title above -- NOT Metadata.description below, which is a different field entirely (see that class's docstring); falls back to GameVariant.content_header.description when not is_multiplayer, same as title
    source_file: str
    generated_at: datetime
    # PROMPT.md: "we can get rid of user_settings.json ad move category and category_icon into
    # settings.json" -- this project's own in_reach.app.categories classification (chosen in the
    # New Project dialog), NOT the engine's own Metadata.engine_category/categorization_icon below
    # -- those two can legitimately disagree (a blank project's source .bin has no real category of
    # its own baked in at all; this project's own choice is independent either way).
    category: ProjectCategory = ProjectCategory.none
    category_icon: ProjectIcon | None = None

    @field_serializer("category")
    def _serialize_category(self, value: ProjectCategory) -> str:
        return value.name

    @field_serializer("category_icon")
    def _serialize_category_icon(self, value: ProjectIcon | None) -> str | None:
        return value.name if value is not None else None


class Metadata(BaseModel):
    """ui/main_window/page_multiplayer_metadata.ui's *other* real GUI-page fields (title/
    description live on Meta above instead, since they're useful even outside this deep-dive
    section -- categorization_icon/engine_category/author/created_at/editor/edited_at come from
    the same page but stayed here) -- plus ui/script_editor/page_metadata_strings.ui's separate
    localized description_string/category, a DIFFERENT page entirely.

    description_string/category come from localizedDesc/localizedCategory
    (GameVariantDataMultiplayer) -- edited on the Script Editor window's separate "Metadata
    Strings" page, NOT the main Metadata page (do not confuse Metadata.description_string here with
    Meta.description above -- they are two independent engine fields that can hold completely
    different content. Confirmed against a real built-in variant (ASSAULT): Meta.description
    (variant_header) held the internal localization placeholder key "$hr_gvar_Assault_desc", while
    Metadata.description_string (localizedDesc) held the real, human-readable text players actually
    see, "Retrieve the bomb, arm it in your opponent's base, and then protect it until it
    detonates." -- description_string, not Meta.description, is the one to edit for a gametype's
    actual description). categorization_icon/engine_category/author/created_at/editor/edited_at all
    come from the main Metadata page. categorization_icon/engine_category are each stored in *two*
    places in the engine (GameVariantDataMultiplayer.engineIcon/engineCategory directly, and a
    duplicate copy nested in variant_header) that RVT's own GUI always keeps in sync when writing --
    see mide.settings_writer.apply_multiplayer_settings()'s docstring for why both need writing.

    There is deliberately no `name` field (localizedName) here anymore -- confirmed empirically
    across real .bin files that it's never actually populated (always empty), unlike
    description_string/category, so it was dropped from this model entirely rather than kept as a
    permanently-blank field. localizedName is still readable/writable directly via the lower-level
    POST /active/{uuid}/strings path (mide.models.strings.StringsMeta.name) if it ever turns out to
    matter for some file this assumption doesn't hold for.
    """

    description_string: str = Field(default="", max_length=127)
    category: str = ""
    categorization_icon: EngineIcon | None = None
    engine_category: EngineCategory | None = None
    author: str = ""
    created_at: datetime = _EPOCH
    editor: str = ""
    edited_at: datetime = _EPOCH


# ---- multiplayer.game_settings ---------------------------------------------------------------


class GeneralSettings(BaseModel):
    """ui/main_window/page_multiplayer_settings_general.ui"""

    perfection_enabled: bool = False
    new_round_resets_players: bool = False  # checkbox label says "(unused)" in the .ui file itself
    new_round_resets_map: bool = False  # checkbox label says "(unused)" in the .ui file itself
    teams_enabled: bool = False
    fireteams_enabled: bool = False
    player_species: int = Field(default=0, ge=0, le=4)  # 0=Player Preference, 1=All Spartans, 2=All Elites, 3=Use Team Species, 4=Spartans vs Elites -- combobox lives on this page but is backed by TeamOptions.species, not GeneralOptions; no registered py::enum_
    time_limit: int = Field(default=0, ge=0, le=255)
    round_limit: int = Field(default=0, ge=0, le=31)
    rounds_to_win: int = Field(default=0, ge=0, le=15)
    sudden_death_time: int = Field(default=0, ge=-1, le=126)
    grace_period: int = Field(default=1, ge=0, le=31)  # the .ui spinbox itself won't let you type below 1, but real files can and do contain 0 -- the bit field allows it even if the editor's input widget doesn't
    score_to_win: int = Field(default=0, ge=0, le=65535)


class RespawnSettings(BaseModel):
    """ui/main_window/page_multiplayer_settings_respawn.ui"""

    sync_with_team: bool = False  # code comment: "testing confirms this does nothing"
    respawn_with_teammate: bool = False  # checkbox label says "(unverified)" in the .ui file itself
    respawn_at_location: bool = False  # checkbox label says "(unverified)" in the .ui file itself
    respawn_on_kills: bool = False
    lives_per_round: int = Field(default=0, ge=0, le=63)
    team_lives_per_round: int = Field(default=0, ge=0, le=127)
    respawn_time: int = Field(default=0, ge=0, le=255)  # editor raises min to 3 at runtime for Firefight variants specifically -- not representable as a single static range
    suicide_penalty: int = Field(default=0, ge=0, le=255)
    betrayal_penalty: int = Field(default=0, ge=0, le=255)
    respawn_growth: int = Field(default=0, ge=0, le=15)
    loadout_cam_time: int = Field(default=0, ge=0, le=15)
    traits_duration: int = Field(default=0, ge=0, le=63)
    traits: PlayerTraits = PlayerTraits()  # "Respawn Traits" nav child


class SocialSettings(BaseModel):
    """ui/main_window/page_multiplayer_settings_social.ui"""

    observers: bool = False
    team_changes: int = Field(default=0, ge=0, le=2)  # 0=Disabled, 1=Enabled, 2=Balancing Only -- no registered py::enum_
    friendly_fire: bool = False
    betrayal_booting: bool = False
    proximity_voice: bool = False
    global_voice: bool = False  # .ui label is "Don't Team-Restrict Voice Chat" -- true means voice is NOT team-restricted
    dead_player_voice: bool = False


class MapAndGameSettings(BaseModel):
    """ui/main_window/page_multiplayer_settings_map.ui"""

    grenades: bool = False
    shortcuts: bool = False
    abilities: bool = False
    powerups: bool = False
    turrets: bool = False
    indestructible_vehicles: bool = False
    weapon_set: WeaponSet = WeaponSet.map_default
    vehicle_set: VehicleSet = VehicleSet.map_default
    powerup_duration_red: int = Field(default=0, ge=0, le=120)
    powerup_duration_blue: int = Field(default=0, ge=0, le=120)
    powerup_duration_yellow: int = Field(default=0, ge=0, le=120)
    base_traits: PlayerTraits = PlayerTraits()  # "Base Player Traits" nav child
    powerup_red_traits: PlayerTraits = PlayerTraits()  # "Red Powerup Traits" nav child
    powerup_blue_traits: PlayerTraits = PlayerTraits()  # "Blue Powerup Traits" nav child
    powerup_yellow_traits: PlayerTraits = PlayerTraits()  # "Yellow Powerup Traits" nav child


class TeamSettings(BaseModel):
    """ui/main_window/page_multiplayer_settings_team.ui (overall) +
    page_multiplayer_settings_team_specific.ui (per team)"""

    scoring_method: TeamScoringMode = TeamScoringMode.sum
    switch_type: TeamDesignatorSwitchType = TeamDesignatorSwitchType.none
    teams: list[Team] = Field(default_factory=lambda: [Team(index=i) for i in range(8)], min_length=8, max_length=8)  # ReachCGTeamOptions::teams is a fixed 8-entry array


class LoadoutSettings(BaseModel):
    """ui/main_window/page_multiplayer_settings_loadout.ui (overall) + page_loadout_palette.ui
    (per palette) + ui/widgets/LoadoutForm.ui (per loadout)"""

    spartan_loadouts_enabled: bool = False
    elite_loadouts_enabled: bool = False
    palettes: list[LoadoutPalette] = Field(
        default_factory=lambda: [LoadoutPalette(tier=tier) for tier in LoadoutPaletteTier],
        min_length=6,
        max_length=6,
    )  # 3 Spartan + 3 Elite tiers, interleaved in storage (see reach::loadout_palette's own comment)


class OptionVisibility(BaseModel):
    """ui/main_window.ui, PageOptionToggles (MegaloOptionToggleTree widget).

    Bound as raw set-bit indices into the 4 underlying flag lists (GameVariantDataMultiplayer::
    optionToggles.{engine,megalo}.{disabled,hidden}) -- the mechanic itself (which index maps to
    which named option, and what exactly "disabled" vs "hidden" mean here) is still not fully
    understood, so there's no friendly field-per-option model yet, just the raw indices the engine
    actually stores.
    """

    engine_options_disabled: list[int] = Field(default_factory=list)  # 1273-bit list, one per built-in engine option
    engine_options_hidden: list[int] = Field(default_factory=list)
    megalo_options_disabled: list[int] = Field(default_factory=list)  # 16-bit list, indexes into scripted_options
    megalo_options_hidden: list[int] = Field(default_factory=list)


class TitleUpdateSettings(BaseModel):
    """ui/main_window/page_multiplayer_title_update_1.ui"""

    bleedthrough: bool = False
    armor_lock_cant_shed_stickies: bool = False
    armor_lock_can_be_stuck: bool = False
    enable_active_camo_modifiers: bool = False
    limit_sword_block_to_sword: bool = False
    enable_automatic_magnum: bool = False
    precision_bloom: float = Field(default=100.0, ge=0.0, le=200.0)  # UI field is a percentage (0-200); stored internally as a 0.0-2.0 fraction
    armor_lock_damage_drain: float = Field(default=0.0, ge=0.0, le=2.0)  # a drain rate, confirmed cannot go negative
    armor_lock_damage_drain_limit: float = Field(default=0.0, ge=0.0, le=2.0)  # same reasoning as armor_lock_damage_drain
    active_camo_energy_curve_min: float = Field(default=0.0, ge=0.0, le=2.0)  # an energy-curve value, confirmed cannot go negative
    active_camo_energy_curve_max: float = Field(default=0.0, ge=0.0, le=2.0)  # same reasoning as active_camo_energy_curve_min
    magnum_damage: float = Field(default=0.0, ge=0.0, le=10.0)  # .ui sets no explicit minimum; assumed 0.0 (QDoubleSpinBox default), not confirmed against engine bounds
    magnum_fire_delay: float = Field(default=0.0, ge=0.0, le=10.0)  # same minimum caveat as magnum_damage
    # apply_official_settings is deliberately not a field here: it's the Vanilla/TU/Anniversary/
    # Zero-Bloom preset-apply action (ReachGameVariantTU1Options::make_vanilla() etc.), an
    # operation, not a stored value -- to be mapped later as a command, not a settings field.


class MultiplayerGameSettings(BaseModel):
    """Everything extractable from GameVariantDataMultiplayer today, flattened directly under
    multiplayer.game_settings (see game_settings.py's module docstring for the section layout)."""

    metadata: Metadata = Metadata()
    general_settings: GeneralSettings = GeneralSettings()
    respawn_settings: RespawnSettings = RespawnSettings()
    social_settings: SocialSettings = SocialSettings()
    map_and_game_settings: MapAndGameSettings = MapAndGameSettings()
    team_settings: TeamSettings = TeamSettings()
    loadout_settings: LoadoutSettings = LoadoutSettings()
    option_visibility: OptionVisibility = OptionVisibility()
    title_update_settings: TitleUpdateSettings = TitleUpdateSettings()


class Multiplayer(BaseModel):
    game_settings: MultiplayerGameSettings = MultiplayerGameSettings()
    script_settings: ScriptSettings = ScriptSettings()


# ---- firefight -------------------------------------------------------------------------------


class FirefightWaveTraits(BaseModel):
    """ReachFirefightWaveTraits (game_variants/components/firefight_wave_traits.h) -- per-wave AI
    behavior modifiers, distinct from ReachPlayerTraits (which governs the human players)."""

    vision: AIVision = AIVision.unchanged
    hearing: AIHearing = AIHearing.unchanged
    luck: AILuck = AILuck.unchanged
    shootiness: AIShootiness = AIShootiness.unchanged
    grenades: AIGrenades = AIGrenades.unchanged
    dont_drop_equipment: BoolTrait = BoolTrait.unchanged
    assassin_immunity: BoolTrait = BoolTrait.unchanged
    headshot_immunity: BoolTrait = BoolTrait.unchanged
    damage_resist: DamageResist = DamageResist.unchanged
    damage_mult: DamageMultiplier = DamageMultiplier.unchanged


class FirefightGeneralSettings(BaseModel):
    """Same as GeneralSettings, minus fireteams_enabled/score_to_win -- both of those are sourced
    from GameVariantDataMultiplayer directly (see extraction.py's _extract_general()), not from
    ReachCustomGameOptions.general, so they don't exist for a Firefight variant's options tree."""

    perfection_enabled: bool = False
    new_round_resets_players: bool = False
    new_round_resets_map: bool = False
    teams_enabled: bool = False
    player_species: int = Field(default=0, ge=0, le=4)
    time_limit: int = Field(default=0, ge=0, le=255)
    round_limit: int = Field(default=0, ge=0, le=31)
    rounds_to_win: int = Field(default=0, ge=0, le=15)
    sudden_death_time: int = Field(default=0, ge=-1, le=126)
    grace_period: int = Field(default=1, ge=0, le=31)


class FirefightGameSettings(BaseModel):
    """Firefight's own ReachCustomGameOptions tree (FirefightData.options) -- same C++ type and
    shape as multiplayer.game_settings, minus metadata/option_visibility/title_update_settings
    (all sourced from GameVariantDataMultiplayer, which Firefight variants don't have) and with
    FirefightGeneralSettings instead of GeneralSettings (see that model's docstring)."""

    general_settings: FirefightGeneralSettings = FirefightGeneralSettings()
    respawn_settings: RespawnSettings = RespawnSettings()
    social_settings: SocialSettings = SocialSettings()
    map_and_game_settings: MapAndGameSettings = MapAndGameSettings()
    team_settings: TeamSettings = TeamSettings()
    loadout_settings: LoadoutSettings = LoadoutSettings()


class FirefightSkullSet(BaseModel):
    """A skull_list_t bitset (ReachFirefightRound::skulls, GameVariantDataFirefight::
    bonusWaveSkulls) -- one bool per reach::firefight_skull member."""

    iron: bool = False
    black_eye: bool = False
    tough_luck: bool = False
    catch_: bool = False
    fog: bool = False
    famine: bool = False
    thunderstorm: bool = False
    tilt: bool = False
    mythic: bool = False
    assassin: bool = False
    blind: bool = False
    cowbell: bool = False
    grunt_birthday_party: bool = False
    iwhbyd: bool = False
    red: bool = False
    yellow: bool = False
    blue: bool = False


class FirefightWave(BaseModel):
    """ReachFirefightWave (game_variants/components/firefight_round.h) -- one of a Round's
    Initial/Main/Boss wave configurations."""

    uses_dropship: bool = False
    ordered_squads: bool = False
    squad_count: int = Field(default=0, ge=0, le=15)
    squads: list[FirefightSquad] = Field(default_factory=lambda: [FirefightSquad.none] * 12, min_length=12, max_length=12)


class FirefightRound(BaseModel):
    """ReachFirefightRound -- a Firefight Set is 3 of these (rounds[3]) plus a bonus wave; each
    Round is 5 Waves (1 Initial + 3 Main + 1 Boss), see firefight_round.h's file comment."""

    skulls: FirefightSkullSet = FirefightSkullSet()
    wave_initial: FirefightWave = FirefightWave()
    wave_main: FirefightWave = FirefightWave()
    wave_boss: FirefightWave = FirefightWave()


class FirefightCustomSkull(BaseModel):
    """ReachFirefightCustomSkull -- one of the 3 (red/yellow/blue) map-selectable custom skulls,
    each with its own player traits and wave AI traits."""

    traits_spartan: PlayerTraits = PlayerTraits()
    traits_elite: PlayerTraits = PlayerTraits()
    traits_wave: FirefightWaveTraits = FirefightWaveTraits()


class Firefight(BaseModel):
    """GameVariantDataFirefight (game_variants/types/firefight.h). Covers the scenario-level
    scalars, the trait/respawn/header sub-structures that are straightforward reuses of types
    already bound for Multiplayer (ReachPlayerTraits, ReachCGRespawnOptions, ReachUGCHeader all
    being the exact same C++ types there and here), Firefight's own ReachCustomGameOptions tree
    (`options`), and the per-round wave/squad configuration, custom skulls, and bonus wave.
    """

    hazards_enabled: bool = False
    all_generators_must_survive: bool = False
    random_generator_spawns: bool = False
    weapon_drops_enabled: bool = False
    ammo_crates_enabled: bool = False
    wave_limit: int = Field(default=0, ge=0, le=255)  # see GameVariantDataFirefight::predefined_wave_limit_values for common presets: 0=no limit, 1=one wave, 5=one round, 16=one set (15 waves + bonus), 32=two sets, ...
    bonus_target: int = Field(default=10000, ge=0, le=32767)  # points; "always 10000?" per the engine source's own comment
    elite_kill_bonus: int = Field(default=0, ge=0, le=32767)
    starting_lives_spartan: int = Field(default=0, ge=-63, le=63)
    starting_lives_elite: int = Field(default=0, ge=-63, le=63)
    max_spartan_extra_lives: int = Field(default=0, ge=-63, le=63)
    generator_count: int = Field(default=0, ge=0, le=3)
    bonus_wave_duration: int = Field(default=0, ge=0, le=4095)  # seconds
    base_traits_spartan: PlayerTraits = PlayerTraits()
    base_traits_elite: PlayerTraits = PlayerTraits()
    base_traits_wave: FirefightWaveTraits = FirefightWaveTraits()
    elite_respawn_options: RespawnSettings = RespawnSettings()  # ReachCGRespawnOptions -- same type/shape as multiplayer.game_settings.respawn_settings
    options: FirefightGameSettings = FirefightGameSettings()
    custom_skulls: list[FirefightCustomSkull] = Field(default_factory=lambda: [FirefightCustomSkull() for _ in range(3)], min_length=3, max_length=3)  # index 0/1/2 = red/yellow/blue, see GameVariantDataFirefight::custom_skull
    rounds: list[FirefightRound] = Field(default_factory=lambda: [FirefightRound() for _ in range(3)], min_length=3, max_length=3)
    bonus_wave: FirefightWave = FirefightWave()
    bonus_wave_skulls: FirefightSkullSet = FirefightSkullSet()


# ---- top level --------------------------------------------------------------------------------


class GameSettings(BaseModel):
    """The full settings tree for one game variant. This is what a Project's game/settings.json
    holds (see mide/project.py).

    multiplayer/firefight are mutually exclusive, enforced below: a multiplayer variant
    (meta.is_multiplayer true) never carries a `firefight` section, and a Firefight variant
    (meta.is_multiplayer false) never carries a `multiplayer` one -- whichever doesn't apply is
    always None, regardless of what a client posts, rather than a meaningless all-defaults object
    sitting there unused. The relevant section is auto-defaulted if omitted, so a minimal
    `{"meta": {...}}` body (or one that already has the right section filled in) still validates.
    """

    meta: Meta
    multiplayer: Multiplayer | None = None
    firefight: Firefight | None = None

    @model_validator(mode="after")
    def _enforce_multiplayer_firefight_exclusivity(self) -> "GameSettings":
        if self.meta.is_multiplayer:
            if self.multiplayer is None:
                self.multiplayer = Multiplayer()
            self.firefight = None
        else:
            if self.firefight is None:
                self.firefight = Firefight()
            self.multiplayer = None
        return self
