import numpy as np
from typing import Optional
from bot.pathing.consts import ALL_STRUCTURES, ATTACK_TARGET_IGNORE_WITH_WORKERS, DANGEROUS_STRUCTURES
from bot.pathing.pathing import Pathing
from sc2.bot_ai import BotAI
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.ability_id import AbilityId


class Tanks:
    def __init__(self, ai: BotAI, pathing: Pathing):
        self.ai: BotAI = ai
        self.pathing: Pathing = pathing


    async def handle_attackers(self, units: Units, attack_target: Point2) -> None:
        grid = self.pathing.ground_grid

        for unit in units:
            close_enemies: Units = self.ai.enemy_units.filter(lambda u: not u.is_flying and u.type_id not in ATTACK_TARGET_IGNORE_WITH_WORKERS) | self.ai.enemy_structures#.filter(lambda s: s.distance_to(unit) < 15.0 and s.type_id in DANGEROUS_STRUCTURES)

            # handle tanks
            if unit.type_id == UnitTypeId.SIEGETANK and close_enemies.amount > 0 and close_enemies.closest_distance_to(unit) <= 13:
                unit(AbilityId.SIEGEMODE_SIEGEMODE)
                continue
            if unit.type_id == UnitTypeId.SIEGETANKSIEGED and (close_enemies.amount == 0 or close_enemies.closest_distance_to(unit) >= 14):
                unit(AbilityId.UNSIEGE_UNSIEGE)
                continue

            # no target and in danger, run away
            if not self.pathing.is_position_safe(grid, unit.position):
                self.move_to_safety(unit, grid)
                continue

            # get to the target
            unit.attack(attack_target)


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
        Path to pos
        """
        for unit in units:
            close_enemies: Units = self.ai.enemy_units.filter(lambda u: not u.is_flying and u.type_id not in ATTACK_TARGET_IGNORE_WITH_WORKERS)# | self.ai.enemy_structures.filter(lambda s: s.distance_to(unit) < 15.0 and s.type_id in DANGEROUS_STRUCTURES)
            if unit.type_id == UnitTypeId.SIEGETANKSIEGED and (close_enemies.not_structure.amount == 0 or close_enemies.not_structure.closest_distance_to(unit) > 14):
                unit(AbilityId.UNSIEGE_UNSIEGE)

            move_to: Point2 = self.pathing.find_path_next_point(unit.position, pos, self.pathing.ground_grid)
            unit.move(move_to)
