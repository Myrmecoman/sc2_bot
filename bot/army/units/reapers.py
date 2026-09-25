"""Reapers: the early scout/harasser. Grenades (Ares' predictive ReaperGrenade), fights on the climber grid (they can
jump cliffs), retreats when hurt, and while there is nothing else to do it hunts for the enemy base."""
from typing import Optional, Set

from cython_extensions import cy_attack_ready, cy_closest_to, cy_in_attack_range, cy_pick_enemy_target

from ares.behaviors.combat.individual import ReaperGrenade
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.army.consts import ATTACK_TARGET_IGNORE
from bot.army.context import ArmyContext
from bot.army.orders import GroupOrders
from bot.army.units.common import (
    attack_move,
    attack_unit,
    futile_to_kite,
    kite_away,
    kite_from_banelings,
    path_move,
    run,
)

RETREAT_BELOW_HEALTH = 0.5   # pull back to heal below this - reapers regenerate quickly once out of combat
RESUME_ABOVE_HEALTH = 0.85
HIDDEN_BASE_SCOUT_INTERVAL = 30.0   # move on to the next candidate expansion this often while hunting for the enemy


class ReaperHarass:
    def __init__(self, ai):
        self.ai = ai
        self.retreating: Set[int] = set()
        # cycles through expansion locations looking for the enemy's actual base, used only when the early
        # worker-scout (bot/scouting.py) never confirmed it
        self._hunt_index: int = 0
        self._hunt_since: float = 0.0

    def control(self, units: Units, orders: GroupOrders, ctx: ArmyContext) -> None:
        self.retreating &= {u.tag for u in units}
        ctx.prefetch_near(units)
        grid = ctx.climber_grid
        for unit in units:
            self._control_unit(unit, orders, ctx, grid)

    # ------------------------------------------------------------------------------------------------------------
    def _control_unit(self, unit: Unit, orders: GroupOrders, ctx: ArmyContext, grid) -> None:
        health = unit.health_percentage
        if unit.tag in self.retreating:
            if health >= RESUME_ABOVE_HEALTH:
                self.retreating.discard(unit.tag)
        elif health < RETREAT_BELOW_HEALTH:
            self.retreating.add(unit.tag)
        if unit.tag in self.retreating:
            path_move(self.ai, ctx, unit, orders.hold_point, grid=grid)
            return

        # a Reaper only hits ground, and never wastes a shot on a building while units are around
        targets = [t for t in ctx.targets_near(unit) if not t.is_structure]

        if targets and run(self.ai, ReaperGrenade(unit=unit, enemy_units=targets, retreat_target=orders.hold_point,
                                                  grid=grid)):
            return

        # banelings: always back away, whatever else is true (see kite_from_banelings)
        banelings = ctx.banelings_near(unit)
        close_banelings = ctx.close_banelings(unit)

        target: Optional[Unit] = None
        if targets:
            in_range = cy_in_attack_range(unit, targets)
            target = cy_pick_enemy_target(in_range) if in_range else cy_closest_to(unit.position, targets)
            if cy_attack_ready(self.ai, unit, target):
                attack_unit(unit, target)
                return

        if close_banelings:
            kite_from_banelings(self.ai, ctx, unit, close_banelings, orders, grid=grid)
            return

        # in danger: run - unless what threatens us both outranges us AND is not slower (or is rooted), in which case
        # backing off between shots is futile and holding and trading is better (see futile_to_kite) - not with banelings
        if not (futile_to_kite(unit, target) and not banelings) and not ctx.is_safe(unit, grid):
            if kite_away(self.ai, ctx, unit, grid):
                return

        destination = self._destination(orders)
        if unit.distance_to(destination) > 5:
            path_move(self.ai, ctx, unit, destination, grid=grid, sense_danger=bool(targets))
        else:
            attack_move(unit, destination)

    # ------------------------------------------------------------------------------------------------------------
    def _destination(self, orders: GroupOrders) -> Point2:
        ai = self.ai
        enemies = [
            e for e in ai.enemy_units
            if not e.is_memory and not e.is_flying and not e.is_cloaked and not e.is_hallucination
            and e.type_id not in ATTACK_TARGET_IGNORE
        ]
        if enemies:
            return min(enemies, key=lambda e: e.distance_to(ai.start_location)).position
        if ai.enemy_structures:
            return ai.enemy_structures.closest_to(ai.start_location).position
        if not ai.enemy_base_scouted:
            # the early worker-scout never confirmed the enemy's main (died en route, or they just aren't there) -
            # hunt expansions with our own vision instead of sitting at a possibly-empty default forever
            candidate = self._next_hunt_candidate()
            if candidate is not None:
                return candidate
        return ai.enemy_start_locations[0]

    def _next_hunt_candidate(self) -> Optional[Point2]:
        expansions = self.ai.expansion_locations_list
        if not expansions:
            return None
        if self.ai.time - self._hunt_since > HIDDEN_BASE_SCOUT_INTERVAL:
            self._hunt_since = self.ai.time
            self._hunt_index = (self._hunt_index + 1) % len(expansions)
        return expansions[self._hunt_index]

