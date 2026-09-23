import numpy as np
from typing import Dict, Optional
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
LOCAL_FIGHT_RADIUS = 14.0             # how far around a unit counts as "this particular fight"
OVERWHELMING_LOCAL_POWER_RATIO = 2.0  # local power edge that's worth pushing in for instead of kiting away
MELEE_RANGE_THRESHOLD = 1.0           # a nearby enemy at or below this ground_range counts as melee


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

            # no lock-on target and in danger, run away - unless it's futile to kite (the nearest
            # threat outranges us and isn't slower, so backing off can't create distance) or
            # we're locally overwhelming the enemy anyway (push in instead of kiting away). Same
            # reasoning retreat_to already uses below - this was previously a bare safety check
            # with neither exception, unlike every other combat-capable unit class
            nearest: Optional[Unit] = close_enemies.closest_to(unit) if close_enemies else None
            futile_to_kite: bool = (
                nearest is not None
                and nearest.ground_range > unit.ground_range
                and (nearest.real_speed >= unit.real_speed or nearest.real_speed < 0.5)
            )
            if (
                not futile_to_kite
                and not self.pathing.is_position_safe(grid, unit.position)
                and not self._winning_locally(unit, units, close_enemies)
            ):
                self.move_to_safety(unit, grid)
                continue

            # get to the target
            if nearest is not None:
                if not is_already_attacking(unit, nearest):
                    unit.attack(nearest)
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

    def _winning_locally(self, unit: Unit, units: Units, close_enemies: Units) -> bool:
        """True when the fight actually happening right around this unit is lopsided enough that
        kiting away between shots would just waste time - see bio.py's identical helper for the
        full reasoning, including the melee exception."""
        nearby_enemies: Units = close_enemies.closer_than(LOCAL_FIGHT_RADIUS, unit)
        if not nearby_enemies:
            return False
        if all(e.ground_range <= MELEE_RANGE_THRESHOLD for e in nearby_enemies):
            return False
        nearby_allies: Units = units.closer_than(LOCAL_FIGHT_RADIUS, unit)
        advisor = self.ai.army_advisor
        local_enemy_power: float = sum(advisor.unit_power(e) for e in nearby_enemies)
        if local_enemy_power <= 0:
            return False
        local_our_power: float = sum(advisor.unit_power(a) for a in nearby_allies)
        return local_our_power > OVERWHELMING_LOCAL_POWER_RATIO * local_enemy_power

    async def retreat_to(self, units: Units, pos: Point2):
        """
        Hold near pos. Doesn't cancel an active lock-on: it keeps draining the target without
        needing the cyclone to stay in range once cast. Also takes a fresh lock-on if one's
        available while waiting - there's no reason to withhold it just because we haven't
        committed to a full attack, and this was the only place a Cyclone could never use it
        (mirrors the same fix already made for Ravens' Auto-Turret/Matrix).

        Keeps firing normal attacks at anything already in range while holding. If something
        nearby isn't in range yet, don't just sit at pos absorbing it doing nothing either:
        retreat if this isn't a fight worth taking, or close the distance and engage if it
        clearly is - same reasoning handle_attackers already uses.
        """
        grid = self.pathing.ground_grid
        for unit in units:
            if unit.is_using_ability(LOCK_ON_ABILITIES):
                continue

            close_enemies: Units = self.ai.enemy_units.filter(lambda u: u.type_id not in ATTACK_TARGET_IGNORE and u.distance_to(unit) < 15.0)

            lockable: Units = close_enemies.filter(lambda u: u.type_id not in ATTACK_TARGET_IGNORE_WITH_WORKERS and u.tag not in self.lock_ons and u.distance_to(unit) < self.lockon_range)
            if lockable:
                target: Unit = self.pick_lockon_target(lockable)
                ability = AbilityId.LOCKONAIR_LOCKONAIR if target.is_flying else AbilityId.LOCKON_LOCKON
                if await self.ai.can_cast(unit, ability, target):
                    unit(ability, target)
                    self.lock_ons[target.tag] = self.ai.time
                    continue

            if close_enemies:
                in_attack_range: Units = close_enemies.in_attack_range_of(unit)
                if in_attack_range:
                    target = in_attack_range.closest_to(unit)
                    if not is_already_attacking(unit, target):
                        unit.attack(target)
                    continue

            if not close_enemies:
                move_to: Point2 = self.pathing.find_path_next_point(unit.position, pos, grid)
                unit.move(move_to)
                continue

            nearest: Unit = close_enemies.closest_to(unit)
            futile_to_kite: bool = (
                nearest.ground_range > unit.ground_range
                and (nearest.real_speed >= unit.real_speed or nearest.real_speed < 0.5)
            )
            if (
                not futile_to_kite
                and not self.pathing.is_position_safe(grid, unit.position)
                and not self._winning_locally(unit, units, close_enemies)
            ):
                self.move_to_safety(unit, grid)
                continue

            if not is_already_attacking(unit, nearest):
                unit.attack(nearest)

    @staticmethod
    def pick_lockon_target(enemies: Units) -> Unit:
        """Prefer high-value skytoss air if any is lockable, else lowest effective HP like our other unit classes."""
        priority: Units = enemies.of_type(SKYTOSS_TYPES)
        pool: Units = priority if priority else enemies
        return min(pool, key=lambda e: (e.health + e.shield, e.tag))
