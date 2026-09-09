"""GameSettings -> _reachvarianttool object-tree writer -- the reverse of
:mod:`in_reach.app.rvt.extraction`'s ``_extract_*`` functions, used by the "apply settings" step of
:mod:`in_reach.app.rvt.compile`'s compile pipeline (PROMPT.md: "applying changes should try and
compile the jsons into a gametype").

Ported near-verbatim from ``in-reach-v2``'s own ``rvt/settings_writer.py`` (itself ported from
``refactor/mide/settings_writer.py``) -- every model/constant it depends on
(``models/game_settings.py``, ``models/script_settings.py``, ``models/loadouts.py``,
``models/teams.py``, ``models/traits.py``, ``models/enums.py``, and ``extraction.py``'s
``*_FLAGS``/``PLAYER_RATING_PARAM_NAMES`` maps) is field-for-field identical between that repo and
this one, so this port is otherwise unchanged.

Scope: scalar/bool/enum/flag fields and player-traits blocks across general/respawn/social/map/
title-update settings, per-team entries, loadout palette entries, OptionVisibility's bit lists,
all 8 ScriptSettings subsystems (apply_script_settings(), a separate top-level entry point -- see
its own docstring for why it isn't folded into apply_multiplayer_settings()), plus meta.title/
description and metadata's description_string/author/editor/categorization_icon/engine_category
(see apply_multiplayer_settings()'s docstring) -- i.e. everything that's a direct field assignment
on an already-writable engine object.

Every list field applied here (team entries, loadout palette entries, forge labels, scripted
options/traits/stats/HUD widgets) is matched positionally against the already-loaded variant's own
list and must be the exact same length -- these lists are either fixed-size engine arrays (8
teams, 6 palettes x 5 loadouts each) or determined by the compiled Megalo script (forge label/
scripted-option/etc. counts), never resized from settings alone, so a length mismatch means the
settings.json being applied is stale relative to the just-compiled script -- raises ValueError
rather than silently truncating/padding. :mod:`in_reach.app.rvt.compile` wraps every apply_*() call
from this module (and strings_writer's) so this never escapes as an unhandled crash.

Text fields (ForgeLabel.name, ScriptedOption[Value].name/desc, ScriptedStat.name,
ScriptedPlayerTraits.name/desc) are deliberately NOT applied by this module at all, script_settings
subsystem functions included -- they're ``ReachString*`` pointers into the shared ``script_strings``
table, and :mod:`in_reach.app.rvt.strings_writer`'s ``apply_strings()`` already covers editing that
table's content by index. Two separate write paths (settings vs. strings) touching the same
underlying ReachString objects would be redundant and a source of confusing "which one wins" bugs,
so text stays strings_writer's job exclusively, mirroring the metadata.category/description_string
split below. Team.name is the same situation, one level up (TeamData.name, not a script_strings
entry, but still routed through strings_writer.apply_strings()'s team-name handling instead of
here) -- see _apply_team_entry()'s docstring.

metadata.category is deliberately NOT applied here (confirmed by direct testing against a real
.bin that writing it has no observable effect anywhere -- RVT's own display, MCC, or in-game):
editing it is still possible via strings_writer.apply_strings(), it's just not part of what a
settings apply/compile touches. description_string is the opposite case -- confirmed against a
real built-in variant to be the field that actually holds a gametype's human-readable description,
so it delegates to strings_writer.apply_description_string() to take effect on compile too, unlike
category. There is no `name` field anymore at all (confirmed never populated, dropped from the
schema -- see Metadata's docstring).

Note: this project also has its own ``Meta.category``/``Meta.category_icon`` (PROMPT.md project
classification, added after this module's v2 ancestor was written) -- unrelated to
``Metadata.categorization_icon``/``engine_category`` above, and never written back here; see
``Meta.category``'s own docstring in ``models/game_settings.py``.
"""
from __future__ import annotations

from . import strings_writer
from .extraction import (
    GENERAL_FLAGS,
    LOADOUT_FLAGS,
    MAP_FLAGS,
    PLAYER_RATING_PARAM_NAMES,
    REQUIREMENT_FLAGS,
    RESPAWN_FLAGS,
    SOCIAL_FLAGS,
    TEAM_DATA_FLAGS,
    TU1_FLAGS,
)
from .models.game_settings import (
    GeneralSettings,
    MapAndGameSettings,
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
from .models.traits import PlayerTraits
from .rvt_bridge import get_rvt


def _raw(rvt_enum_cls, model_member) -> int:
    """Reverse of extraction.py's _enum(): a models.enums member -> the raw int the engine
    stores, by round-tripping through the matching pybind11 enum's name (pybind11 enums aren't
    subscriptable like Python's native Enum, hence getattr() rather than `rvt_enum_cls[name]`)."""
    return getattr(rvt_enum_cls, model_member.name).value


def _raw_enum(rvt_enum_cls, model_member):
    """Same idea as _raw(), but for the handful of fields (ScriptedStat.format/sort_order) that
    are plain, non-bitnumber-wrapped py::enum_ fields in the engine (see extraction.py's
    _extract_scripted_stat() comment) -- these need the actual pybind11 enum object assigned back,
    not its raw int, unlike everything _raw() above is used for."""
    return getattr(rvt_enum_cls, model_member.name)


def _pack_flags(model, bit_map: dict) -> int:
    """Reverse of extraction.py's _unpack_flags(): pack a model's named bool fields back into a
    single flags int."""
    flags = 0
    for name, mask in bit_map.items():
        if getattr(model, name):
            flags |= mask
    return flags


def _apply_player_traits(rvt, traits_obj, traits: PlayerTraits) -> None:
    d, o, m, a, s = traits_obj.defense, traits_obj.offense, traits_obj.movement, traits_obj.appearance, traits_obj.sensors
    pd, po, pm, pa, ps = traits.defense, traits.offense, traits.movement, traits.appearance, traits.sensors

    d.damage_resist = _raw(rvt.DamageResist, pd.damage_resist)
    d.health_mult = _raw(rvt.HealthMultiplier, pd.health_mult)
    d.health_rate = _raw(rvt.HealthRate, pd.health_rate)
    d.shield_mult = _raw(rvt.ShieldMultiplier, pd.shield_mult)
    d.shield_rate = _raw(rvt.ShieldRate, pd.shield_rate)
    d.overshield_rate = _raw(rvt.ShieldRate, pd.overshield_rate)
    d.headshot_immune = _raw(rvt.BoolTrait, pd.headshot_immune)
    d.vampirism = _raw(rvt.VampirismRate, pd.vampirism)
    d.assassin_immune = _raw(rvt.BoolTrait, pd.assassin_immune)
    d.cannot_die_from_damage = _raw(rvt.BoolTrait, pd.cannot_die_from_damage)

    o.damage_mult = _raw(rvt.DamageMultiplier, po.damage_mult)
    o.melee_mult = _raw(rvt.DamageMultiplier, po.melee_mult)
    o.weapon_primary = _raw(rvt.Weapon, po.weapon_primary)
    o.weapon_secondary = _raw(rvt.Weapon, po.weapon_secondary)
    o.grenade_count = _raw(rvt.GrenadeCountTrait, po.grenade_count)
    o.infinite_ammo = _raw(rvt.InfiniteAmmo, po.infinite_ammo)
    o.grenade_regen = _raw(rvt.BoolTrait, po.grenade_regen)
    o.weapon_pickup = _raw(rvt.BoolTrait, po.weapon_pickup)
    o.ability_usage = _raw(rvt.AbilityUsage, po.ability_usage)
    o.abilities_drop_on_death = _raw(rvt.BoolTrait, po.abilities_drop_on_death)
    o.infinite_ability = _raw(rvt.BoolTrait, po.infinite_ability)
    o.ability = _raw(rvt.Ability, po.ability)

    m.speed = _raw(rvt.MovementSpeed, pm.speed)
    m.jump_height = pm.jump_height
    m.gravity = _raw(rvt.PlayerGravity, pm.gravity)
    m.double_jump = _raw(rvt.DoubleJump, pm.double_jump)
    m.vehicle_usage = _raw(rvt.VehicleUsage, pm.vehicle_usage)

    a.active_camo = _raw(rvt.ActiveCamo, pa.active_camo)
    a.waypoint = _raw(rvt.VisibleIdentity, pa.waypoint)
    a.visible_name = _raw(rvt.VisibleIdentity, pa.visible_name)
    a.aura = _raw(rvt.Aura, pa.aura)
    a.forced_color = _raw(rvt.ForcedColor, pa.forced_color)

    s.radar_state = _raw(rvt.RadarState, ps.radar_state)
    s.radar_range = _raw(rvt.RadarRange, ps.radar_range)
    s.directional_damage_indicator = ps.directional_damage_indicator


def _apply_general(rvt, options, mp, general: GeneralSettings) -> None:
    g = options.general
    g.flags = _pack_flags(general, GENERAL_FLAGS)
    g.time_limit = general.time_limit
    g.round_limit = general.round_limit
    g.rounds_to_win = general.rounds_to_win
    g.sudden_death_time = general.sudden_death_time
    g.grace_period = general.grace_period
    mp.fireteams_enabled = general.fireteams_enabled
    mp.score_to_win = general.score_to_win
    options.team.species = general.player_species  # combobox lives on this page but is backed by TeamOptions.species -- see extraction.py's _extract_general()


def _apply_respawn(rvt, respawn_options, respawn: RespawnSettings) -> None:
    r = respawn_options
    r.flags = _pack_flags(respawn, RESPAWN_FLAGS)
    r.lives_per_round = respawn.lives_per_round
    r.team_lives_per_round = respawn.team_lives_per_round
    r.respawn_time = respawn.respawn_time
    r.suicide_penalty = respawn.suicide_penalty
    r.betrayal_penalty = respawn.betrayal_penalty
    r.respawn_growth = respawn.respawn_growth
    r.loadout_cam_time = respawn.loadout_cam_time
    r.traits_duration = respawn.traits_duration
    _apply_player_traits(rvt, r.traits, respawn.traits)


def _apply_social(rvt, options, social: SocialSettings) -> None:
    s = options.social
    s.flags = _pack_flags(social, SOCIAL_FLAGS)
    s.observers = social.observers
    s.team_changes = social.team_changes


def _apply_map(rvt, options, map_settings: MapAndGameSettings) -> None:
    m = options.map
    m.flags = _pack_flags(map_settings, MAP_FLAGS)
    m.weapon_set = _raw(rvt.WeaponSet, map_settings.weapon_set)
    m.vehicle_set = _raw(rvt.VehicleSet, map_settings.vehicle_set)
    m.powerup_red.duration = map_settings.powerup_duration_red
    m.powerup_blue.duration = map_settings.powerup_duration_blue
    m.powerup_yellow.duration = map_settings.powerup_duration_yellow
    _apply_player_traits(rvt, m.base_traits, map_settings.base_traits)
    _apply_player_traits(rvt, m.powerup_red.traits, map_settings.powerup_red_traits)
    _apply_player_traits(rvt, m.powerup_blue.traits, map_settings.powerup_blue_traits)
    _apply_player_traits(rvt, m.powerup_yellow.traits, map_settings.powerup_yellow_traits)


def _apply_team_entry(rvt, team_data, team: Team) -> None:
    """Everything except `name` -- team names go through
    :mod:`in_reach.app.rvt.strings_writer`'s ``apply_strings()``/``_apply_team_names()`` instead
    (TeamData.name is the same engine field either way; routing it through strings_writer keeps
    exactly one write path per field, matching the text-fields note in this module's own
    docstring, even though this particular field isn't a script_strings pointer like the
    ScriptSettings ones are)."""
    team_data.flags = _pack_flags(team, TEAM_DATA_FLAGS)
    team_data.spartan_or_elite = team.species
    team_data.fireteam_count = team.fireteam_count
    team_data.initial_designator = team.initial_designator
    team_data.color_primary = team.color_primary
    team_data.color_secondary = team.color_secondary
    team_data.color_text = team.color_text


def _apply_team(rvt, options, team: TeamSettings) -> None:
    t = options.team
    t.scoring = _raw(rvt.TeamScoringMode, team.scoring_method)
    t.designator_switch_type = _raw(rvt.TeamDesignatorSwitchType, team.switch_type)
    if len(team.teams) != t.team_count:
        raise ValueError(f"team_settings.teams has {len(team.teams)} entries, but this variant has {t.team_count} team slots")
    for i, entry in enumerate(team.teams):
        _apply_team_entry(rvt, t.team(i), entry)


def _apply_loadout_entry(rvt, loadout_obj, loadout: Loadout) -> None:
    loadout_obj.visible = loadout.visible
    loadout_obj.name_index = loadout.name_index
    loadout_obj.weapon_primary = _raw(rvt.Weapon, loadout.weapon_primary)
    loadout_obj.weapon_secondary = _raw(rvt.Weapon, loadout.weapon_secondary)
    loadout_obj.ability = _raw(rvt.Ability, loadout.ability)
    loadout_obj.grenade_count = loadout.grenade_count


def _apply_loadout_palette(rvt, palette_obj, palette: LoadoutPalette) -> None:
    if len(palette.loadouts) != palette_obj.loadout_count:
        raise ValueError(
            f"loadout_settings.palettes[{palette.tier}] has {len(palette.loadouts)} loadouts, "
            f"but this variant has {palette_obj.loadout_count} slots"
        )
    for i, loadout in enumerate(palette.loadouts):
        _apply_loadout_entry(rvt, palette_obj.loadout(i), loadout)


def _apply_loadout(rvt, loadout_options, loadout) -> None:
    loadout_options.flags = _pack_flags(loadout, LOADOUT_FLAGS)
    if len(loadout.palettes) != loadout_options.palette_count:
        raise ValueError(f"loadout_settings.palettes has {len(loadout.palettes)} entries, but this variant has {loadout_options.palette_count}")
    for i, palette in enumerate(loadout.palettes):
        _apply_loadout_palette(rvt, loadout_options.palette(i), palette)


def _apply_option_visibility(mp, visibility: OptionVisibility) -> None:
    """Replaces each of the 4 bit lists wholesale (see bindings.cpp's set_bit_indices_from()) --
    there's no concept of an incremental toggle here, matching how every other list field in this
    module works (post the full desired list, not a diff)."""
    mp.engine_options_disabled = visibility.engine_options_disabled
    mp.engine_options_hidden = visibility.engine_options_hidden
    mp.megalo_options_disabled = visibility.megalo_options_disabled
    mp.megalo_options_hidden = visibility.megalo_options_hidden


def _apply_title_update(mp, tu: TitleUpdateSettings) -> None:
    t = mp.title_update_data
    t.flags = _pack_flags(tu, TU1_FLAGS)
    t.precision_bloom = tu.precision_bloom / 100.0  # UI/model shows a 0-200 percentage; stored as a 0.0-2.0 fraction
    t.armor_lock_damage_drain = tu.armor_lock_damage_drain
    t.armor_lock_damage_drain_limit = tu.armor_lock_damage_drain_limit
    t.active_camo_energy_curve_min = tu.active_camo_energy_curve_min
    t.active_camo_energy_curve_max = tu.active_camo_energy_curve_max
    t.magnum_damage = tu.magnum_damage
    t.magnum_fire_delay = tu.magnum_fire_delay


def apply_multiplayer_settings(mp, content_header, settings: MultiplayerGameSettings) -> list[str]:
    """Apply everything in scope (see module docstring) from `settings` onto `mp` (a loaded
    variant's .multiplayer), including metadata's description_string/author/editor/
    categorization_icon/engine_category (see below) -- does NOT touch metadata.category, see module
    docstring for why. Returns any over-budget-table warning from the description_string write
    (same convention as strings_writer.apply_strings()), as a single-or-empty list. Does not save --
    the caller (in_reach.app.rvt.compile.run_compile()) does that once all requested applies have
    run.

    `content_header` is `GameVariant.content_header` -- categorization_icon/engine_category/
    author/editor are each stored in *three* places in the engine (a direct field on
    GameVariantDataMultiplayer, a duplicate nested inside its own variant_header, AND a third
    duplicate in the top-level content_header), and RVT's own GUI always writes all three
    together, e.g.:

        variant->contentHeader.data.engineCategory = cat;
        data->engineCategory = cat;                    // the direct MultiplayerData field
        data->variantHeader.engineCategory = cat;

    Writing only variant_header's copy would leave the direct field and content_header stale --
    which is exactly what RVT's own editor reads back on load (updateFromVariant() reads
    `mp->engineIcon`/`mp->engineCategory`, the direct fields, not variant_header's), so a change
    would silently "not take effect" when reopening the file even though it round-tripped fine
    through extract/re-extract. All three are kept in sync here to match."""
    rvt = get_rvt()
    options = mp.options
    _apply_general(rvt, options, mp, settings.general_settings)
    _apply_respawn(rvt, options.respawn, settings.respawn_settings)
    _apply_social(rvt, options, settings.social_settings)
    _apply_map(rvt, options, settings.map_and_game_settings)
    _apply_team(rvt, options, settings.team_settings)
    _apply_loadout(rvt, options.loadouts, settings.loadout_settings)
    _apply_option_visibility(mp, settings.option_visibility)
    _apply_title_update(mp, settings.title_update_settings)
    if settings.metadata.categorization_icon is not None:
        icon = settings.metadata.categorization_icon.value
        mp.engine_icon = icon
        mp.variant_header.engine_icon = icon
        content_header.engine_icon = icon
    if settings.metadata.engine_category is not None:
        category = settings.metadata.engine_category.value
        mp.engine_category = category
        mp.variant_header.engine_category = category
        content_header.engine_category = category
    # author/editor: ContentAuthor.author_name is English/Latin-1 only -- no multi-language concept
    # for these, unlike description_string below.
    mp.variant_header.created_by.author_name = settings.metadata.author
    mp.variant_header.modified_by.author_name = settings.metadata.editor
    content_header.created_by.author_name = settings.metadata.author
    content_header.modified_by.author_name = settings.metadata.editor
    warning = strings_writer.apply_description_string(rvt, mp, settings.metadata.description_string)
    return [warning] if warning is not None else []


def _apply_forge_label(rvt, fl, label: ForgeLabel) -> None:
    """Everything except `name` -- see module docstring's "text fields" note."""
    fl.requirements = _pack_flags(label, REQUIREMENT_FLAGS)
    fl.required_object_type = label.required_object_type if label.required_object_type is not None else -1
    fl.required_team = _raw(rvt.ConstTeam, label.required_team)
    fl.required_number = label.required_number
    fl.map_must_have_at_least = label.map_must_have_at_least


def _apply_map_permissions(rvt, mperm, permissions: MapPermissions) -> None:
    mperm.map_ids = permissions.map_ids
    mperm.type = _raw(rvt.MapPermissionType, permissions.type)


def _apply_player_rating_params(prp, params: PlayerRatingParams) -> None:
    prp.values = [getattr(params, name) for name in PLAYER_RATING_PARAM_NAMES]
    prp.show_in_scoreboard = params.show_in_scoreboard


def _apply_required_object_types(mp, required: RequiredObjectTypes) -> None:
    mp.used_object_type_indices = required.object_type_indices


def _apply_scripted_option_value(v_obj, value: ScriptedOptionValue) -> None:
    """Everything except `name`/`desc` -- see module docstring's "text fields" note."""
    v_obj.value = value.value


def _apply_scripted_option(o_obj, option: ScriptedOption) -> None:
    """Everything except `name`/`desc` (own and each value's) -- see module docstring's "text
    fields" note."""
    if len(option.values) != o_obj.value_count:
        raise ValueError(f"scripted_options value count mismatch: settings has {len(option.values)}, variant has {o_obj.value_count}")
    for i, value in enumerate(option.values):
        _apply_scripted_option_value(o_obj.value(i), value)
    o_obj.is_range = option.is_range
    for model_val, engine_ref, field_name in (
        (option.range_default, o_obj.range_default, "range_default"),
        (option.range_min, o_obj.range_min, "range_min"),
        (option.range_max, o_obj.range_max, "range_max"),
    ):
        if (model_val is None) != (engine_ref is None):
            raise ValueError(f"scripted_options.{field_name} presence mismatch between settings and the loaded variant")
        if model_val is not None:
            _apply_scripted_option_value(engine_ref, model_val)
    o_obj.default_value_index = option.default_value_index
    o_obj.range_current = option.range_current
    o_obj.current_value_index = option.current_value_index


def _apply_scripted_player_trait(rvt, t_obj, trait: ScriptedPlayerTraits) -> None:
    """Everything except `name`/`desc` -- see module docstring's "text fields" note. t_obj exposes
    the same 5 trait groups as PlayerTraits directly (ScriptedPlayerTraits is registered with
    ReachPlayerTraits as its pybind11 base -- see extraction.py's _extract_scripted_player_trait()
    for the read-side equivalent), so _apply_player_traits() applies straight through."""
    _apply_player_traits(rvt, t_obj, trait.traits)


def _apply_scripted_stat(rvt, s_obj, stat: ScriptedStat) -> None:
    """Everything except `name` -- see module docstring's "text fields" note."""
    s_obj.format = _raw_enum(rvt.ScriptedStatFormat, stat.format)
    s_obj.sort_order = _raw_enum(rvt.ScriptedStatSort, stat.sort_order)
    s_obj.group_by_team = stat.group_by_team


def _apply_scripted_hud_widget(w_obj, widget: ScriptedHUDWidget) -> None:
    w_obj.position = widget.position


def apply_script_settings(mp, script_settings: ScriptSettings) -> None:
    """Apply everything in ScriptSettings onto `mp` (a loaded variant's .multiplayer) except every
    subsystem's name/desc text fields (see module docstring's "text fields" note -- those go
    through :mod:`in_reach.app.rvt.strings_writer`'s script_strings handling instead). A separate
    top-level entry point from apply_multiplayer_settings() above because ScriptSettings is a
    sibling of MultiplayerGameSettings under GameSettings.multiplayer (`multiplayer.script_settings`,
    not `multiplayer.game_settings`), not a field of the model that function receives -- see
    :mod:`in_reach.app.rvt.compile`'s compile pipeline for both being called together. Does not
    save -- same convention as apply_multiplayer_settings().

    forge_labels/scripted_options/scripted_player_traits/scripted_stats/scripted_hud_widgets are
    each matched positionally against `mp`'s own existing (compile-determined) list and must be
    the same length -- see module docstring's "Every list field" note for why a mismatch raises
    ValueError instead of truncating/padding. This means the script must already be compiled onto
    `mp` (see :func:`in_reach.app.rvt.compile.run_compile`'s ordering) before this is called."""
    rvt = get_rvt()

    if len(script_settings.forge_labels) != mp.forge_label_count:
        raise ValueError(f"script_settings.forge_labels has {len(script_settings.forge_labels)} entries, but this variant has {mp.forge_label_count}")
    for i, label in enumerate(script_settings.forge_labels):
        _apply_forge_label(rvt, mp.forge_label(i), label)

    _apply_map_permissions(rvt, mp.map_permissions, script_settings.map_permissions)
    _apply_player_rating_params(mp.player_rating_params, script_settings.player_rating_params)
    _apply_required_object_types(mp, script_settings.required_object_types)

    if len(script_settings.scripted_options) != mp.scripted_option_count:
        raise ValueError(
            f"script_settings.scripted_options has {len(script_settings.scripted_options)} entries, but this variant has {mp.scripted_option_count}"
        )
    for i, option in enumerate(script_settings.scripted_options):
        _apply_scripted_option(mp.scripted_option(i), option)

    if len(script_settings.scripted_player_traits) != mp.scripted_player_trait_count:
        raise ValueError(
            f"script_settings.scripted_player_traits has {len(script_settings.scripted_player_traits)} entries, "
            f"but this variant has {mp.scripted_player_trait_count}"
        )
    for i, trait in enumerate(script_settings.scripted_player_traits):
        _apply_scripted_player_trait(rvt, mp.scripted_player_trait(i), trait)

    if len(script_settings.scripted_stats) != mp.scripted_stat_count:
        raise ValueError(f"script_settings.scripted_stats has {len(script_settings.scripted_stats)} entries, but this variant has {mp.scripted_stat_count}")
    for i, stat in enumerate(script_settings.scripted_stats):
        _apply_scripted_stat(rvt, mp.scripted_stat(i), stat)

    if len(script_settings.scripted_hud_widgets) != mp.scripted_hud_widget_count:
        raise ValueError(
            f"script_settings.scripted_hud_widgets has {len(script_settings.scripted_hud_widgets)} entries, "
            f"but this variant has {mp.scripted_hud_widget_count}"
        )
    for i, widget in enumerate(script_settings.scripted_hud_widgets):
        _apply_scripted_hud_widget(mp.scripted_hud_widget(i), widget)


def apply_meta_header(mp, content_header, title: str, description: str) -> None:
    """title/description -> GameVariant.content_header always, plus MultiplayerData.variant_header
    too if `mp` is not None (RVT's own GUI always writes both together when either field changes
    for a multiplayer variant) -- a Firefight-only variant has no variant_header of its own, so
    content_header is the only copy to write there (mirrors extraction.py's _extract_meta()
    fallback)."""
    if mp is not None:
        mp.variant_header.title = title
        mp.variant_header.description = description
    content_header.title = title
    content_header.description = description
