import numpy as np
from typing import Optional
from bot.pathing.consts import ALL_STRUCTURES, ATTACK_TARGET_IGNORE, DANGEROUS_STRUCTURES
from bot.pathing.order_utils import is_already_attacking, is_already_attack_moving_to
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
        self.matrices = {}    # register matrices to let other ravens know to matrix something else

    async def handle_attackers(self, units: Units, attack_target: Point2) -> None:
        grid = self.pathing.air_grid

        # removing too old commands
        to_remove_mat = []
        for k in self.matrices.keys():
            if self.ai.time - self.matrices[k] > 10: # free the unit after 10 seconds
                to_remove_mat.append(k)
        for k in to_remove_mat:
            self.matrices.pop(k, None)

        for unit in units:
            if await self._try_cast_ability(unit):
                continue

            # in danger, run away
            if not self.pathing.is_position_safe(grid, unit.position):
                self.move_to_safety(unit, grid)
                continue

            # get to the target
            if self.ai.units.not_flying.amount > 0:
                pos = self.ai.units.not_flying.closest_to(attack_target).position
                if not is_already_attack_moving_to(unit, pos):
                    unit.attack(pos)
            else:
                if not is_already_attack_moving_to(unit, attack_target):
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
        Path to pos, but still cast Auto-Turret/Interference Matrix on anything worthwhile while
        holding - there's no reason to withhold these just because the army hasn't committed to
        a full attack yet, and this was the only place a Raven could never actually use them.
        Also retreats from danger first, same as handle_attackers already does - a Raven can't
        fight back, so standing still in a dangerous spot while "holding" was never useful.
        """
        grid = self.pathing.air_grid
        for unit in units:
            if await self._try_cast_ability(unit):
                continue
            if not self.pathing.is_position_safe(grid, unit.position):
                self.move_to_safety(unit, grid)
                continue
            move_to: Point2 = self.pathing.find_path_next_point(unit.position, pos, grid)
            unit.move(move_to)

    async def _try_cast_ability(self, unit: Unit) -> bool:
        """True if this unit is busy with (or just started) an ability this step and shouldn't
        get any other order right now - shared so handle_attackers and retreat_to can't drift."""
        # if the order target is an int, it means that we want to cast an ability on a unit
        if isinstance(unit.order_target, int):
            return True
        # we also skip it if we're still approaching/placing an auto turret - checked via the
        # order's ability rather than matching order_target against a remembered Point2: the
        # position the game echoes back for an in-progress order round-trips through float32 and
        # can differ from what we sent by a hair, which silently broke a dict-membership check
        # (Point2's __eq__ tolerates that drift but __hash__ doesn't, so `in` looked in the wrong
        # bucket and never matched) - this is exactly why turrets kept getting re-targeted instead
        # of ever actually landing
        if unit.is_using_ability(AbilityId.BUILDAUTOTURRET_AUTOTURRET):
            return True

        if self.ai.enemy_race == Race.Terran and await self.raven_vs_terran(unit):
            return True
        if self.ai.enemy_race == Race.Protoss and await self.raven_vs_protoss(unit):
            return True
        if self.ai.enemy_race == Race.Zerg and await self.raven_vs_zerg(unit):
            return True
        return False

    async def raven_vs_terran(self, unit: Unit):
        # only_check_energy_and_cooldown: this is a "do we have anything worth matrixing" pre-check,
        # before any specific enemy has been picked to target it with - can_cast's normal range
        # validation requires an actual target (Unit/Point2) and always returns False without one
        # for a targeted ability like this, which was silently skipping Matrix entirely every time
        if not await self.ai.can_cast(unit, AbilityId.EFFECT_INTERFERENCEMATRIX, only_check_energy_and_cooldown=True) or unit.energy >= 125: # if there is nothing to matrix, at some point still spend energy
            return await self.raven_vs_zerg(unit)

        if self.ai.enemy_units.amount == 0:
            return False

        for i in [UnitTypeId.SIEGETANKSIEGED, UnitTypeId.THOR, UnitTypeId.BATTLECRUISER]:
            if await self.matrix_unit(unit, i):
                return True

        return False


    async def raven_vs_protoss(self, unit: Unit):
        if not await self.ai.can_cast(unit, AbilityId.EFFECT_INTERFERENCEMATRIX, only_check_energy_and_cooldown=True) or unit.energy >= 125: # if there is nothing to matrix, at some point still spend energy
            return await self.raven_vs_zerg(unit)

        if self.ai.enemy_units.amount == 0:
            return False

        for i in [UnitTypeId.COLOSSUS, UnitTypeId.CARRIER, UnitTypeId.ARCHON, UnitTypeId.IMMORTAL, UnitTypeId.WARPPRISM]:
            if await self.matrix_unit(unit, i):
                return True

        return False


    async def raven_vs_zerg(self, unit: Unit):
        # same only_check_energy_and_cooldown reasoning as the Matrix pre-checks above - no
        # specific placement chosen yet, so there's no target to validate range against
        if not await self.ai.can_cast(unit, AbilityId.BUILDAUTOTURRET_AUTOTURRET, only_check_energy_and_cooldown=True):
            return False

        valid_enemies: Units = self.ai.enemy_units.filter(lambda u: u.type_id not in ATTACK_TARGET_IGNORE)
        if valid_enemies.amount == 0:
            return False

        can_place = None
        closest_dist = 10000
        enemy: Unit = valid_enemies.closest_to(unit.position)
        if enemy is not None and enemy.distance_to(unit) < 10:
            for x in range(int(enemy.position.x - 3), int(enemy.position.x + 4)):
                for y in range(int(enemy.position.y - 3), int(enemy.position.y + 4)):
                    pos = Point2((x, y))
                    if await self.ai.can_place_single(UnitTypeId.AUTOTURRET, pos):
                        dist = unit.distance_to(pos)
                        if can_place is None or dist < closest_dist:
                            can_place = pos
                            closest_dist = dist

        # the placement search above only checks terrain/vision rules (can_place_single) - it says
        # nothing about whether that spot is actually within the raven's own cast range. Casting at
        # an unreachable point isn't just ineffective, it's silently ineffective: the order gets
        # dropped rather than the raven approaching first, so this was leaving ravens stuck
        # re-picking the same out-of-range spot forever, never actually placing anything
        if can_place is not None and await self.ai.can_cast(unit, AbilityId.BUILDAUTOTURRET_AUTOTURRET, can_place):
            unit(AbilityId.BUILDAUTOTURRET_AUTOTURRET, can_place)
            return True

        return False


    async def matrix_unit(self, unit: Unit, type: UnitTypeId) -> bool:
        enemy_units = self.ai.enemy_units(type)

        if enemy_units.amount == 0:
            return False

        counter = 0
        closest = enemy_units.sorted_by_distance_to(unit)
        while(counter < closest.amount and closest[counter].tag in self.matrices.keys()):
            counter += 1

        if counter >= closest.amount:
            return False

        closest = closest[counter]
        # can_cast (with the real target this time) replaces the old hardcoded "< 13" guess with
        # the ability's actual cast range from game data
        if await self.ai.can_cast(unit, AbilityId.EFFECT_INTERFERENCEMATRIX, closest):
            unit(AbilityId.EFFECT_INTERFERENCEMATRIX, closest)
            self.matrices[closest.tag] = self.ai.time # save time at which we casted to free the unit later
            return True

        return False
