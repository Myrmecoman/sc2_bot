from typing import Optional

import numpy as np
from bot.pathing.consts import ALL_STRUCTURES, ATTACK_TARGET_IGNORE
from bot.pathing.pathing import Pathing
from sc2.bot_ai import BotAI
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

HEAL_AT_LESS_THAN: float = 0.5


class Reapers:
    def __init__(self, ai: BotAI, pathing: Pathing):
        self.ai: BotAI = ai
        self.pathing: Pathing = pathing
        self.grid: np.ndarray = None

        self.reaper_grenade_range: float = self.ai.game_data.abilities[
            AbilityId.KD8CHARGE_KD8CHARGE.value
        ]._proto.cast_range

    @property
    def get_heal_spot(self) -> Point2:
        return self.pathing.find_closest_safe_spot(self.ai.game_info.map_center, self.pathing.reaper_grid)

    async def handle_attackers(self, units: Units, attack_target: Point2) -> None:
        grid: np.ndarray = self.pathing.reaper_grid
        for unit in units:
            # pull back low health reapers to heal
            if unit.health_percentage < HEAL_AT_LESS_THAN:
                unit.move(self.pathing.find_path_next_point(unit.position, self.get_heal_spot, grid))
                continue

            close_enemies: Units = self.ai.enemy_units.filter(lambda u: u.distance_to(unit) < 15.0 and not u.is_flying and u.type_id not in ATTACK_TARGET_IGNORE)

            # reaper grenade
            if await self._do_reaper_grenade(unit, close_enemies):
                continue

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

            # no target and in danger, run away
            if not self.pathing.is_position_safe(grid, unit.position):
                self.move_to_safety(unit, grid)
                continue

            # get to the target
            if unit.distance_to(attack_target) > 5:
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

    @staticmethod
    def pick_enemy_target(enemies: Units) -> Unit:
        """For best enemy target from the provided enemies
        TODO: If there are multiple units that can be killed in one shot, pick the highest value one
        """
        return min(enemies, key=lambda e: (e.health + e.shield, e.tag),)

    async def _do_reaper_grenade(self, r: Unit, close_enemies: Units) -> bool:
        """
        Taken from burny's example
        https://github.com/BurnySc2/python-sc2/blob/develop/examples/terran/mass_reaper.py
        """
        enemy_ground_units_in_grenade_range: Units = close_enemies.filter(
            lambda unit: unit.type_id not in ALL_STRUCTURES
            and unit.type_id not in ATTACK_TARGET_IGNORE
            and unit.distance_to(unit) < self.reaper_grenade_range
        )

        if enemy_ground_units_in_grenade_range and (r.is_attacking or r.is_moving):
            # If AbilityId.KD8CHARGE_KD8CHARGE in abilities, we check that to see if the reaper grenade is off cooldown
            abilities = await self.ai.get_available_abilities(r)
            enemy_ground_units_in_grenade_range = (
                enemy_ground_units_in_grenade_range.sorted(
                    lambda x: x.distance_to(r), reverse=True
                )
            )
            furthest_enemy: Unit = None
            for enemy in enemy_ground_units_in_grenade_range:
                if await self.ai.can_cast(
                    r,
                    AbilityId.KD8CHARGE_KD8CHARGE,
                    enemy,
                    cached_abilities_of_unit=abilities,
                ):
                    furthest_enemy: Unit = enemy
                    break
            if furthest_enemy:
                r(AbilityId.KD8CHARGE_KD8CHARGE, furthest_enemy)
                return True

        return False
