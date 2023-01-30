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


class Bio:
    def __init__(self, ai: BotAI, pathing: Pathing):
        self.ai: BotAI = ai
        self.pathing: Pathing = pathing

    async def handle_attackers(self, units: Units, attack_target: Point2) -> None:
        grid = self.pathing.ground_grid
        for unit in units:

            close_enemies: Units = None
            if unit.type_id == UnitTypeId.MARAUDER:
                close_enemies = self.ai.enemy_units.filter(lambda u: not u.is_flying and u.type_id not in ATTACK_TARGET_IGNORE) | self.ai.enemy_structures#.filter(lambda s: s.distance_to(unit) < 15.0 and s.type_id in DANGEROUS_STRUCTURES)
            else:
                close_enemies = self.ai.enemy_units.filter(lambda u: u.type_id not in ATTACK_TARGET_IGNORE) | self.ai.enemy_structures#.filter(lambda s: s.distance_to(unit) < 15.0 and s.type_id in DANGEROUS_STRUCTURES)

            # check for nearby target fire
            target: Optional[Unit] = None
            if close_enemies:
                in_attack_range: Units = close_enemies.in_attack_range_of(unit)
                if in_attack_range:
                    target = self.pick_enemy_target(unit, in_attack_range, True)
                else:
                    target = self.pick_enemy_target(unit, close_enemies, False)

            if target and unit.weapon_cooldown == 0:
                self.attack_and_stim(unit, target)
                continue

            # no target and in danger, run away
            if not self.pathing.is_position_safe(grid, unit.position):
                self.move_to_safety(unit, grid)
                continue

            # get to the target
            if unit.distance_to(attack_target) > unit.ground_range:
                # only make pathing queries if enemies are close
                if target:
                    unit.attack(target)
                else:
                    unit.attack(attack_target)
            else:
                unit.attack(target)

    def move_to_safety(self, unit: Unit, grid: np.ndarray):
        """
        Find a close safe spot on our grid
        Then path to it
        """
        safe_spot: Point2 = self.pathing.find_closest_safe_spot(unit.position, grid)
        move_to: Point2 = self.pathing.find_path_next_point(unit.position, safe_spot, grid)
        unit.move(move_to)
    
    def attack_and_stim(self, unit: Unit, enemy: Unit):
        if unit.health == unit.health_max and self.ai.already_pending_upgrade(UpgradeId.STIMPACK) == 1 and enemy.distance_to(unit) < unit.ground_range:
            if unit.type_id == UnitTypeId.MARINE and unit.is_using_ability(AbilityId.EFFECT_STIM_MARINE) == False:
                unit(AbilityId.EFFECT_STIM_MARINE)
            elif unit.type_id == UnitTypeId.MARAUDER and unit.is_using_ability(AbilityId.EFFECT_STIM_MARAUDER) == False:
                unit(AbilityId.EFFECT_STIM_MARAUDER)
        unit.attack(enemy)

    async def retreat_to(self, units: Units, pos: Point2):
        """
        Path to pos
        """
        for unit in units:
            move_to: Point2 = self.pathing.find_path_next_point(unit.position, pos, self.pathing.ground_grid)
            unit.move(move_to)

    @staticmethod
    def pick_enemy_target(unit: Unit, enemies: Units, in_range: bool = True) -> Unit:
        """For best enemy target from the provided enemies
        TODO: If there are multiple units that can be killed in one shot, pick the highest value one
        """
        if in_range:
            return min(enemies, key=lambda e: (e.health + e.shield, e.tag),)
        else:
            return enemies.closest_to(unit)
