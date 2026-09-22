import numpy as np
from typing import Optional
from bot.pathing.consts import ALL_STRUCTURES, ATTACK_TARGET_IGNORE_WITH_WORKERS, DANGEROUS_STRUCTURES
from bot.pathing.order_utils import is_already_attack_moving_to, spread_out_point
from bot.pathing.pathing import Pathing
from sc2.bot_ai import BotAI
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.ability_id import AbilityId

TANK_SPACING = 3.0            # tanks are big units with a wide splash radius - keep more distance between them than bio needs
TANK_HOLD_ARRIVAL_RANGE = 4.0 # close enough to the hold point to dig in proactively


class Tanks:
    def __init__(self, ai: BotAI, pathing: Pathing):
        self.ai: BotAI = ai
        self.pathing: Pathing = pathing


    async def handle_attackers(self, units: Units, attack_target: Point2) -> None:
        grid = self.pathing.ground_grid

        for unit in units:
            # tanks can't hit air at all, sieged or not - a lifted structure has to be excluded too
            close_enemies: Units = self.ai.enemy_units.filter(lambda u: not u.is_flying and u.type_id not in ATTACK_TARGET_IGNORE_WITH_WORKERS) | self.ai.enemy_structures.not_flying#.filter(lambda s: s.distance_to(unit) < 15.0 and s.type_id in DANGEROUS_STRUCTURES)

            # handle tanks
            if unit.type_id == UnitTypeId.SIEGETANK and close_enemies.amount > 0 and close_enemies.closest_distance_to(unit) <= 13:
                if not unit.is_using_ability(AbilityId.SIEGEMODE_SIEGEMODE):
                    unit(AbilityId.SIEGEMODE_SIEGEMODE)
                continue
            if unit.type_id == UnitTypeId.SIEGETANKSIEGED and (close_enemies.amount == 0 or close_enemies.closest_distance_to(unit) >= 14):
                if not unit.is_using_ability(AbilityId.UNSIEGE_UNSIEGE):
                    unit(AbilityId.UNSIEGE_UNSIEGE)
                continue

            # no target and in danger, run away
            if not self.pathing.is_position_safe(grid, unit.position):
                self.move_to_safety(unit, grid)
                continue

            # get to the target - spread out a bit so we're not all stacked on the same tile,
            # both to spread out our own splash and to not present one juicy AOE target
            spread_point: Point2 = spread_out_point(unit, units, attack_target, radius=TANK_SPACING, nudge=TANK_SPACING)
            if not is_already_attack_moving_to(unit, spread_point):
                unit.attack(spread_point)


    def move_to_safety(self, unit: Unit, grid: np.ndarray):
        """
        Find a close safe spot on our grid
        Then path to it
        """
        safe_spot: Point2 = self.pathing.find_closest_safe_spot(unit.position, grid)
        move_to: Point2 = self.pathing.find_path_next_point(unit.position, safe_spot, grid)
        unit.move(move_to)


    async def retreat_to(self, units: Units, pos: Point2):
        """
        Path to pos. While holding (not actually in danger), dig in proactively once close to the
        hold point instead of only ever reacting once an enemy is already nearby - the whole point
        is to already be sieged and ready by the time the enemy arrives, including when our own
        units kite back through here. Once dug in and safe, stays sieged even with nothing visible
        right now rather than popping in and out every time a target briefly leaves detection range.
        """
        grid = self.pathing.ground_grid
        for unit in units:
            close_enemies: Units = self.ai.enemy_units.filter(lambda u: not u.is_flying and u.type_id not in ATTACK_TARGET_IGNORE_WITH_WORKERS) | self.ai.enemy_structures.not_flying
            safe: bool = self.pathing.is_position_safe(grid, unit.position)
            at_hold_point: bool = unit.position.distance_to(pos) <= TANK_HOLD_ARRIVAL_RANGE

            if unit.type_id == UnitTypeId.SIEGETANKSIEGED:
                # only unsiege if we actually need to move - not safe, or the hold point shifted
                if not safe or not at_hold_point:
                    if not unit.is_using_ability(AbilityId.UNSIEGE_UNSIEGE):
                        unit(AbilityId.UNSIEGE_UNSIEGE)
                continue

            if unit.type_id == UnitTypeId.SIEGETANK and safe:
                close_enough_to_fight = close_enemies.amount > 0 and close_enemies.closest_distance_to(unit) <= 13
                if close_enough_to_fight or at_hold_point:
                    if not unit.is_using_ability(AbilityId.SIEGEMODE_SIEGEMODE):
                        unit(AbilityId.SIEGEMODE_SIEGEMODE)
                    continue

            if not safe:
                self.move_to_safety(unit, grid)
                continue

            spread_point: Point2 = spread_out_point(unit, units, pos, radius=TANK_SPACING, nudge=TANK_SPACING)
            move_to: Point2 = self.pathing.find_path_next_point(unit.position, spread_point, grid)
            unit.move(move_to)
