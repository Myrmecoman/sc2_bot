import numpy as np
from typing import Dict
from bot.pathing.consts import ATTACK_TARGET_IGNORE, ATTACK_TARGET_IGNORE_WITH_WORKERS, SKYTOSS_TYPES
from bot.pathing.order_utils import is_already_attacking, is_already_attack_moving_to
from bot.pathing.pathing import Pathing
from sc2.bot_ai import BotAI
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId

LOCK_ON_TIMEOUT: float = 15.0  # forget a lock-on if it's been this long, target is presumably dead/gone
LOCK_ON_ABILITIES = {AbilityId.LOCKON_LOCKON, AbilityId.LOCKONAIR_LOCKONAIR}


class Cyclones:
    def __init__(self, ai: BotAI, pathing: Pathing):
        self.ai: BotAI = ai
        self.pathing: Pathing = pathing
        self.lock_ons: Dict[int, float] = {}  # enemy tag -> time we cast lock-on, so we don't re-target it every frame
        self.lockon_range: float = self.ai.game_data.abilities[AbilityId.LOCKON_LOCKON.value]._proto.cast_range

    async def handle_attackers(self, units: Units, attack_target: Point2) -> None:
        grid = self.pathing.ground_grid

        # forget lock-ons old enough that the target is presumably dead or long gone
        to_remove = [tag for tag, cast_time in self.lock_ons.items() if self.ai.time - cast_time > LOCK_ON_TIMEOUT]
        for tag in to_remove:
            self.lock_ons.pop(tag, None)

        for unit in units:
            if unit.is_using_ability(LOCK_ON_ABILITIES):
                continue

            close_enemies: Units = self.ai.enemy_units.filter(lambda u: u.type_id not in ATTACK_TARGET_IGNORE and u.distance_to(unit) < 15.0)

            # try to lock on to a fresh, worthwhile target (never waste it on a worker) before falling back to plain attacks
            lockable: Units = close_enemies.filter(lambda u: u.type_id not in ATTACK_TARGET_IGNORE_WITH_WORKERS and u.tag not in self.lock_ons and u.distance_to(unit) < self.lockon_range)
            if lockable:
                target: Unit = self.pick_lockon_target(lockable)
                ability = AbilityId.LOCKONAIR_LOCKONAIR if target.is_flying else AbilityId.LOCKON_LOCKON
                if await self.ai.can_cast(unit, ability, target):
                    unit(ability, target)
                    self.lock_ons[target.tag] = self.ai.time
                    continue

            # no lock-on target and in danger, run away
            if not self.pathing.is_position_safe(grid, unit.position):
                self.move_to_safety(unit, grid)
                continue

            # get to the target
            if close_enemies:
                target = close_enemies.closest_to(unit)
                if not is_already_attacking(unit, target):
                    unit.attack(target)
            elif not is_already_attack_moving_to(unit, attack_target):
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
        Path to pos. Doesn't cancel an active lock-on: it keeps draining the target without
        needing the cyclone to stay in range once cast. Also keeps firing normal attacks at
        anything already in range while holding (e.g. an enemy stuck at a closed wall) instead
        of ignoring a free kill - only what's already in range, not chasing, so holding stays
        holding.
        """
        grid = self.pathing.ground_grid
        for unit in units:
            if unit.is_using_ability(LOCK_ON_ABILITIES):
                continue

            close_enemies: Units = self.ai.enemy_units.filter(lambda u: u.type_id not in ATTACK_TARGET_IGNORE and u.distance_to(unit) < 15.0)
            if close_enemies:
                in_attack_range: Units = close_enemies.in_attack_range_of(unit)
                if in_attack_range:
                    target = in_attack_range.closest_to(unit)
                    if not is_already_attacking(unit, target):
                        unit.attack(target)
                    continue

            move_to: Point2 = self.pathing.find_path_next_point(unit.position, pos, grid)
            unit.move(move_to)

    @staticmethod
    def pick_lockon_target(enemies: Units) -> Unit:
        """Prefer high-value skytoss air if any is lockable, else lowest effective HP like our other unit classes."""
        priority: Units = enemies.of_type(SKYTOSS_TYPES)
        pool: Units = priority if priority else enemies
        return min(pool, key=lambda e: (e.health + e.shield, e.tag))
