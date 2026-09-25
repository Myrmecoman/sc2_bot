"""Small helpers shared by every unit controller."""
import math
from typing import Iterable, Optional, Sequence

from ares.behaviors.combat.individual import KeepUnitSafe
from sc2.position import Point2
from sc2.unit import Unit

from bot.army.consts import BANELING_RETREAT_DISTANCE
from bot.army.context import ArmyContext
from bot.army.orders import GroupOrders
from bot.pathing.order_utils import is_already_attack_moving_to, is_already_attacking, is_already_moving_to, segment_walkable

MELEE_RANGE_THRESHOLD = 1.0   # an enemy at or below this ground_range counts as melee (Zealot/Zergling/Ultralisk/...)


def run(ai, behavior) -> bool:
    """Execute an Ares behavior right now (instead of registering it for after-step execution)."""
    return bool(behavior.execute(ai, ai.config, ai.mediator))


# ----------------------------------------------------------------------------------------------------------------
# order helpers: never re-issue an order the unit is already executing (re-issuing an Attack resets the weapon
# windup in the engine, a real loss of damage output - the "APM bug" this project has always guarded against)
# ----------------------------------------------------------------------------------------------------------------
def attack_unit(unit: Unit, target: Unit) -> None:
    if not is_already_attacking(unit, target):
        unit.attack(target)


def attack_move(unit: Unit, point: Point2) -> None:
    if not is_already_attack_moving_to(unit, point):
        unit.attack(point)


def move_to(unit: Unit, point: Point2) -> None:
    if not is_already_moving_to(unit, point):
        unit.move(point)


# ----------------------------------------------------------------------------------------------------------------
# the kiting rules this bot has been tuned with
# ----------------------------------------------------------------------------------------------------------------
def futile_to_kite(unit: Unit, threat: Optional[Unit]) -> bool:
    """Backing off between shots cannot help when the threat outranges us AND is not slower than us (a Stalker vs a
    Marine) or is near-immobile (a sieged tank, a defensive structure): whenever something outranges us, being in
    OUR range means being in ITS range, so real kiting only pays off if we can escape its entire threat radius
    faster than it can re-threaten us. real_speed (not movement_speed) accounts for active buffs/slows."""
    if threat is None:
        return False
    return threat.ground_range > unit.ground_range and (
        threat.real_speed >= unit.real_speed or threat.real_speed < 0.5
    )


def target_harmless(target: Optional[Unit]) -> bool:
    """A target with no weapon at all (a Command Center, a depot) can never hurt us - retreating from it only
    wastes time we could spend closing in and finishing it off."""
    return target is not None and target.ground_range == 0 and target.air_range == 0


def all_melee(enemies: Iterable[Unit]) -> bool:
    """Kiting a melee-only group is free value, not a trade-off, so it is never worth abandoning (used to veto the
    'push in because we are winning' shortcut)."""
    seen = False
    for e in enemies:
        seen = True
        if e.ground_range > MELEE_RANGE_THRESHOLD:
            return False
    return seen


# ----------------------------------------------------------------------------------------------------------------
# movement
# ----------------------------------------------------------------------------------------------------------------
def kite_away(ai, ctx: ArmyContext, unit: Unit, grid=None) -> bool:
    """Step to the nearest safe cell on `grid` (default: the unit's own ground or air grid). False if the unit is
    already safe - i.e. nothing was ordered."""
    return run(ai, KeepUnitSafe(unit=unit, grid=ctx.grid_for(unit) if grid is None else grid))


def retreat_point(ai, unit: Unit, threats: Sequence[Unit], fallback: Point2) -> Point2:
    """A point BANELING_RETREAT_DISTANCE from `unit`, straight away from the centre of `threats` (or half that far when the
    full distance is not walkable). `fallback` when the unit stands in the middle of them - any direction is as good - or
    there is nowhere to walk to."""
    cx = sum(t.position.x for t in threats) / len(threats)
    cy = sum(t.position.y for t in threats) / len(threats)
    dx, dy = unit.position.x - cx, unit.position.y - cy
    length = math.hypot(dx, dy)
    if length < 0.5:
        return fallback
    for fraction in (1.0, 0.5):
        reach = BANELING_RETREAT_DISTANCE * fraction
        point = Point2((unit.position.x + dx / length * reach, unit.position.y + dy / length * reach))
        if ai.in_map_bounds(point) and ai.in_pathing_grid(point):
            return point
    return fallback


def kite_from_banelings(
    ai, ctx: ArmyContext, unit: Unit, banelings: Sequence[Unit], orders: GroupOrders, grid=None
) -> None:
    """Banelings are the one enemy every kiting unit ALWAYS backs away from: not only "when this cell is dangerous" (Ares' grid
    reaches just 3 around a baneling, about a second before it arrives) and not "unless we are winning" (bio that walks into
    banelings because the simulator likes the fight loses its marines to splash for nothing). Steps away from the pack, or
    heads for the hold point when the group is retreating anyway. `banelings` must not be empty."""
    if orders.retreating:
        path_move(ai, ctx, unit, orders.hold_point, grid=grid)
        return
    path_move(ai, ctx, unit, retreat_point(ai, unit, banelings, orders.hold_point), grid=grid)


def path_move(ai, ctx: ArmyContext, unit: Unit, target: Point2, grid=None, sense_danger: bool = True) -> None:
    """Move towards `target` along a path that avoids the enemy influence on `grid`."""
    grid = ctx.grid_for(unit) if grid is None else grid
    next_point = ai.mediator.find_path_next_point(
        start=unit.position, target=target, grid=grid, sense_danger=sense_danger
    )
    move_to(unit, next_point)


def follow_point(orders: GroupOrders, lead: float = 4.0, walkable=None) -> Point2:
    """Where a fast or supporting unit (cyclone, medivac, viking, ...) should be while there is no fight: just ahead of
    the group's main squad when attacking - so it never runs ahead of the units it is meant to support - and at the
    hold position otherwise. Ground units pass `walkable` (`ai.in_pathing_grid`): the point ahead is in a straight line
    towards the target, so if that line crosses terrain nobody can stand on, the target itself is returned instead and
    the engine finds the real way (see spread_out_point)."""
    if orders.aggressive:
        anchor = orders.anchor
        if anchor is None or anchor.distance_to(orders.target) <= lead:
            return orders.target
        point = anchor.towards(orders.target, lead)
        if walkable is not None and not segment_walkable(anchor, point, walkable):
            return orders.target
        return point
    return orders.bio_position if orders.bio_position is not None else orders.hold_point
