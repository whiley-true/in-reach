"""Builds an in_reach.app.rvt.models.GameSettings from a loaded _reachvarianttool GameVariant.

Scoped to what's bound in _reachvarianttool. Expand as more of the engine gets bound -- add the
field to the relevant model in models/ first, then read it here.

Several fields are packed bitmasks in the engine (a single `flags` int per options struct) rather
than individually-bound booleans. The *_FLAGS maps below mirror the corresponding C++
flags_t/Flags enums bit-for-bit (see the cited header for each) so those bits can be unpacked here
in Python without needing a bindings.cpp change per flag.

Enum-typed fields are stored as cobb::bitnumber<N, reach::X>, so _reachvarianttool's generic
bitnumber type_caster hands Python a plain int, not the registered py::enum_ object -- _enum()
below reconstructs the pybind11 enum from that int (to get a name back), then looks up the
matching member on the equivalent models.enums class (a plain Python Enum, independent of the
native module -- see models/enums.py's docstring for why).
"""
from datetime import datetime, timezone
from pathlib import Path

from .models import enums as E
from .models.game_settings import (
    Firefight,
    FirefightCustomSkull,
    FirefightGameSettings,
    FirefightGeneralSettings,
    FirefightRound,
    FirefightSkullSet,
    FirefightWave,
    FirefightWaveTraits,
    GameSettings,
    GeneralSettings,
    LoadoutSettings,
    MapAndGameSettings,
    Meta,
    Metadata,
    Multiplayer,
    MultiplayerGameSettings,
    OptionVisibility,
    RespawnSettings,
    SocialSettings,
    TeamSettings,
    TitleUpdateSettings,
)
from .models.loadouts import Loadout, LoadoutPalette
from .models.script_settings import (
    ForgeLabel,
    MapPermissions,
    PlayerRatingParams,
    RequiredObjectTypes,
    ScriptedHUDWidget,
    ScriptedOption,
    ScriptedOptionValue,
    ScriptedPlayerTraits,
    ScriptedStat,
    ScriptSettings,
)
from .models.teams import Team
from .models.traits import (
    AppearanceTraits,
    DefenseTraits,
    MovementTraits,
    OffenseTraits,
    PlayerTraits,
    SensorTraits,
)
from .rvt_bridge import get_rvt

# game_variants/components/custom_game_options.h, ReachCGGeneralOptions::flags_t
GENERAL_FLAGS = {
    "perfection_enabled": 0x01,
    "new_round_resets_players": 0x02,
    "new_round_resets_map": 0x04,
    "teams_enabled": 0x08,
}
# game_variants/components/custom_game_options.h, ReachCGRespawnOptions::flags_t
RESPAWN_FLAGS = {
    "sync_with_team": 0x01,
    "respawn_with_teammate": 0x02,
    "respawn_at_location": 0x04,
    "respawn_on_kills": 0x08,
}
# game_variants/components/custom_game_options.h, ReachCGSocialOptions::flags_t
SOCIAL_FLAGS = {
    "dead_player_voice": 0x01,
    "global_voice": 0x02,
    "proximity_voice": 0x04,
    "betrayal_booting": 0x08,
    "friendly_fire": 0x10,
}
# game_variants/components/custom_game_options.h, ReachCGMapOptions::flags_t
MAP_FLAGS = {
    "grenades": 0x01,
    "shortcuts": 0x02,
    "abilities": 0x04,
    "powerups": 0x08,
    "turrets": 0x10,
    "indestructible_vehicles": 0x20,
}
# game_variants/components/teams.h, ReachTeamData::Flags
TEAM_DATA_FLAGS = {
    "enabled": 0x01,
    "color_primary_enabled": 0x02,
    "color_secondary_enabled": 0x04,
    "color_text_enabled": 0x08,
}
# ui/main_window/page_multiplayer_settings_loadout.cpp (0x01/0x02 used inline there; no named C++ enum)
LOADOUT_FLAGS = {
    "spartan_loadouts_enabled": 0x01,
    "elite_loadouts_enabled": 0x02,
}
# game_variants/types/firefight.h, GameVariantDataFirefight::scenario_flags
FIREFIGHT_SCENARIO_FLAGS = {
    "hazards_enabled": 0x01,
    "all_generators_must_survive": 0x02,
    "random_generator_spawns": 0x04,
    "weapon_drops_enabled": 0x08,
    "ammo_crates_enabled": 0x10,
}
# game_variants/components/tu1_options.h, ReachTU1Flags
TU1_FLAGS = {
    "bleedthrough": 0x01,
    "armor_lock_cant_shed_stickies": 0x02,
    "armor_lock_can_be_stuck": 0x04,
    "enable_active_camo_modifiers": 0x08,
    "limit_sword_block_to_sword": 0x10,
    "enable_automatic_magnum": 0x20,
}
# game_variants/components/firefight_round.h, ReachFirefightRound::skulls / GameVariantDataFirefight::
# bonusWaveSkulls (skull_list_t, an 18-bit cobb::bitnumber). Assumed to match reach::firefight_skull's
# declaration order (bit i = the i-th enumerator) -- unlike the *_FLAGS maps above, there's no explicit
# per-bit constant in the engine source to confirm this against, since skull_list_t is a bare bitnumber
# with no named flags_t/Flags enum alongside it.
FIREFIGHT_SKULL_FLAGS = {
    "iron": 0x00001,
    "black_eye": 0x00002,
    "tough_luck": 0x00004,
    "catch_": 0x00008,
    "fog": 0x00010,
    "famine": 0x00020,
    "thunderstorm": 0x00040,
    "tilt": 0x00080,
    "mythic": 0x00100,
    "assassin": 0x00200,
    "blind": 0x00400,
    "cowbell": 0x00800,
    "grunt_birthday_party": 0x01000,
    "iwhbyd": 0x02000,
    "red": 0x04000,
    "yellow": 0x08000,
    "blue": 0x10000,
}
# Megalo::const_team's team_1..team_8 map 1:1 onto TeamSettings.teams[0..7] -- see
# _resolve_const_team_name() below.
CONST_TEAM_INDEX = {
    E.ConstTeam.team_1: 0,
    E.ConstTeam.team_2: 1,
    E.ConstTeam.team_3: 2,
    E.ConstTeam.team_4: 3,
    E.ConstTeam.team_5: 4,
    E.ConstTeam.team_6: 5,
    E.ConstTeam.team_7: 6,
    E.ConstTeam.team_8: 7,
}


def _unpack_flags(flags: int, bit_map: dict) -> dict:
    return {name: bool(flags & mask) for name, mask in bit_map.items()}


def _enum_by_name(name: str, model_enum_cls):
    # Several engine enum fields are stored in a wider bitfield/byte than the engine actually
    # assigns names to (e.g. reach::health_rate is a 4-bit field -- 0-15 representable -- but only
    # 0-9 have a named C++ enumerator; several sibling enums in the same headers have their own
    # explicit "bitfield can hold more, though likely not valid" comments for the same reason --
    # confirmed by an audit covering every enum _enum() below routes through). A real .bin can
    # genuinely contain one of these reserved/unmapped values -- confirmed by a live crash on a
    # real Capture the Flag variant's health_rate field -- and pybind11's own enum reconstruction
    # collapses EVERY such value to the same placeholder name ("???"), so there is no way to
    # recover which specific reserved value it was once it gets here. Falling back to the enum's
    # own first-declared member (every affected trait enum -- confirmed across player_traits.h --
    # starts with "unchanged" at raw value 0) means reading a file with a reserved value never
    # crashes, at the cost of that specific field misreporting as "unchanged" instead of its true
    # (meaningless anyway, per the engine's own comments) raw value -- a deliberate, documented
    # trade-off, not a silent gap: re-compiling settings that were only ever read-and-passed-through
    # (never actually edited) could clobber a reserved value back to 0 rather than preserving it
    # byte-for-byte.
    if name not in model_enum_cls.__members__:
        return next(iter(model_enum_cls))
    return model_enum_cls[name]


def _enum(rvt_enum_cls, model_enum_cls, raw_value: int):
    # Reconstruct the pybind11 enum from the raw bitnumber int (see module docstring), then map
    # its name onto the equivalent mide.models.enums member -- see _enum_by_name()'s docstring for
    # the reserved/unmapped-value fallback this needs.
    return _enum_by_name(rvt_enum_cls(raw_value).name, model_enum_cls)


def _object_type_name(rvt, index: int | None) -> str | None:
    return rvt.object_type_name(index) if index is not None else None


def _resolve_const_team_name(const_team: E.ConstTeam, teams: list[Team]) -> str | None:
    """The map's actual configured team name for a Megalo::const_team slot -- as opposed to
    `const_team`'s own name (team_1, ...), which is just a fixed slot reference, not the team's
    real display name (e.g. "Crimson")."""
    if const_team == E.ConstTeam.none:
        return None
    if const_team == E.ConstTeam.neutral:
        return "Neutral"
    index = CONST_TEAM_INDEX[const_team]
    return teams[index].name or f"Team {index + 1}"


def _string_table_text(table) -> str:
    return table[0].text if len(table) > 0 else ""


def _timestamp_to_datetime(seconds: int) -> datetime:
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def _extract_meta(variant, source_path: Path, mp) -> Meta:
    if mp is not None:
        header = mp.variant_header
    else:
        header = variant.content_header  # Firefight (or other non-MP types) has no header copy of its own
    return Meta(
        is_forge=mp.is_forge if mp is not None else False,
        is_multiplayer=mp is not None,
        symmetric=mp.symmetric if mp is not None else False,
        title=header.title,
        description=header.description,
        source_file=source_path.name,
        generated_at=datetime.now(timezone.utc),
    )


def _extract_metadata(mp) -> Metadata:
    vh = mp.variant_header
    # engine_icon/engine_category: read from the DIRECT MultiplayerData fields, not vh's nested
    # copy -- these are the ones RVT's own editor GUI actually reads back on load (see
    # mide.settings_writer.apply_multiplayer_settings()'s docstring); RVT's own write handlers keep
    # both copies in sync, but the direct one is the more authoritative source to read from.
    return Metadata(
        description_string=_string_table_text(mp.localized_desc),
        category=_string_table_text(mp.localized_category),
        categorization_icon=E.EngineIcon(mp.engine_icon) if mp.engine_icon in E.EngineIcon._value2member_map_ else None,
        engine_category=E.EngineCategory(mp.engine_category) if mp.engine_category in E.EngineCategory._value2member_map_ else None,
        author=vh.created_by.author_name,
        created_at=_timestamp_to_datetime(vh.created_by.timestamp),
        editor=vh.modified_by.author_name,
        edited_at=_timestamp_to_datetime(vh.modified_by.timestamp),
    )


def _extract_player_traits(rvt, traits) -> PlayerTraits:
    d, o, m, a, s = traits.defense, traits.offense, traits.movement, traits.appearance, traits.sensors
    return PlayerTraits(
        defense=DefenseTraits(
            damage_resist=_enum(rvt.DamageResist, E.DamageResist, d.damage_resist),
            health_mult=_enum(rvt.HealthMultiplier, E.HealthMultiplier, d.health_mult),
            health_rate=_enum(rvt.HealthRate, E.HealthRate, d.health_rate),
            shield_mult=_enum(rvt.ShieldMultiplier, E.ShieldMultiplier, d.shield_mult),
            shield_rate=_enum(rvt.ShieldRate, E.ShieldRate, d.shield_rate),
            overshield_rate=_enum(rvt.ShieldRate, E.ShieldRate, d.overshield_rate),
            headshot_immune=_enum(rvt.BoolTrait, E.BoolTrait, d.headshot_immune),
            vampirism=_enum(rvt.VampirismRate, E.VampirismRate, d.vampirism),
            assassin_immune=_enum(rvt.BoolTrait, E.BoolTrait, d.assassin_immune),
            cannot_die_from_damage=_enum(rvt.BoolTrait, E.BoolTrait, d.cannot_die_from_damage),
        ),
        offense=OffenseTraits(
            damage_mult=_enum(rvt.DamageMultiplier, E.DamageMultiplier, o.damage_mult),
            melee_mult=_enum(rvt.DamageMultiplier, E.DamageMultiplier, o.melee_mult),
            weapon_primary=_enum(rvt.Weapon, E.Weapon, o.weapon_primary),
            weapon_secondary=_enum(rvt.Weapon, E.Weapon, o.weapon_secondary),
            grenade_count=_enum(rvt.GrenadeCountTrait, E.GrenadeCountTrait, o.grenade_count),
            infinite_ammo=_enum(rvt.InfiniteAmmo, E.InfiniteAmmo, o.infinite_ammo),
            grenade_regen=_enum(rvt.BoolTrait, E.BoolTrait, o.grenade_regen),
            weapon_pickup=_enum(rvt.BoolTrait, E.BoolTrait, o.weapon_pickup),
            ability_usage=_enum(rvt.AbilityUsage, E.AbilityUsage, o.ability_usage),
            abilities_drop_on_death=_enum(rvt.BoolTrait, E.BoolTrait, o.abilities_drop_on_death),
            infinite_ability=_enum(rvt.BoolTrait, E.BoolTrait, o.infinite_ability),
            ability=_enum(rvt.Ability, E.Ability, o.ability),
        ),
        movement=MovementTraits(
            speed=_enum(rvt.MovementSpeed, E.MovementSpeed, m.speed),
            jump_height=m.jump_height,
            gravity=_enum(rvt.PlayerGravity, E.PlayerGravity, m.gravity),
            double_jump=_enum(rvt.DoubleJump, E.DoubleJump, m.double_jump),
            vehicle_usage=_enum(rvt.VehicleUsage, E.VehicleUsage, m.vehicle_usage),
        ),
        appearance=AppearanceTraits(
            active_camo=_enum(rvt.ActiveCamo, E.ActiveCamo, a.active_camo),
            waypoint=_enum(rvt.VisibleIdentity, E.VisibleIdentity, a.waypoint),
            visible_name=_enum(rvt.VisibleIdentity, E.VisibleIdentity, a.visible_name),
            aura=_enum(rvt.Aura, E.Aura, a.aura),
            forced_color=_enum(rvt.ForcedColor, E.ForcedColor, a.forced_color),
        ),
        sensors=SensorTraits(
            radar_state=_enum(rvt.RadarState, E.RadarState, s.radar_state),
            radar_range=_enum(rvt.RadarRange, E.RadarRange, s.radar_range),
            directional_damage_indicator=s.directional_damage_indicator,
        ),
    )


def _extract_general(rvt, options, mp) -> GeneralSettings:
    general = options.general
    flags = _unpack_flags(general.flags, GENERAL_FLAGS)
    return GeneralSettings(
        **flags,
        player_species=options.team.species,
        time_limit=general.time_limit,
        round_limit=general.round_limit,
        rounds_to_win=general.rounds_to_win,
        sudden_death_time=general.sudden_death_time,
        grace_period=general.grace_period,
        fireteams_enabled=mp.fireteams_enabled,
        score_to_win=mp.score_to_win,
    )


def _extract_respawn(rvt, respawn) -> RespawnSettings:
    """`respawn` is a RespawnOptions object directly -- CustomGameOptions.respawn for
    Multiplayer, or FirefightData.elite_respawn_options for Firefight (same C++ type either way,
    just reached via a different path -- see _extract_firefight())."""
    flags = _unpack_flags(respawn.flags, RESPAWN_FLAGS)
    return RespawnSettings(
        **flags,
        lives_per_round=respawn.lives_per_round,
        team_lives_per_round=respawn.team_lives_per_round,
        respawn_time=respawn.respawn_time,
        suicide_penalty=respawn.suicide_penalty,
        betrayal_penalty=respawn.betrayal_penalty,
        respawn_growth=respawn.respawn_growth,
        loadout_cam_time=respawn.loadout_cam_time,
        traits_duration=respawn.traits_duration,
        traits=_extract_player_traits(rvt, respawn.traits),
    )


def _extract_social(rvt, options) -> SocialSettings:
    social = options.social
    flags = _unpack_flags(social.flags, SOCIAL_FLAGS)
    return SocialSettings(**flags, observers=social.observers, team_changes=social.team_changes)


def _extract_map(rvt, options) -> MapAndGameSettings:
    map_options = options.map
    flags = _unpack_flags(map_options.flags, MAP_FLAGS)
    return MapAndGameSettings(
        **flags,
        weapon_set=_enum(rvt.WeaponSet, E.WeaponSet, map_options.weapon_set),
        vehicle_set=_enum(rvt.VehicleSet, E.VehicleSet, map_options.vehicle_set),
        powerup_duration_red=map_options.powerup_red.duration,
        powerup_duration_blue=map_options.powerup_blue.duration,
        powerup_duration_yellow=map_options.powerup_yellow.duration,
        base_traits=_extract_player_traits(rvt, map_options.base_traits),
        powerup_red_traits=_extract_player_traits(rvt, map_options.powerup_red.traits),
        powerup_blue_traits=_extract_player_traits(rvt, map_options.powerup_blue.traits),
        powerup_yellow_traits=_extract_player_traits(rvt, map_options.powerup_yellow.traits),
    )


def _extract_team_entry(index: int, team) -> Team:
    flags = _unpack_flags(team.flags, TEAM_DATA_FLAGS)
    name = team.get_name()
    return Team(
        **flags,
        index=index,
        name=name.text if name is not None else None,
        species=team.spartan_or_elite,
        fireteam_count=team.fireteam_count,
        initial_designator=team.initial_designator,
        color_primary=team.color_primary,
        color_secondary=team.color_secondary,
        color_text=team.color_text,
    )


def _extract_team(rvt, options) -> TeamSettings:
    team_options = options.team
    teams = [_extract_team_entry(i, team_options.team(i)) for i in range(team_options.team_count)]
    return TeamSettings(
        scoring_method=_enum(rvt.TeamScoringMode, E.TeamScoringMode, team_options.scoring),
        switch_type=_enum(rvt.TeamDesignatorSwitchType, E.TeamDesignatorSwitchType, team_options.designator_switch_type),
        teams=teams,
    )


def _extract_loadout_entry(rvt, loadout) -> Loadout:
    return Loadout(
        visible=loadout.visible,
        name_index=loadout.name_index,
        weapon_primary=_enum(rvt.Weapon, E.Weapon, loadout.weapon_primary),
        weapon_secondary=_enum(rvt.Weapon, E.Weapon, loadout.weapon_secondary),
        ability=_enum(rvt.Ability, E.Ability, loadout.ability),
        grenade_count=loadout.grenade_count,  # plain int -- NOT the PlayerTraits.offense.grenade_count enum
    )


def _extract_loadout_palette(rvt, index: int, palette) -> LoadoutPalette:
    tier = list(E.LoadoutPaletteTier)[index]
    loadouts = [_extract_loadout_entry(rvt, palette.loadout(i)) for i in range(palette.loadout_count)]
    return LoadoutPalette(tier=tier, loadouts=loadouts)


def _extract_loadout(rvt, options) -> LoadoutSettings:
    loadouts = options.loadouts
    flags = _unpack_flags(loadouts.flags, LOADOUT_FLAGS)
    palettes = [_extract_loadout_palette(rvt, i, loadouts.palette(i)) for i in range(loadouts.palette_count)]
    return LoadoutSettings(**flags, palettes=palettes)


def _extract_option_visibility(mp) -> OptionVisibility:
    return OptionVisibility(
        engine_options_disabled=list(mp.engine_options_disabled),
        engine_options_hidden=list(mp.engine_options_hidden),
        megalo_options_disabled=list(mp.megalo_options_disabled),
        megalo_options_hidden=list(mp.megalo_options_hidden),
    )


def _extract_title_update(mp) -> TitleUpdateSettings:
    tu = mp.title_update_data
    flags = _unpack_flags(tu.flags, TU1_FLAGS)
    return TitleUpdateSettings(
        **flags,
        precision_bloom=tu.precision_bloom * 100.0,  # stored as a 0.0-2.0 fraction; UI shows a 0-200 percentage
        armor_lock_damage_drain=tu.armor_lock_damage_drain,
        armor_lock_damage_drain_limit=tu.armor_lock_damage_drain_limit,
        active_camo_energy_curve_min=tu.active_camo_energy_curve_min,
        active_camo_energy_curve_max=tu.active_camo_energy_curve_max,
        magnum_damage=tu.magnum_damage,
        magnum_fire_delay=tu.magnum_fire_delay,
    )


# ReachPlayerRatingParams::indices (game_variants/components/player_rating_params.h) -- the
# order of PlayerRatingParams' 15 named fields must match this exactly, since mp.player_rating_params.values
# is a plain 15-float list/array with no field names of its own on the Python side.
PLAYER_RATING_PARAM_NAMES = [
    "rating_scale",
    "kill_weight",
    "assist_weight",
    "betrayal_weight",
    "death_weight",
    "normalize_by_max_kills",
    "base",
    "range",
    "loss_scalar",
    "custom_stat_0",
    "custom_stat_1",
    "custom_stat_2",
    "custom_stat_3",
    "expansion_0",
    "expansion_1",
]


def _text_or_empty(string_ref) -> str:
    # string_ref is a ReachString* (via a MegaloStringRef -- see bindings.cpp's forge_label.h/
    # megalo_options.h/megalo_game_stats.h bindings), or None if unset.
    return string_ref.text if string_ref is not None else ""


def _optional_index(value: int) -> int | None:
    return value if value >= 0 else None


REQUIREMENT_FLAGS = {
    # Megalo::ReachForgeLabel::requirement_flags (game_variants/components/megalo/forge_label.h)
    "requires_object_type": 0x01,
    "requires_assigned_team": 0x02,
    "requires_number": 0x04,
}


def _extract_forge_label(rvt, fl, teams: list[Team]) -> ForgeLabel:
    flags = _unpack_flags(fl.requirements, REQUIREMENT_FLAGS)
    required_object_type = _optional_index(fl.required_object_type)
    required_team = _enum(rvt.ConstTeam, E.ConstTeam, fl.required_team)
    return ForgeLabel(
        **flags,
        name=_text_or_empty(fl.name),
        required_object_type=required_object_type,
        required_object_type_name=_object_type_name(rvt, required_object_type),
        required_team=required_team,
        required_team_name=_resolve_const_team_name(required_team, teams),
        required_number=fl.required_number,
        map_must_have_at_least=fl.map_must_have_at_least,
    )


def _extract_scripted_option_value(v) -> ScriptedOptionValue:
    return ScriptedOptionValue(name=_text_or_empty(v.name), desc=_text_or_empty(v.desc), value=v.value)


def _extract_scripted_option(o) -> ScriptedOption:
    values = [_extract_scripted_option_value(o.value(i)) for i in range(o.value_count)]
    return ScriptedOption(
        name=_text_or_empty(o.name),
        desc=_text_or_empty(o.desc),
        is_range=o.is_range,
        values=values,
        range_default=_extract_scripted_option_value(o.range_default) if o.range_default is not None else None,
        range_min=_extract_scripted_option_value(o.range_min) if o.range_min is not None else None,
        range_max=_extract_scripted_option_value(o.range_max) if o.range_max is not None else None,
        default_value_index=o.default_value_index,
        range_current=o.range_current,
        current_value_index=o.current_value_index,
    )


def _extract_scripted_player_trait(rvt, t) -> ScriptedPlayerTraits:
    # t is a ScriptedPlayerTraits (bindings.cpp registers it with ReachPlayerTraits as its pybind11
    # base), so it exposes .defense/.offense/.movement/.appearance/.sensors directly -- reuse
    # _extract_player_traits() by passing it straight through.
    return ScriptedPlayerTraits(name=_text_or_empty(t.name), desc=_text_or_empty(t.desc), traits=_extract_player_traits(rvt, t))


def _extract_scripted_stat(t) -> ScriptedStat:
    # format/sort_order are plain (non-bitnumber) enum members in the engine, so they come
    # through as real pybind11 enum objects already -- no _enum() int-reconstruction step needed --
    # but still go through _enum_by_name() for its reserved/unmapped-value fallback (same
    # "???"-name situation as _enum(), just arriving here as a pybind11 object rather than a raw
    # int to begin with).
    return ScriptedStat(
        name=_text_or_empty(t.name),
        format=_enum_by_name(t.format.name, E.ScriptedStatFormat),
        sort_order=_enum_by_name(t.sort_order.name, E.ScriptedStatSort),
        group_by_team=t.group_by_team,
    )


def _extract_scripted_hud_widget(w) -> ScriptedHUDWidget:
    return ScriptedHUDWidget(position=w.position)


def _extract_script_settings(rvt, mp, teams: list[Team]) -> ScriptSettings:
    mperm = mp.map_permissions
    prp = mp.player_rating_params
    object_type_indices = list(mp.used_object_type_indices)
    return ScriptSettings(
        forge_labels=[_extract_forge_label(rvt, mp.forge_label(i), teams) for i in range(mp.forge_label_count)],
        map_permissions=MapPermissions(
            map_ids=list(mperm.map_ids),
            type=_enum(rvt.MapPermissionType, E.MapPermissionType, mperm.type),
        ),
        player_rating_params=PlayerRatingParams(
            **dict(zip(PLAYER_RATING_PARAM_NAMES, prp.values)),
            show_in_scoreboard=prp.show_in_scoreboard,
        ),
        required_object_types=RequiredObjectTypes(
            object_type_indices=object_type_indices,
            object_type_names=[rvt.object_type_name(i) for i in object_type_indices],
        ),
        scripted_options=[_extract_scripted_option(mp.scripted_option(i)) for i in range(mp.scripted_option_count)],
        scripted_player_traits=[
            _extract_scripted_player_trait(rvt, mp.scripted_player_trait(i)) for i in range(mp.scripted_player_trait_count)
        ],
        scripted_stats=[_extract_scripted_stat(mp.scripted_stat(i)) for i in range(mp.scripted_stat_count)],
        scripted_hud_widgets=[_extract_scripted_hud_widget(mp.scripted_hud_widget(i)) for i in range(mp.scripted_hud_widget_count)],
    )


def _extract_firefight_wave_traits(rvt, wt) -> FirefightWaveTraits:
    return FirefightWaveTraits(
        vision=_enum(rvt.AIVision, E.AIVision, wt.vision),
        hearing=_enum(rvt.AIHearing, E.AIHearing, wt.hearing),
        luck=_enum(rvt.AILuck, E.AILuck, wt.luck),
        shootiness=_enum(rvt.AIShootiness, E.AIShootiness, wt.shootiness),
        grenades=_enum(rvt.AIGrenades, E.AIGrenades, wt.grenades),
        dont_drop_equipment=_enum(rvt.BoolTrait, E.BoolTrait, wt.dont_drop_equipment),
        assassin_immunity=_enum(rvt.BoolTrait, E.BoolTrait, wt.assassin_immunity),
        headshot_immunity=_enum(rvt.BoolTrait, E.BoolTrait, wt.headshot_immunity),
        damage_resist=_enum(rvt.DamageResist, E.DamageResist, wt.damage_resist),
        damage_mult=_enum(rvt.DamageMultiplier, E.DamageMultiplier, wt.damage_mult),
    )


def _extract_firefight_general(rvt, options) -> FirefightGeneralSettings:
    # Same as _extract_general() minus fireteams_enabled/score_to_win -- both are sourced from
    # GameVariantDataMultiplayer directly there, not from ReachCustomGameOptions.general, so they
    # don't exist for Firefight's options tree (see FirefightGeneralSettings' docstring).
    general = options.general
    flags = _unpack_flags(general.flags, GENERAL_FLAGS)
    return FirefightGeneralSettings(
        **flags,
        player_species=options.team.species,
        time_limit=general.time_limit,
        round_limit=general.round_limit,
        rounds_to_win=general.rounds_to_win,
        sudden_death_time=general.sudden_death_time,
        grace_period=general.grace_period,
    )


def _extract_firefight_options(rvt, options) -> FirefightGameSettings:
    return FirefightGameSettings(
        general_settings=_extract_firefight_general(rvt, options),
        respawn_settings=_extract_respawn(rvt, options.respawn),
        social_settings=_extract_social(rvt, options),
        map_and_game_settings=_extract_map(rvt, options),
        team_settings=_extract_team(rvt, options),
        loadout_settings=_extract_loadout(rvt, options),
    )


def _extract_skull_set(bits: int) -> FirefightSkullSet:
    return FirefightSkullSet(**_unpack_flags(bits, FIREFIGHT_SKULL_FLAGS))


def _extract_firefight_wave(rvt, wave) -> FirefightWave:
    return FirefightWave(
        uses_dropship=wave.uses_dropship,
        ordered_squads=wave.ordered_squads,
        squad_count=wave.squad_count,
        squads=[_enum(rvt.FirefightSquad, E.FirefightSquad, wave.squad(i)) for i in range(wave.squad_capacity)],
    )


def _extract_firefight_round(rvt, round_) -> FirefightRound:
    return FirefightRound(
        skulls=_extract_skull_set(round_.skulls),
        wave_initial=_extract_firefight_wave(rvt, round_.wave_initial),
        wave_main=_extract_firefight_wave(rvt, round_.wave_main),
        wave_boss=_extract_firefight_wave(rvt, round_.wave_boss),
    )


def _extract_firefight_custom_skull(rvt, skull) -> FirefightCustomSkull:
    return FirefightCustomSkull(
        traits_spartan=_extract_player_traits(rvt, skull.traits_spartan),
        traits_elite=_extract_player_traits(rvt, skull.traits_elite),
        traits_wave=_extract_firefight_wave_traits(rvt, skull.traits_wave),
    )


def _extract_firefight(rvt, ff) -> Firefight:
    flags = _unpack_flags(ff.scenario_flags, FIREFIGHT_SCENARIO_FLAGS)
    return Firefight(
        **flags,
        wave_limit=ff.wave_limit,
        bonus_target=ff.bonus_target,
        elite_kill_bonus=ff.elite_kill_bonus,
        starting_lives_spartan=ff.starting_lives_spartan,
        starting_lives_elite=ff.starting_lives_elite,
        max_spartan_extra_lives=ff.max_spartan_extra_lives,
        generator_count=ff.generator_count,
        bonus_wave_duration=ff.bonus_wave_duration,
        base_traits_spartan=_extract_player_traits(rvt, ff.base_traits_spartan),
        base_traits_elite=_extract_player_traits(rvt, ff.base_traits_elite),
        base_traits_wave=_extract_firefight_wave_traits(rvt, ff.base_traits_wave),
        elite_respawn_options=_extract_respawn(rvt, ff.elite_respawn_options),
        options=_extract_firefight_options(rvt, ff.options),
        custom_skulls=[_extract_firefight_custom_skull(rvt, ff.custom_skull(i)) for i in range(3)],
        rounds=[_extract_firefight_round(rvt, ff.round(i)) for i in range(3)],
        bonus_wave=_extract_firefight_wave(rvt, ff.bonus_wave),
        bonus_wave_skulls=_extract_skull_set(ff.bonus_wave_skulls),
    )


def extract_game_settings(variant, source_path: Path) -> GameSettings:
    """Build a validated GameSettings from a loaded _reachvarianttool GameVariant."""
    mp = variant.multiplayer
    ff = variant.firefight
    if mp is None:
        # Not multiplayer/Forge -- meta is still fully populated (falls back to
        # GameVariant.content_header for title); multiplayer stays default. If this is a
        # Firefight variant, its own data gets extracted below (first pass -- see the Firefight
        # model's docstring for what isn't covered yet).
        rvt = get_rvt() if ff is not None else None
        return GameSettings(
            meta=_extract_meta(variant, source_path, mp),
            firefight=_extract_firefight(rvt, ff) if ff is not None else Firefight(),
        )

    rvt = get_rvt()
    options = mp.options
    # Computed once, up front, so _extract_script_settings() can cross-reference each forge
    # label's required_team against the map's own configured team names (see
    # _resolve_const_team_name()) without re-extracting the team list itself.
    team_settings = _extract_team(rvt, options)
    game_settings = MultiplayerGameSettings(
        metadata=_extract_metadata(mp),
        general_settings=_extract_general(rvt, options, mp),
        respawn_settings=_extract_respawn(rvt, options.respawn),
        social_settings=_extract_social(rvt, options),
        map_and_game_settings=_extract_map(rvt, options),
        team_settings=team_settings,
        loadout_settings=_extract_loadout(rvt, options),
        option_visibility=_extract_option_visibility(mp),
        title_update_settings=_extract_title_update(mp),
    )
    return GameSettings(
        meta=_extract_meta(variant, source_path, mp),
        multiplayer=Multiplayer(
            game_settings=game_settings,
            script_settings=_extract_script_settings(rvt, mp, team_settings.teams),
        ),
    )
