"""Marines and Marauders: stim, focus fire, kiting - the "push in when winning" exception, and its one exception:
banelings, which are always backed away from.

Against sieged tanks the bio splits up on the way in: a shell splashes everything within a cell or so of where it lands, so a bio ball that
walks up to a tank line loses a dozen marines to every volley. From TANK_SPLIT_RANGE out, until something is in weapon range, each unit
keeps its distance from its neighbours (TANK_SPLIT_RADIUS) while it closes in - not at the same target on the same path."""
from typing import List, Optional

from cython_extensions import cy_attack_ready, cy_closest_to, cy_in_attack_range, cy_pick_enemy_target

from ares.behaviors.combat.individual import StutterUnitForward
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.army.consts import FIGHT_GHOST_MAX_AGE, KITE_IN_RESULT, LOCAL_FIGHT_RADIUS
from bot.army.context import ArmyContext
from bot.army.orders import GroupOrders
from bot.army.units.common import (
    all_melee,
    attack_move,
    attack_unit,
    futile_to_kite,
    kite_away,
    kite_from_banelings,
    path_move,
    run,
    target_harmless,
)
from bot.pathing.order_utils import Crowd, spread_out_point

TANK_SPLIT_RANGE = 24.0       # start splitting up when a sieged tank is this close (its own range is 13: room to fan out before it fires)
TANK_SPLIT_RADIUS = 2.2       # ...keeping this far from each other (a shell's splash reaches 1.25 from where it lands)
TANK_SPLIT_NUDGE = 2.5        # ...by stepping this far away from the neighbours that are closer

_STIM = {
    UnitTypeId.MARINE: (AbilityId.EFFECT_STIM_MARINE, BuffId.STIMPACK),
    UnitTypeId.MARAUDER: (AbilityId.EFFECT_STIM_MARAUDER, BuffId.STIMPACKMARAUDER),
}


class BioController:
    def __init__(self, ai):
        self.ai = ai
        self._tanks: List[Unit] = []          # the sieged enemy tanks to split up for, this call
        self._crowd: Optional[Crowd] = None

    def control(self, units: Units, orders: GroupOrders, ctx: ArmyContext) -> None:
        ctx.prefetch_near(units)
        # sieged tanks stay where they are, so one that dropped out of sight a moment ago still counts (Ares' ghosts)
        self._tanks = [
            e for e in self.ai.enemy_units
            if e.type_id == UnitTypeId.SIEGETANKSIEGED and (not e.is_memory or e.age <= FIGHT_GHOST_MAX_AGE)
        ] if orders.aggressive and not orders.retreating and orders.staging is None and not orders.pausing else []      # (not while the army is stopped on purpose)
        self._crowd = Crowd(units) if orders.aggressive else None
        for unit in units:
            self._control_unit(unit, units, orders, ctx)

    def _split_point(self, unit: Unit, units: Units) -> Optional[Point2]:
        """Where a unit on its way in to sieged tanks goes: towards the nearest one, but spread out from its neighbours. None when
        there are no sieged tanks about (or they are still far off)."""
        if not self._tanks:
            return None
        tank = cy_closest_to(unit.position, self._tanks)
        if unit.distance_to(tank) > TANK_SPLIT_RANGE:
            return None
        return spread_out_point(unit, units, tank.position, radius=TANK_SPLIT_RADIUS, nudge=TANK_SPLIT_NUDGE,
                                walkable=self.ai.in_pathing_grid, crowd=self._crowd)

    # ------------------------------------------------------------------------------------------------------------
    def _control_unit(self, unit: Unit, units: Units, orders: GroupOrders, ctx: ArmyContext) -> None:
        targets = ctx.targets_near(unit)
        if not targets:
            self._no_fight(unit, units, orders, ctx)
            return

        in_range = cy_in_attack_range(unit, targets)
        if not in_range and not ctx.banelings_near(unit):
            # nothing to shoot yet: still on the way in - to sieged tanks, spread out (banelings keep their own rule below)
            split = self._split_point(unit, units)
            if split is not None:
                attack_move(unit, split)
                return
        # lowest effective HP among what is already in range, else simply the nearest thing to walk at
        target: Unit = cy_pick_enemy_target(in_range) if in_range else cy_closest_to(unit.position, targets)

        # banelings: always back away, whatever else is true (see kite_from_banelings). `banelings` are the ones within
        # the fight radius - every "kite in" / "futile to run" / "harmless target" shortcut below is off while any exist -
        # and `close_banelings` are inside our own weapon range (plus a margin): the unit steps back from those on its
        # own, without waiting for the danger grid
        banelings = ctx.banelings_near(unit)
        close_banelings = ctx.close_banelings(unit)

        # weapon (about to be) ready: shoot - or walk into range of the target and shoot. cy_attack_ready looks ahead
        # one game step (plus turn/approach time), so the attack is ordered slightly BEFORE the cooldown ends. This holds
        # against banelings too: kiting them is shoot-when-ready, step-back-on-cooldown - never just running
        if cy_attack_ready(self.ai, unit, target):
            if in_range:
                self._stim(unit, target, ctx)
            attack_unit(unit, target)
            return

        if close_banelings:
            kite_from_banelings(self.ai, ctx, unit, close_banelings, orders)
            return

        # weapon on cooldown. Decide between backing off, pushing in, and holding
        # kite in only with "very very high" confidence in THIS fight - the one this unit is in, judged on the units that take part in it
        # and as an advance into the enemy (see GroupOrders.advance_result) - and never against melee-only enemies, where kiting away
        # is free value rather than a trade-off (see all_melee) - and never with banelings about
        advance = orders.advance_result(unit)
        winning = (
            advance is not None
            and advance >= KITE_IN_RESULT
            and not banelings
            and not all_melee([e for e in ctx.enemies_near(unit) if not e.is_memory and e.distance_to(unit) <= LOCAL_FIGHT_RADIUS])
        )
        futile = futile_to_kite(unit, target) and not banelings
        harmless = target_harmless(target) and not banelings

        if not futile and not harmless and not winning and not ctx.is_safe(unit):
            if orders.retreating:
                path_move(self.ai, ctx, unit, orders.hold_point)
                return
            if kite_away(self.ai, ctx, unit):
                return

        if winning or harmless:
            # "kite in": instead of retreating with each shot, step forward with each shot
            if run(self.ai, StutterUnitForward(unit=unit, target=target)):
                return
        # safe, futile to run, or nothing better to do: hold and keep the attack order on the target
        attack_unit(unit, target)

    # ------------------------------------------------------------------------------------------------------------
    def _no_fight(self, unit: Unit, units: Units, orders: GroupOrders, ctx: ArmyContext) -> None:
        if orders.aggressive:
            # spread out a little while marching in so we do not arrive as one AOE-friendly blob (banelings, tanks, storm) - a lot,
            # when sieged tanks are what waits at the end of the march
            point = self._split_point(unit, units)
            if point is None:
                point = orders.target
                if unit.distance_to(point) > unit.ground_range:
                    point = spread_out_point(unit, units, point, walkable=self.ai.in_pathing_grid, crowd=self._crowd)
            attack_move(unit, point)
            return
        position = orders.bio_position if orders.bio_position is not None else orders.hold_point
        if unit.distance_to(position) > orders.hold_radius:
            path_move(self.ai, ctx, unit, position)

    def _stim(self, unit: Unit, target: Unit, ctx: ArmyContext) -> None:
        """Stim once per fight, at full health (stim costs HP), with the target actually in range."""
        entry = _STIM.get(unit.type_id)
        if entry is None or not ctx.stim_researched:
            return
        ability, buff = entry
        if unit.health < unit.health_max or unit.has_buff(buff):
            return
        if target.distance_to(unit) >= unit.ground_range:
            return
        unit(ability)
