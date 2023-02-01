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


class Banshees:
    def __init__(self, ai: BotAI, pathing: Pathing):
        self.ai: BotAI = ai
        self.pathing: Pathing = pathing
        self.roam_spot = {} # tells where the banshee should harass
        self.roam_spot_positions = [self.ai.enemy_start_locations[0], self.ai.enemy_start_locations[0], self.ai.enemy_start_locations[0], self.ai.enemy_start_locations[0]] # roaming spot positions


    async def handle_attackers(self, units: Units) -> None:

        grid = self.pathing.air_grid

        # remove dead banshees
        to_remove = []
        for k in self.roam_spot.keys():
            if self.ai.units.find_by_tag(k) is None:
                to_remove.append(k)
        for k in to_remove:
            self.roam_spot.pop(k, None)

        for unit in units:
            
            # give a roaming spot to the banshee, it will harass continuously this place autonomously
            if not unit.tag in self.roam_spot.keys():
                spot = self.get_free_roaming_spot()
                if spot != -1:
                    self.roam_spot[unit.tag] = spot
            attack_target: Point2 = self.get_attack_target(unit.tag)

            close_enemies = self.ai.enemy_units.filter(lambda u: u.distance_to(unit) < 15.0 and not u.is_flying and not u.type_id in ATTACK_TARGET_IGNORE)

            # check for nearby target fire
            target: Optional[Unit] = None
            if close_enemies:
                in_attack_range: Units = close_enemies.in_attack_range_of(unit)
                if in_attack_range:
                    target = self.pick_enemy_target(in_attack_range)
                else:
                    target = self.pick_enemy_target(close_enemies)

            if target and unit.weapon_cooldown == 0:
                unit.attack(target)
                continue

            # in danger, run away
            if not self.pathing.is_position_safe(grid, unit.position):
                if self.ai.already_pending_upgrade(UpgradeId.BANSHEECLOAK) == 1 and self.ai.can_cast(unit, AbilityId.BEHAVIOR_CLOAKON_BANSHEE):
                    unit(AbilityId.BEHAVIOR_CLOAKON_BANSHEE)
                self.move_to_safety(unit, grid)
                continue

            # get to the target
            if unit.distance_to(attack_target) > unit.air_range:
                # only make pathing queries if enemies are close
                if close_enemies:
                    unit.move(self.pathing.find_path_next_point(unit.position, attack_target, grid))
                else:
                    unit.move(attack_target)
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


    @staticmethod
    def pick_enemy_target(enemies: Units) -> Unit:
        """For best enemy target from the provided enemies
        TODO: If there are multiple units that can be killed in one shot, pick the highest value one
        """
        workers = enemies.of_type({UnitTypeId.DRONE, UnitTypeId.PROBE, UnitTypeId.SCV, UnitTypeId.MULE})
        if workers.amount > 0:
            return min(workers, key=lambda e: (e.health + e.shield, e.tag),)
        return min(enemies, key=lambda e: (e.health + e.shield, e.tag),)
    

    def get_attack_target(self, tag) -> Point2:
        if enemy_units := self.ai.enemy_units.filter(
            lambda u: u.type_id not in ATTACK_TARGET_IGNORE
            and not u.is_flying
            and not u.is_cloaked
            and not u.is_hallucination):
            return enemy_units.closest_to(self.ai.start_location).position
        return self.roam_spot_positions[self.roam_spot[tag]]
    

    # there are 4 roaming spots, in order it's 1rst base, 2nd, 3rd, and 4rth
    def get_free_roaming_spot(self):
        spots = [0, 0, 0, 0]
        for k in self.roam_spot.keys():
            spots[self.roam_spot[k]] = -1
        for i in range(len(spots)):
            if spots[i] == 0:
                return i
        return -1
