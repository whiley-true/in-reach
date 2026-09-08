"""Python-native mirrors of the reach:: enums used by GameSettings.

These are deliberately independent of _reachvarianttool's pybind11 enum objects: GameSettings
(and everything under mide/models/) must be constructible and validate-able without the native
extension loaded at all -- e.g. for a future "open a .mide file and inspect it" workflow that
never touches a .bin file. mide/extraction.py is the only place that bridges the two, converting
raw ints read off the pybind11 objects into these enums.

Each enum's value list and member names come from the corresponding C++ definition (see the
comment above each class) -- this file is the runtime source of truth for shape and allowed
values. An earlier pass kept a hand-written, heavily-annotated yaml schema (provenance comments,
GUI widget names, flagged uncertainties) alongside this one for cross-reference; that's since been
removed, so this module's own comments are the only record of that provenance now.
"""
from enum import Enum


class StrEnum(str, Enum):
    """Base for enums that should serialize as their plain name in YAML/JSON."""

    def __str__(self) -> str:
        return self.value


# ---- game_variants/components/custom_game_options.h ------------------------------------------


class WeaponSet(StrEnum):
    map_default = "map_default"
    human = "human"
    covenant = "covenant"
    no_snipers = "no_snipers"
    rocket_launchers = "rocket_launchers"
    no_power_weapons = "no_power_weapons"
    juggernaut = "juggernaut"
    slayer_pro = "slayer_pro"
    rifles_only = "rifles_only"
    mid_range_only = "mid_range_only"
    long_range_only = "long_range_only"
    sniper_rifles = "sniper_rifles"
    melee = "melee"
    energy_swords = "energy_swords"
    gravity_hammers = "gravity_hammers"
    mass_destruction = "mass_destruction"
    none = "none"
    random = "random"


class VehicleSet(StrEnum):
    map_default = "map_default"
    mongooses = "mongooses"
    warthogs = "warthogs"
    no_aircraft = "no_aircraft"
    only_aircraft = "only_aircraft"
    no_tanks = "no_tanks"
    only_tanks = "only_tanks"
    no_light_ground = "no_light_ground"
    only_light_ground = "only_light_ground"
    no_covenant = "no_covenant"
    all_covenant = "all_covenant"
    no_human = "no_human"
    all_human = "all_human"
    none = "none"
    all = "all"


class TeamScoringMode(StrEnum):
    sum = "sum"
    minimum = "minimum"
    maximum = "maximum"
    # NOTE: the GUI combobox (page_multiplayer_settings_team.ui) has a 4th item, "Unknown 3"
    # (index 3), with no corresponding value in bindings.cpp's registered TeamScoringMode enum.


class TeamDesignatorSwitchType(StrEnum):
    none = "none"
    random = "random"
    rotate = "rotate"


# ---- formats/ugc_header.h, ui/widgets/GametypeIconCombobox.cpp ---------------------------------


class EngineIcon(int, Enum):
    """The "Metadata" page's icon picker (ui/main_window/page_multiplayer_metadata.ui,
    GametypeIconCombobox). Not a reach:: C++ enum -- there's no named type for this field in the
    engine, just a raw cobb::bitnumber<8, uint32_t> -- but unlike the genuinely-uncertain unbound
    combobox fields elsewhere (player_species, team_changes, ...), this list is a complete,
    engine-source-derived transcription (GametypeIconCombobox.cpp's `_icons` array) rather than a
    guess, so it gets a real named enum per the prompt that added this field.
    """

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
    infinity = 25  # was "Shapes" pre-MCC; MCC-era icon is what's registered here
    forerunner_terminal = 26
    eight_ball = 27
    noble_team_insignia = 28
    covenant_insignia = 29
    capture_waypoint = 30


class EngineCategory(int, Enum):
    """The "Metadata" page's *Category* combobox (ui/main_window/page_multiplayer_metadata.ui,
    ui.engineCategory) -- a completely separate field/value-space from EngineIcon above (same
    underlying storage shape, cobb::bitnumber<8, int8_t>, but the two combobox item lists don't
    match at all: e.g. raw value 11 is EngineIcon's "stockpile" but EngineCategory's "lumped into
    Action Sack, not independently selectable"). Transcribed directly from
    page_multiplayer_metadata.cpp's own combobox setup code -- category indices 11/14/15 are
    deliberately excluded (the constructor's own comments: "MCC lumps category #11 in with Action
    Sack" / "MCC does not display category #14/#15"), so raw values in that range can exist on a
    real file (esp. one from Xbox 360-era Reach) but aren't a selectable combobox item and have no
    member here.
    """

    none = -1  # "Forge / None"
    capture_the_flag = 0
    slayer = 1
    oddball = 2
    king_of_the_hill = 3
    juggernaut = 4
    territories = 5
    assault = 6
    infection = 7
    unknown_vip = 8  # "Unknown/Blank (VIP?)"
    invasion = 9
    stockpile = 10
    race = 12
    headhunter = 13
    action_sack = 16


# ---- game_variants/components/map_permissions.h -----------------------------------------------


class MapPermissionType(StrEnum):
    only_these_maps = "only_these_maps"
    never_these_maps = "never_these_maps"


# ---- game_variants/components/megalo_game_stats.h ----------------------------------------------


class ScriptedStatFormat(StrEnum):
    number = "number"
    number_with_sign = "number_with_sign"
    percentage = "percentage"
    time = "time"


class ScriptedStatSort(StrEnum):
    ascending = "ascending"
    ignored = "ignored"
    descending = "descending"
    obsolete_2 = "obsolete_2"


# ---- game_variants/components/firefight_wave_traits.h ------------------------------------------


class AIVision(StrEnum):
    unchanged = "unchanged"
    normal = "normal"
    blind = "blind"  # "not in UI" per the engine source comment
    nearsighted = "nearsighted"
    eagle_eye = "eagle_eye"


class AIHearing(StrEnum):
    unchanged = "unchanged"
    normal = "normal"
    deaf = "deaf"
    sharp = "sharp"  # hearing range doubled


class AILuck(StrEnum):
    unchanged = "unchanged"
    normal = "normal"
    unlucky = "unlucky"
    lucky = "lucky"
    leprechaun = "leprechaun"


class AIShootiness(StrEnum):
    unchanged = "unchanged"
    normal = "normal"
    marksman = "marksman"
    trigger_happy = "trigger_happy"


class AIGrenades(StrEnum):
    unchanged = "unchanged"
    normal = "normal"
    none = "none"
    catch_skull = "catch_skull"


# ---- game_variants/components/firefight_round.h, namespace reach -------------------------------


class FirefightSkull(StrEnum):
    iron = "iron"
    black_eye = "black_eye"
    tough_luck = "tough_luck"
    catch_ = "catch_"  # trailing underscore in the C++ enum too, to avoid the `catch` keyword
    fog = "fog"
    famine = "famine"
    thunderstorm = "thunderstorm"
    tilt = "tilt"
    mythic = "mythic"
    assassin = "assassin"  # internal name
    blind = "blind"
    cowbell = "cowbell"  # "superman" internally
    grunt_birthday_party = "grunt_birthday_party"
    iwhbyd = "iwhbyd"
    red = "red"
    yellow = "yellow"
    blue = "blue"


class FirefightSquad(StrEnum):
    """Which squad type a Firefight wave spawns -- see firefight_round.h's file comment for how
    Initial/Main/Boss waves and Rounds/Sets fit together."""

    none = "none"
    brutes = "brutes"
    brute_kill_team = "brute_kill_team"
    brute_patrol = "brute_patrol"
    brute_infantry = "brute_infantry"
    brute_tactical = "brute_tactical"
    brute_chieftains = "brute_chieftains"
    elites = "elites"
    elite_patrol = "elite_patrol"
    elite_infantry = "elite_infantry"
    elite_airborne = "elite_airborne"
    elite_tactical = "elite_tactical"
    elite_spec_ops = "elite_spec_ops"
    engineers = "engineers"  # a single Engineer (not in UI)
    elite_generals = "elite_generals"
    grunts = "grunts"
    hunter_kill_team = "hunter_kill_team"
    hunter_patrol = "hunter_patrol"
    hunter_strike_team = "hunter_strike_team"
    jackal_patrol = "jackal_patrol"
    elite_strike_team = "elite_strike_team"
    skirmisher_patrol = "skirmisher_patrol"
    hunters = "hunters"
    jackal_snipers = "jackal_snipers"
    jackals = "jackals"
    hunter_infantry = "hunter_infantry"
    guta = "guta"  # a single Guta ("Mule" internally) (not in UI)
    skirmishers = "skirmishers"
    hunter_tactical = "hunter_tactical"
    skirmisher_infantry = "skirmisher_infantry"
    heretics = "heretics"
    heretic_snipers = "heretic_snipers"
    heretic_heavy = "heretic_heavy"


# ---- game_variants/components/megalo/limits.h, namespace Megalo --------------------------------


class ConstTeam(StrEnum):
    """Megalo::const_team -- a fixed team-slot reference (as opposed to TeamSettings.teams[i],
    the map's own configured team data). team_1..team_8 correspond 1:1 to TeamSettings.teams[0..7]
    (see mide.extraction._resolve_const_team_name(), which cross-references the two)."""

    none = "none"
    team_1 = "team_1"
    team_2 = "team_2"
    team_3 = "team_3"
    team_4 = "team_4"
    team_5 = "team_5"
    team_6 = "team_6"
    team_7 = "team_7"
    team_8 = "team_8"
    neutral = "neutral"


# ---- game_variants/components/loadouts.h ------------------------------------------------------


class LoadoutPaletteTier(StrEnum):
    """reach::loadout_palette -- not registered as a py::enum_ in bindings.cpp; storage order only."""

    spartan_tier_1 = "spartan_tier_1"
    elite_tier_1 = "elite_tier_1"
    spartan_tier_2 = "spartan_tier_2"
    elite_tier_2 = "elite_tier_2"
    spartan_tier_3 = "spartan_tier_3"
    elite_tier_3 = "elite_tier_3"


# ---- game_variants/components/player_traits.h, namespace reach ---------------------------------


class Weapon(StrEnum):
    random = "random"
    unchanged = "unchanged"
    map_default = "map_default"
    none = "none"
    dmr = "dmr"
    assault_rifle = "assault_rifle"
    plasma_pistol = "plasma_pistol"
    spiker = "spiker"
    energy_sword = "energy_sword"
    magnum = "magnum"
    needler = "needler"
    plasma_rifle = "plasma_rifle"
    rocket_launcher = "rocket_launcher"
    shotgun = "shotgun"
    sniper_rifle = "sniper_rifle"
    spartan_laser = "spartan_laser"
    gravity_hammer = "gravity_hammer"
    plasma_repeater = "plasma_repeater"
    needle_rifle = "needle_rifle"
    focus_rifle = "focus_rifle"
    plasma_launcher = "plasma_launcher"
    concussion_rifle = "concussion_rifle"
    grenade_launcher = "grenade_launcher"
    golf_club = "golf_club"
    fuel_rod_gun = "fuel_rod_gun"
    machine_gun_turret = "machine_gun_turret"
    plasma_cannon = "plasma_cannon"
    target_locator = "target_locator"


class Ability(StrEnum):
    random = "random"
    unchanged = "unchanged"
    map_default = "map_default"
    none = "none"
    sprint = "sprint"
    jetpack = "jetpack"
    armor_lock = "armor_lock"
    unused_power_fist = "unused_power_fist"
    active_camo = "active_camo"
    unused_ammo_pack = "unused_ammo_pack"
    unused_sensor_pack = "unused_sensor_pack"
    hologram = "hologram"
    evade = "evade"
    drop_shield = "drop_shield"


class AbilityUsage(StrEnum):
    unchanged = "unchanged"
    disabled = "disabled"
    not_with_objectives = "not_with_objectives"
    enabled = "enabled"


class ActiveCamo(StrEnum):
    unchanged = "unchanged"
    off = "off"
    worst = "worst"
    poor = "poor"
    good = "good"
    best = "best"
    # NOTE: the 3-bit field can also hold 7, but the engine source comment warns that value
    # crashes MCC on startup -- deliberately not registered as a valid member here.


class Aura(StrEnum):
    unchanged = "unchanged"
    none = "none"
    team_primary = "team_primary"
    darken_armor = "darken_armor"
    pastel_armor = "pastel_armor"
    unknown_5 = "unknown_5"
    unknown_6 = "unknown_6"


class BoolTrait(StrEnum):
    unchanged = "unchanged"
    disabled = "disabled"
    enabled = "enabled"


class DamageMultiplier(StrEnum):
    unchanged = "unchanged"
    value_000 = "value_000"
    value_025 = "value_025"
    value_050 = "value_050"
    value_075 = "value_075"
    value_090 = "value_090"
    value_100 = "value_100"
    value_110 = "value_110"
    value_125 = "value_125"
    value_150 = "value_150"
    value_200 = "value_200"
    value_300 = "value_300"
    instant_kill = "instant_kill"


class DamageResist(StrEnum):
    unchanged = "unchanged"
    value_0010 = "value_0010"
    value_0050 = "value_0050"
    value_0090 = "value_0090"
    value_0100 = "value_0100"
    value_0110 = "value_0110"
    value_0150 = "value_0150"
    value_0200 = "value_0200"
    value_0300 = "value_0300"
    value_0500 = "value_0500"
    value_1000 = "value_1000"
    value_2000 = "value_2000"
    invulnerable = "invulnerable"


class DoubleJump(StrEnum):
    """Engine source marks this field "unused"; the .ui field is literally labelled fieldMovementUnknown."""

    unchanged = "unchanged"
    disabled = "disabled"
    enabled = "enabled"
    enabled_plus_lunge = "enabled_plus_lunge"


class ForcedColor(StrEnum):
    unchanged = "unchanged"
    none = "none"
    red = "red"
    blue = "blue"
    green = "green"
    orange = "orange"
    purple = "purple"
    gold = "gold"
    brown = "brown"
    pink = "pink"
    white = "white"
    black = "black"
    zombie = "zombie"
    very_marginally_more_vibrant_pink = "very_marginally_more_vibrant_pink"


class GrenadeCountTrait(StrEnum):
    """PlayerTraits.offense.grenade_count only -- Loadout.grenade_count is a plain int, a different field."""

    unchanged = "unchanged"
    map_default = "map_default"
    none = "none"
    frag_1 = "frag_1"
    frag_2 = "frag_2"
    frag_3 = "frag_3"
    frag_4 = "frag_4"
    plasma_1 = "plasma_1"
    plasma_2 = "plasma_2"
    plasma_3 = "plasma_3"
    plasma_4 = "plasma_4"
    each_1 = "each_1"
    each_2 = "each_2"
    each_3 = "each_3"
    each_4 = "each_4"


class HealthMultiplier(StrEnum):
    unchanged = "unchanged"
    value_000 = "value_000"
    value_100 = "value_100"
    value_150 = "value_150"
    value_200 = "value_200"
    value_300 = "value_300"
    value_400 = "value_400"


class HealthRate(StrEnum):
    unchanged = "unchanged"
    value_n25 = "value_n25"
    value_n10 = "value_n10"
    value_n05 = "value_n05"
    value_000 = "value_000"
    value_050 = "value_050"
    value_090 = "value_090"
    value_100 = "value_100"
    value_110 = "value_110"
    value_200 = "value_200"


class InfiniteAmmo(StrEnum):
    unchanged = "unchanged"
    disabled = "disabled"
    enabled = "enabled"
    bottomless = "bottomless"


class MovementSpeed(StrEnum):
    unchanged = "unchanged"
    value_000 = "value_000"
    value_025 = "value_025"
    value_050 = "value_050"
    value_075 = "value_075"
    value_090 = "value_090"
    value_100 = "value_100"
    value_110 = "value_110"
    value_120 = "value_120"
    value_130 = "value_130"
    value_140 = "value_140"
    value_150 = "value_150"
    value_160 = "value_160"
    value_170 = "value_170"
    value_180 = "value_180"
    value_190 = "value_190"
    value_200 = "value_200"
    value_300 = "value_300"


class PlayerGravity(StrEnum):
    unchanged = "unchanged"
    value_050 = "value_050"
    value_075 = "value_075"
    value_100 = "value_100"
    value_150 = "value_150"
    value_200 = "value_200"


class RadarRange(StrEnum):
    unchanged = "unchanged"
    meters_010 = "meters_010"
    meters_015 = "meters_015"
    meters_025 = "meters_025"
    meters_050 = "meters_050"
    meters_075 = "meters_075"
    meters_100 = "meters_100"
    meters_150 = "meters_150"


class RadarState(StrEnum):
    unchanged = "unchanged"
    off = "off"
    allies = "allies"
    normal = "normal"
    enhanced = "enhanced"


class ShieldMultiplier(StrEnum):
    unchanged = "unchanged"
    value_000 = "value_000"
    value_100 = "value_100"
    value_150 = "value_150"
    value_200 = "value_200"
    value_300 = "value_300"
    value_400 = "value_400"


class ShieldRate(StrEnum):
    """Also used for PlayerTraits.defense.overshield_rate (same enum, see that field's docstring)."""

    unchanged = "unchanged"
    value_n25 = "value_n25"
    value_n10 = "value_n10"
    value_n05 = "value_n05"
    value_000 = "value_000"
    value_010 = "value_010"
    value_025 = "value_025"
    value_050 = "value_050"
    value_075 = "value_075"
    value_090 = "value_090"
    value_100 = "value_100"
    value_110 = "value_110"
    value_125 = "value_125"
    value_150 = "value_150"
    value_200 = "value_200"


class VampirismRate(StrEnum):
    unchanged = "unchanged"
    value_000 = "value_000"
    value_010 = "value_010"
    value_025 = "value_025"
    value_050 = "value_050"
    value_100 = "value_100"


class VehicleUsage(StrEnum):
    unchanged = "unchanged"
    none = "none"
    passenger_only = "passenger_only"
    driver_only = "driver_only"
    gunner_only = "gunner_only"
    no_passenger = "no_passenger"
    no_driver = "no_driver"
    no_gunner = "no_gunner"
    full_use = "full_use"


class VisibleIdentity(StrEnum):
    """Used for both PlayerTraits.appearance.waypoint and .visible_name (same enum)."""

    unchanged = "unchanged"
    none = "none"
    allies = "allies"
    everyone = "everyone"
