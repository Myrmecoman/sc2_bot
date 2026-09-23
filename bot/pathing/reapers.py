from typing import Optional

import numpy as np
from bot.pathing.consts import ALL_STRUCTURES, ATTACK_TARGET_IGNORE, DANGEROUS_STRUCTURES
from bot.pathing.order_utils import is_already_attacking, is_already_attack_moving_to
from bot.pathing.pathing import Pathing
from sc2.bot_ai import BotAI
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

HEAL_AT_LESS_THAN: float = 0.5
HIDDEN_BASE_SCOUT_INTERVAL: float = 30.0  # move on to the next candidate expansion this often while hunting


class Reapers:
    def __init__(self, ai: BotAI, pathing: Pathing):
        self.ai: BotAI = ai
        self.pathing: Pathing = pathing
        self.grid: np.ndarray = None

        self.reaper_grenade_range: float = self.ai.game_data.abilities[
            AbilityId.KD8CHARGE_KD8CHARGE.value
        ]._proto.cast_range

        # cycles through expansion locations looking for the enemy's actual base, used only when
        # the early worker-scout (bot/scouting.py) never confirmed it
        self.hidden_base_scout_index: int = 0
        self.hidden_base_scout_since: float = 0.0


    @property
    def get_heal_spot(self) -> Point2:
        return self.pathing.find_closest_safe_spot(self.ai.game_info.map_center, self.pathing.reaper_grid)


    async def handle_attackers(self, units: Units) -> None:

        attack_target: Point2 = self.get_attack_target()
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
                if not is_already_attacking(unit, target):
                    unit.attack(target)
                continue

            # no target and in danger, run away - unless the thing threatening us both outranges
            # AND isn't slower than us, in which case backing off between shots is futile (can't
            # out-range or out-run it) and just wastes movement; hold and trade instead. Reapers
            # are fast enough that this is a no-op against almost everything - it only kicks in
            # for the rare case something both outranges and outruns them. real_speed (not
            # movement_speed) because that accounts for buffs/upgrades currently active. Also
            # futile against a near-immobile target (a sieged tank, a defensive structure) even
            # though it "loses" the speed check - see bio.py's identical check for the full
            # reasoning: whenever something outranges us, escaping it means escaping its whole
            # threat radius, and a rooted target's radius never moves, so a full
            # retreat-and-reapproach every cycle is strictly worse than holding and trading.
            futile_to_kite: bool = (
                target is not None
                and target.ground_range > unit.ground_range
                and (target.real_speed >= unit.real_speed or target.real_speed < 0.5)
            )
            if not futile_to_kite and not self.pathing.is_position_safe(grid, unit.position):
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
    

    def get_attack_target(self) -> Point2:
        if enemy_units := self.ai.enemy_units.filter(
            lambda u: u.type_id not in ATTACK_TARGET_IGNORE
            and not u.is_flying
            and not u.is_cloaked
            and not u.is_hallucination):
            return enemy_units.closest_to(self.ai.start_location).position
        elif enemy_structures := self.ai.enemy_structures:
            return enemy_structures.closest_to(self.ai.start_location).position
        elif not self.ai.enemy_base_scouted:
            # the early worker-scout never confirmed the enemy's main (died en route, or they
            # just aren't there) - hunt expansions with our own vision instead of sitting at a
            # possibly-empty default location for the rest of the game
            candidate = self._next_hidden_base_candidate()
            if candidate is not None:
                return candidate
        return self.ai.enemy_start_locations[0]


    def _next_hidden_base_candidate(self) -> Optional[Point2]:
        expansions = self.ai.expansion_locations_list
        if not expansions:
            return None
        if self.ai.time - self.hidden_base_scout_since > HIDDEN_BASE_SCOUT_INTERVAL:
            self.hidden_base_scout_since = self.ai.time
            self.hidden_base_scout_index = (self.hidden_base_scout_index + 1) % len(expansions)
        return expansions[self.hidden_base_scout_index]


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
            and unit.distance_to(r) < self.reaper_grenade_range
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
