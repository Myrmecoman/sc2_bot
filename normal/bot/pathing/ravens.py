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
from sc2.data import Race


class Ravens:
    def __init__(self, ai: BotAI, pathing: Pathing):
        self.ai: BotAI = ai
        self.pathing: Pathing = pathing
        self.auto_turret = [] # register auto_turret positions to let the raven reach it even if it is under fire

    async def handle_attackers(self, units: Units, attack_target: Point2) -> None:
        grid = self.pathing.air_grid
        for unit in units:
            
            # cast abilities
            if self.ai.enemy_race == Race.Terran:
                self.raven_vs_terran(unit)
            elif self.ai.enemy_race == Race.Protoss:
                self.raven_vs_protoss(unit)
            elif self.ai.enemy_race == Race.Zerg:
                self.raven_vs_zerg(unit)
            
            # if the order target is an int, it means that we want to cast an ability on a unit
            if isinstance(unit.order_target, int) or (isinstance(unit.order_target, Point2) and unit.order_target in self.auto_turret):
                return
            
            # in danger, run away
            if not self.pathing.is_position_safe(grid, unit.position):
                self.move_to_safety(unit, grid)
                continue

            # get to the target
            if self.ai.units.not_flying.amount > 0:
                pos = self.ai.units.not_flying.closest_to(attack_target).position
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
            move_to: Point2 = self.pathing.find_path_next_point(unit.position, pos, self.pathing.air_grid)
            unit.move(move_to)

    def raven_vs_terran(self, unit: Unit):
        units: Units = self.ai.enemy_units(UnitTypeId.SIEGETANKSIEGED)
        closest: Unit = None
        if units.amount > 0:
            closest = units.closest_to(unit)
        if closest is not None and closest.distance_to(unit) < 13 and self.ai.can_cast(unit, AbilityId.EFFECT_INTERFERENCEMATRIX):
            unit(AbilityId.EFFECT_INTERFERENCEMATRIX, closest)
            return True

        units: Units = self.ai.enemy_units(UnitTypeId.THOR)
        closest: Unit = None
        if units.amount > 0:
            closest = units.closest_to(unit)
        if closest is not None and closest.distance_to(unit) < 13 and self.ai.can_cast(unit, AbilityId.EFFECT_INTERFERENCEMATRIX):
            unit(AbilityId.EFFECT_INTERFERENCEMATRIX, closest)
            return True

        units: Units = self.ai.enemy_units(UnitTypeId.BATTLECRUISER)
        closest: Unit = None
        if units.amount > 0:
            closest = units.closest_to(unit)
        if closest is not None and closest.distance_to(unit) < 13 and self.ai.can_cast(unit, AbilityId.EFFECT_INTERFERENCEMATRIX):
            unit(AbilityId.EFFECT_INTERFERENCEMATRIX, closest)
            return True
        
        return False
    

    def raven_vs_protoss(self, unit: Unit):
        units: Units = self.ai.enemy_units(UnitTypeId.COLOSSUS)
        closest: Unit = None
        if units.amount > 0:
            closest = units.closest_to(unit)
        if closest is not None and closest.distance_to(unit) < 13 and self.ai.can_cast(unit, AbilityId.EFFECT_INTERFERENCEMATRIX):
            unit(AbilityId.EFFECT_INTERFERENCEMATRIX, closest)
            return True
        
        units: Units = self.ai.enemy_units(UnitTypeId.CARRIER)
        closest: Unit = None
        if units.amount > 0:
            closest = units.closest_to(unit)
        if closest is not None and closest.distance_to(unit) < 13 and self.ai.can_cast(unit, AbilityId.EFFECT_INTERFERENCEMATRIX):
            unit(AbilityId.EFFECT_INTERFERENCEMATRIX, closest)
            return True
        
        units: Units = self.ai.enemy_units(UnitTypeId.ARCHON)
        closest: Unit = None
        if units.amount > 0:
            closest = units.closest_to(unit)
        if closest is not None and closest.distance_to(unit) < 13 and self.ai.can_cast(unit, AbilityId.EFFECT_INTERFERENCEMATRIX):
            unit(AbilityId.EFFECT_INTERFERENCEMATRIX, closest)
            return True
        
        units: Units = self.ai.enemy_units(UnitTypeId.IMMORTAL)
        closest: Unit = None
        if units.amount > 0:
            closest = units.closest_to(unit)
        if closest is not None and closest.distance_to(unit) < 13 and self.ai.can_cast(unit, AbilityId.EFFECT_INTERFERENCEMATRIX):
            unit(AbilityId.EFFECT_INTERFERENCEMATRIX, closest)
            return True
        
        return False
    

    def raven_vs_zerg(self, unit: Unit):
        if not self.ai.can_cast(unit, AbilityId.BUILDAUTOTURRET_AUTOTURRET) or self.ai.enemy_units.amount == 0:
            return False
        
        can_place = None
        closest_dist = 10000
        enemy: Unit = self.ai.enemy_units.closest_to(unit.position)
        if enemy is not None and enemy.distance_to(unit) < 10:
            for x in range(int(enemy.position.x - 4), int(enemy.position.x + 5)):
                for y in range(int(enemy.position.y - 4), int(enemy.position.y + 5)):
                    pos = Point2((x, y))
                    if self.ai.can_place(UnitTypeId.AUTOTURRET, pos):
                        dist = unit.distance_to(pos)
                        if can_place is None or dist < closest_dist:
                            can_place = pos
                            closest_dist = dist
        
        if can_place is not None:
            unit(AbilityId.BUILDAUTOTURRET_AUTOTURRET, can_place)
            self.auto_turret.append(can_place)
            return True
        
        return False
