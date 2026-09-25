"""Cyclones: Lock-On (worth spending on real targets, skytoss first), otherwise kite like the rest of the army."""
from typing import Dict, List, Optional

from cython_extensions import cy_attack_ready, cy_closest_to, cy_in_attack_range

from ares.behaviors.combat.individual import StutterUnitForward
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit
from sc2.units import Units

from bot.army.consts import ATTACK_TARGET_IGNORE_WITH_WORKERS, KITE_IN_RESULT, LOCAL_FIGHT_RADIUS, SKYTOSS_TYPES
from bot.army.context import ArmyContext
from bot.army.orders import GroupOrders
from bot.army.units.common import (
    all_melee,
    attack_move,
    attack_unit,
    follow_point,
    futile_to_kite,
    kite_away,
    kite_from_banelings,
    path_move,
    run,
)

LOCK_ON_TIMEOUT = 15.0   # forget a lock-on after this long - the target is presumably dead or gone
LOCK_ON_ABILITIES = {AbilityId.LOCKON_LOCKON, AbilityId.LOCKONAIR_LOCKONAIR}


class CycloneController:
    def __init__(self, ai):
        self.ai = ai
        self.lock_ons: Dict[int, float] = {}   # enemy tag -> time we locked on, so one target is not re-locked every frame
        self.lockon_range: float = ai.game_data.abilities[AbilityId.LOCKON_LOCKON.value]._proto.cast_range

    def control(self, units: Units, orders: GroupOrders, ctx: ArmyContext) -> None:
        now = self.ai.time
        for tag in [t for t, cast_at in self.lock_ons.items() if now - cast_at > LOCK_ON_TIMEOUT]:
            del self.lock_ons[tag]
        ctx.prefetch_near(units)
        for unit in units:
            self._control_unit(unit, orders, ctx)

    # ------------------------------------------------------------------------------------------------------------
    def _control_unit(self, unit: Unit, orders: GroupOrders, ctx: ArmyContext) -> None:
        # an active lock-on keeps draining the target without the cyclone having to stay in range - leave it alone
        if unit.is_using_ability(LOCK_ON_ABILITIES):
            return

        targets = ctx.targets_near(unit)
        if self._try_lock_on(unit, targets):
            return

        if not targets:
            self._no_fight(unit, orders, ctx)
            return

        in_range = cy_in_attack_range(unit, targets)
        # banelings: always back away, whatever else is true (see kite_from_banelings, and BioController for the details)
        banelings = ctx.banelings_near(unit)
        close_banelings = ctx.close_banelings(unit)
        if not orders.aggressive and in_range and not close_banelings:
            # holding: keep firing at whatever is already in range, exactly like a stationary defender would
            attack_unit(unit, cy_closest_to(unit.position, in_range))
            return

        nearest: Unit = cy_closest_to(unit.position, targets)
        if cy_attack_ready(self.ai, unit, nearest):
            attack_unit(unit, nearest)
            return

        if close_banelings:
            kite_from_banelings(self.ai, ctx, unit, close_banelings, orders)
            return

        nearby = [e for e in ctx.enemies_near(unit) if not e.is_memory and e.distance_to(unit) <= LOCAL_FIGHT_RADIUS]
        advance = orders.advance_result(unit)          # the fight this unit is in, judged as an advance (see BioController)
        winning = (
            advance is not None
            and advance >= KITE_IN_RESULT
            and not all_melee(nearby)
            and not banelings
        )
        # not worth backing off when the nearest threat outranges us and is not slower (kiting cannot create
        # distance), or when we are locally crushing the fight anyway - neither holds with banelings about
        if not (futile_to_kite(unit, nearest) and not banelings) and not winning and not ctx.is_safe(unit):
            if orders.retreating:
                path_move(self.ai, ctx, unit, orders.hold_point)
                return
            if kite_away(self.ai, ctx, unit):
                return
        if winning and run(self.ai, StutterUnitForward(unit=unit, target=nearest)):
            return
        attack_unit(unit, nearest)

    # ------------------------------------------------------------------------------------------------------------
    def _try_lock_on(self, unit: Unit, targets: List[Unit]) -> bool:
        """Spend Lock-On on a fresh, worthwhile target (never a worker). True if the command was issued."""
        if not unit.abilities:
            return False
        candidates = [
            e for e in targets
            if e.type_id not in ATTACK_TARGET_IGNORE_WITH_WORKERS
            and e.tag not in self.lock_ons
            and unit.distance_to(e) <= unit.radius + e.radius + self.lockon_range
        ]
        if not candidates:
            return False
        target = self.pick_lockon_target(candidates)
        ability = AbilityId.LOCKONAIR_LOCKONAIR if target.is_flying else AbilityId.LOCKON_LOCKON
        if ability not in unit.abilities:
            return False
        unit(ability, target)
        self.lock_ons[target.tag] = self.ai.time
        return True

    def _no_fight(self, unit: Unit, orders: GroupOrders, ctx: ArmyContext) -> None:
        point = follow_point(orders, walkable=self.ai.in_pathing_grid)
        if orders.aggressive:
            attack_move(unit, point)
        elif unit.distance_to(point) > orders.hold_radius:
            path_move(self.ai, ctx, unit, point)

    @staticmethod
    def pick_lockon_target(enemies: List[Unit]) -> Unit:
        """Prefer high-value skytoss air if any is lockable, else the lowest effective HP like the other classes."""
        priority = [e for e in enemies if e.type_id in SKYTOSS_TYPES]
        pool = priority if priority else enemies
        return min(pool, key=lambda e: (e.health + e.shield, e.tag))
