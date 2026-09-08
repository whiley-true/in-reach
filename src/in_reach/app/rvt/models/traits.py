"""ReachPlayerTraits (game_variants/components/player_traits.h), edited on
ui/main_window/page_player_traits.ui. One shared shape, reused by GameSettings at 5 places:
Options.respawn_settings.traits, Options.map_and_game_settings.base_traits and
.powerup_{red,blue,yellow}_traits -- see game_settings.py.
"""
from pydantic import BaseModel, Field

from .enums import (
    Ability,
    AbilityUsage,
    ActiveCamo,
    Aura,
    BoolTrait,
    DamageMultiplier,
    DamageResist,
    DoubleJump,
    ForcedColor,
    GrenadeCountTrait,
    HealthMultiplier,
    HealthRate,
    InfiniteAmmo,
    MovementSpeed,
    PlayerGravity,
    RadarRange,
    RadarState,
    ShieldMultiplier,
    ShieldRate,
    VampirismRate,
    VehicleUsage,
    VisibleIdentity,
    Weapon,
)


class DefenseTraits(BaseModel):
    damage_resist: DamageResist = DamageResist.unchanged
    health_mult: HealthMultiplier = HealthMultiplier.unchanged
    health_rate: HealthRate = HealthRate.unchanged
    shield_mult: ShieldMultiplier = ShieldMultiplier.unchanged
    shield_rate: ShieldRate = ShieldRate.unchanged
    overshield_rate: ShieldRate = ShieldRate.unchanged  # recharge rate for overshield powerup? or overshields in general? -- unconfirmed per the engine source's own comment
    headshot_immune: BoolTrait = BoolTrait.unchanged
    vampirism: VampirismRate = VampirismRate.unchanged
    assassin_immune: BoolTrait = BoolTrait.unchanged
    cannot_die_from_damage: BoolTrait = BoolTrait.unchanged


class OffenseTraits(BaseModel):
    damage_mult: DamageMultiplier = DamageMultiplier.unchanged
    melee_mult: DamageMultiplier = DamageMultiplier.unchanged
    weapon_primary: Weapon = Weapon.unchanged
    weapon_secondary: Weapon = Weapon.unchanged
    grenade_count: GrenadeCountTrait = GrenadeCountTrait.unchanged  # NOT the same field as Loadout.grenade_count, see loadouts.py
    infinite_ammo: InfiniteAmmo = InfiniteAmmo.unchanged
    grenade_regen: BoolTrait = BoolTrait.unchanged
    weapon_pickup: BoolTrait = BoolTrait.unchanged
    ability_usage: AbilityUsage = AbilityUsage.unchanged
    abilities_drop_on_death: BoolTrait = BoolTrait.unchanged
    infinite_ability: BoolTrait = BoolTrait.unchanged
    ability: Ability = Ability.unchanged


class MovementTraits(BaseModel):
    speed: MovementSpeed = MovementSpeed.unchanged
    jump_height: int = Field(default=-1, ge=-1, le=400)  # percentage; -1 is the "Unchanged" sentinel (QSpinBox specialValueText), not a real -1% value
    gravity: PlayerGravity = PlayerGravity.unchanged
    double_jump: DoubleJump = DoubleJump.unchanged
    vehicle_usage: VehicleUsage = VehicleUsage.unchanged


class AppearanceTraits(BaseModel):
    active_camo: ActiveCamo = ActiveCamo.unchanged
    waypoint: VisibleIdentity = VisibleIdentity.unchanged
    visible_name: VisibleIdentity = VisibleIdentity.unchanged
    aura: Aura = Aura.unchanged
    forced_color: ForcedColor = ForcedColor.unchanged


class SensorTraits(BaseModel):
    radar_state: RadarState = RadarState.unchanged
    radar_range: RadarRange = RadarRange.unchanged
    directional_damage_indicator: int = Field(default=0, ge=0, le=3)  # no named C++ enum -- .ui combobox items are literally "Unchanged"/"Unknown 1"/"Unknown 2"/"Unknown 3"


class PlayerTraits(BaseModel):
    defense: DefenseTraits = DefenseTraits()
    offense: OffenseTraits = OffenseTraits()
    movement: MovementTraits = MovementTraits()
    appearance: AppearanceTraits = AppearanceTraits()
    sensors: SensorTraits = SensorTraits()
