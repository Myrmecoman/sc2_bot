import numpy as np
from typing import Optional
from bot.pathing.consts import ALL_STRUCTURES, ATTACK_TARGET_IGNORE, DANGEROUS_STRUCTURES
from bot.pathing.pathing import Pathing
from sc2.bot_ai import BotAI
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.ability_id import AbilityId


class Medivacs:
    def __init__(self, ai: BotAI, pathing: Pathing):
        self.ai: BotAI = ai
        self.pathing: Pathing = pathing

    async def handle_attackers(self, units: Units, attack_target: Point2) -> None:
        grid = self.pathing.air_grid
        for unit in units:
            
            # use afterburners continuously (not optimal but better than not using it)
            if await self.ai.can_cast(unit, AbilityId.EFFECT_MEDIVACIGNITEAFTERBURNERS):
                unit(AbilityId.EFFECT_MEDIVACIGNITEAFTERBURNERS)

            # in danger, run away
            if not self.pathing.is_position_safe(grid, unit.position):
                self.move_to_safety(unit, grid)
                continue

            # get to the target
            if self.ai.units.not_flying.amount > 0:
                pos = self.ai.units.not_flying.closest_to(attack_target)
                unit.attack(pos)
            else:
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

            # use afterburners continuously (not optimal but better than not using it)
            if await self.ai.can_cast(unit, AbilityId.EFFECT_MEDIVACIGNITEAFTERBURNERS):
                unit(AbilityId.EFFECT_MEDIVACIGNITEAFTERBURNERS)

            move_to: Point2 = self.pathing.find_path_next_point(unit.position, pos, self.pathing.air_grid)
            unit.move(move_to)
