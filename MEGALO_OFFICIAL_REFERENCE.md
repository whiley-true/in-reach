# Official Megalo action/condition reference (from MegaloEdit/ManagedMegalo.dll)

Extracted directly from the official Bungie compiler shipped in the Halo: Reach Editing Kit
(`C:\Program Files (x86)\Steam\steamapps\common\HREK\bin\ManagedMegalo.dll`, a mixed-mode
C++/CLI assembly) -- not hand-typed, not reverse-engineered from real `.bin` content. Loaded
via .NET reflection (`Bungie.Megalo.ManagedMegaloSystem.Initialize()` then
`Bungie.Megalo.MegaloCompiler.Initialize(objectListsPath, authorName)`, both static-class
methods despite not looking like it from C#) and queried directly: `GetActionList()`/
`GetConditionList()` for the name lists, `DescribeAction(name)`/`DescribeCondition(name)` for
the syntax text below. See "Regenerating this file" at the bottom for the exact script.

**This is the official, richer, hand-authorable script dialect's own syntax** (matching what
`Bungie.Megalo.MegaloCompiler.Compile()` itself parses -- confirmed by calling it directly: it
expects a structured top-level file format with `variables { }`/`trigger name { }`/etc.
sections, NOT the flat `declare`/`if`/`do` text `_reachvarianttool.decompile_script()`
produces) -- keyword names here (e.g. `object_is_type`, `player_is_elite`) are this dialect's
own, and differ from RVT's decompiled rendering (e.g. `.is_of_type()`, `.is_elite()`) for the
same underlying opcode. Still the single most authoritative source available for exact
argument order, optional-vs-required brackets, and choice-sets for every action/condition --
use it to check/extend `in_reach.app.rvt.megalo_compiler`'s own coverage against the real
thing rather than only what a handful of real `.bin` fixtures happen to exercise.

106 actions, 17 conditions confirmed present (RVT's own binding reports
107/18 respectively for its own, separately-numbered action/condition function tables -- close
but not guaranteed 1:1 by name or order, since RVT is an independent reimplementation, not this
DLL).

Syntax notation: `<name>` = a required argument, `[...]` = optional, `{a|b|c}` = a fixed choice
set (this is MegaloEdit's own notation, not invented here).

## Actions

### `set_score`

```
<operation> <value> <team_or_player_target
```

### `create_object`

```
<object_type> at <place_at_object> [set <object_reference_out>] [label <filter name>] [never_garbage] [suppress_effect] [absolute_orientation] [offset <x> <y> <z> (feet)] [variant <name>]
```

### `delete_object`

```
<object>
```

### `navpoint_set_visible`

```
<object> {no_one|everyone|allies|enemies|player <player_reference> <boolean>}
```

### `navpoint_set_icon`

```
<object> <icon> <number (only if icon==num)>
```

### `navpoint_set_priority`

```
<object> {low|normal|high|blink}
```

### `navpoint_set_timer`

```
<object> <timer_name>
```

### `navpoint_set_visible_range`

```
<object> <min (feet)> <max (feet)>
```

### `set`

```
<var_a> {add|subtract|multiply|divide|set_to|modulo|and|xor|not|lshift|rshift|abs} <var_b>
```

### `set_boundary`

```
<object> {none|sphere|cylinder|box} [width/radius] [length (box)] [neg_height] [pos_height] (feet)
```

### `apply_player_traits`

```
<player> <player_traits_name>
```

### `set_pickup_filter`

```
<object> {no_one|everyone|allies|enemies|player <player_reference> <boolean>}
```

### `set_respawn_filter`

```
<object> {no_one|everyone|allies|enemies|player <player_reference> <boolean>}
```

### `set_fireteam_respawn_filter`

```
<object> {none|all|0-3
```

### `set_progress_bar`

```
<object> {no_one|everyone|allies|enemies|player <player_reference> <boolean>} <timer_name>
```

### `hud_post_message`

```
<team_or_player_target> <sound> <dynamic_string>
```

### `timer_set_rate`

```
<timer> <rate>
```

### `print_variable`

```
<dynamic_string>
```

### `get_player_holding_object`

```
<object> <player_out>
```

### `for_each`

```
<trigger_type>
```

### `end_round`

```
(no arguments)
```

### `boundary_set_visible`

```
<object> <boolean>
```

### `object_destroy`

```
<object> [no_statistics]
```

### `object_set_invincibility`

```
<object> <boolean>
```

### `random`

```
<value_count> <number_out (0-count-1)>
```

### `break_into_debugger`

```
(no arguments)
```

### `object_get_orientation`

```
<object> <orientation_out (1-6)>
```

### `object_get_velocity`

```
<object> <number_out (ft/s)>
```

### `player_death_get_killing_player`

```
<dead_player> <killing_player>
```

### `player_death_get_damage_type`

```
<dead_player> <number_out (damage type)>
```

### `player_death_get_special_type`

```
<dead_player> <number_out (special type)>
```

### `debugging_enable_tracing`

```
<literal_boolean>
```

### `object_attach`

```
<child_object> <parent_object> <offset_x> <offset_y> <offset_z> (feet) [absolute_orientation]
```

### `object_detach`

```
<child_object>
```

### `player_get_place`

```
<player> <number_out (place)>
```

### `team_get_place`

```
<team> <number_out (place)>
```

### `player_get_killing_spree_count`

```
<player> <number_out>
```

### `player_adjust_money`

```
<player> {add|subtract|multiply|divide|set_to|modulo|and|xor|not|lshift|rshift|abs} <number>
```

### `player_enable_purchases`

```
<player> {alive|dead|both} <boolean>
```

### `player_get_vehicle`

```
<player> <vehicle_out>
```

### `player_set_vehicle`

```
<player> <vehicle>
```

### `player_set_unit`

```
<player> <unit>
```

### `timer_reset`

```
<timer>
```

### `weapon_set_pickup_priority`

```
<object> {normal|special|auto}
```

### `object_bounce`

```
<object>
```

### `hud_widget_set_text`

```
<hud_widget_name> <dynamic_string>
```

### `hud_widget_set_value`

```
<hud_widget_name> <dynamic_string>
```

### `hud_widget_set_meter`

```
<hud_widget_name> {off|<number> <number>|<timer>}
```

### `hud_widget_set_icon`

```
<hud_widget_name> <icon name>
```

### `hud_widget_set_visibility`

```
<hud_widget_name> <player> <literal_boolean>
```

### `play_sound`

```
<team_or_player_target> [immediate] <sound>
```

### `object_set_scale`

```
<object> <number (percent)>
```

### `navpoint_set_text`

```
<object> <dynamic_string>
```

### `object_get_shield`

```
<object> <vitality_out (percent)>
```

### `object_get_health`

```
<object> <vitality_out (percent)>
```

### `player_set_objective`

```
<player> <dynamic_string>
```

### `player_set_objective_allegiance`

```
<player> <dynamic_string> <engine_icon_index
```

### `player_set_objective_allegiance_icon`

```
<player> <dynamic_string> <engine_icon_index
```

### `team_set_coop_spawning`

```
<team> <literal_boolean>
```

### `team_set_primary_respawn_object`

```
<team> <object>
```

### `player_set_primary_respawn_object`

```
<player> <object>
```

### `player_get_fireteam_index`

```
<player> <number_out>
```

### `player_set_fireteam_index`

```
<player> <number>
```

### `object_adjust_shield`

```
<object> {add|subtract|multiply|divide|set_to|modulo|and|xor|not|lshift|rshift|abs} <number>
```

### `object_adjust_health`

```
<object> {add|subtract|multiply|divide|set_to|modulo|and|xor|not|lshift|rshift|abs} <number>
```

### `object_get_distance`

```
<object_a> <object_b> <distance_out (feet)>
```

### `object_adjust_maximum_shield`

```
<object> {add|subtract|multiply|divide|set_to|modulo|and|xor|not|lshift|rshift|abs} <number>
```

### `object_adjust_maximum_health`

```
<object> {add|subtract|multiply|divide|set_to|modulo|and|xor|not|lshift|rshift|abs} <number>
```

### `player_set_requisition_palette`

```
<player> <req_palette_name>
```

### `device_set_power`

```
<object> <number (percent)>
```

### `device_get_power`

```
<object> <number_out (percent)>
```

### `device_set_position`

```
<object> <number (percent)>
```

### `device_get_position`

```
<object> <number_out (percent)>
```

### `adjust_grenades`

```
<player> {frag|plasma} {add|subtract|multiply|divide|set_to|modulo|and|xor|not|lshift|rshift|abs} <number>
```

### `submit_incident`

```
<incident_name> <cause_team_or_player> <effect_team_or_player>
```

### `submit_incident_with_custom_value`

```
<incident_name> <cause_team_or_player> <effect_team_or_player> <custom_value_such_as_territory_index>
```

### `set_loadout_palette`

```
<team_or_player> <loadout>
```

### `device_set_position_track`

```
<object> <animation name> <interpolation time>
```

### `device_animate_position`

```
<object> <animation_target_fraction> <animation_duration_seconds> <acceleration_seconds> <deceleration_seconds>
```

### `device_set_position_immediate`

```
<object> <number (percent)>
```

### `saved_film_insert_marker`

```
<offset (s)> <label>
```

### `respawn_zone_enable`

```
<object> <boolean>
```

### `player_get_weapon`

```
<player> {primary|secondary} <weapon_out>
```

### `player_get_equipment`

```
<player> <equipment_out>
```

### `object_set_never_garbage`

```
<object> <boolean>
```

### `player_get_target_object`

```
<player> <object_out>
```

### `create_tunnel`

```
<object_a> <object_b> <object_type> <radius> <object_reference_out>
```

### `debug_force_player_view_count`

```
<splitscreen_count>
```

### `player_pick_up_weapon`

```
<player> <weapon object>
```

### `player_set_coop_spawning`

```
<player> <literal_boolean>
```

### `object_set_orientation`

```
<object> <source> [absolute_orientation]
```

### `object_face_object`

```
<object> <target> [offset <x> <y> <z> (feet)]
```

### `biped_give_weapon`

```
<biped> <weapon> {primary|secondary|force}
```

### `biped_drop_weapon`

```
<biped> {primary|secondary} [delete_on_drop]
```

### `set_scenario_interpolator_state`

```
<interpolator index> <boolean active>
```

### `get_random_object`

```
<filter name> <ignore object> <object out>
```

### `game_grief_record_custom_penalty`

```
<player> <penalty amount>
```

### `boundary_set_player_color`

```
<object> <player variable name> (must be member of object)
```

### `begin`

```
(no arguments)
```

### `hs_function_call`

```
<function name>
```

### `get_button_time`

```
<player> <button> <milliseconds_out>
```

### `team_set_vehicle_spawning`

```
<team> <literal_boolean>
```

### `player_set_vehicle_spawning`

```
<player> <literal_boolean>
```

### `set_player_respawn_vehicle`

```
<vehicle> <player>
```

### `set_team_respawn_vehicle`

```
<vehicle> <team>
```

### `hide_object`

```
<object> <should hide>
```

## Conditions

### `if`

```
<var_a> {less_than|greater_than|equal_to|less_than_or_equal_to|greater_than_or_equal_to|not_equal_to} <var_b>
```

### `object_in_area`

```
<test_object> <boundary_object>
```

### `player_died`

```
<player> <player_death_type>
```

### `team_disposition`

```
<team_a> <disposition> <team_b>
```

### `timer_expired`

```
<timer>
```

### `object_is_type`

```
<object> <object_type>
```

### `team_is_active`

```
<team>
```

### `object_out_of_bounds`

```
<object>
```

### `player_is_fire_team_leader`

```
<player>
```

### `player_assisted_with_kill`

```
<assisting_player> <victim_player>
```

### `object_matches_filter`

```
<object> <filter_name>
```

### `player_is_active`

```
<player>
```

### `equipment_is_active`

```
<object>
```

### `player_is_spartan`

```
<player>
```

### `player_is_elite`

```
<player>
```

### `player_is_editor`

```
<player>
```

### `game_is_forge`

```
(no arguments)
```

## Companion name lists

Plain name lists (one per line, in `reference/megalo/`), also pulled straight from
`MegaloCompiler.Get*List()` -- the exact, complete enum vocabularies for the corresponding
argument types (object types, weapons, incidents, etc.), useful for confirming an enum
constant name is real before spending a brute-force `.decompile()` search on it, or for
cross-checking against RVT's own `OpcodeArgTypeinfo` value tables.

| List | Count | File |
|---|---|---|
| object types (biped/vehicle/weapon/equipment/prop/etc. tags) | 222 | `reference/megalo/object_types.txt` |
| weapon tags | 24 | `reference/megalo/weapons.txt` |
| equipment tags | 10 | `reference/megalo/equipment.txt` |
| vehicle tags | 35 | `reference/megalo/vehicles.txt` |
| grenade types | 4 | `reference/megalo/grenades.txt` |
| Forge weapon-set names | 16 | `reference/megalo/weapon_sets.txt` |
| Forge vehicle-set names | 14 | `reference/megalo/vehicle_sets.txt` |
| submit_incident event names | 449 | `reference/megalo/incidents.txt` |
| loadout names | 81 | `reference/megalo/loadouts.txt` |
| loadout palette names | 15 | `reference/megalo/loadout_palettes.txt` |
| engine string IDs | 57 | `reference/megalo/string_ids.txt` |
| HUD widget icon names | 35 | `reference/megalo/hud_widget_icons.txt` |
| overridable game option names | 53 | `reference/megalo/overridable_game_options.txt` |
| sound names | 95 | `reference/megalo/sounds.txt` |

## Regenerating this file

Requires a Windows machine with the Halo: Reach Editing Kit installed via Steam (free with
Halo: MCC). Run from PowerShell:

```powershell
Add-Type -Path "C:\Program Files (x86)\Steam\steamapps\common\HREK\bin\ManagedMegalo.dll"
$sys = New-Object Bungie.Megalo.ManagedMegaloSystem
[Bungie.Megalo.ManagedMegaloSystem].GetMethod("Initialize", [Type[]]@()).Invoke($sys, @())
[Bungie.Megalo.MegaloCompiler]::Initialize(
    "C:\Program Files (x86)\Steam\steamapps\common\HREK\data\multiplayer\megalo\object_lists", "me")
# then MegaloCompiler.GetActionList()/GetConditionList()/DescribeAction(name)/DescribeCondition(name)
# -- static methods, so call them via the fully-qualified type, not an instance.
```
