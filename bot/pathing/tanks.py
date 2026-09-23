import numpy as np
from typing import Dict, Optional
from bot.pathing.consts import ALL_STRUCTURES, ATTACK_TARGET_IGNORE_WITH_WORKERS, DANGEROUS_STRUCTURES
from bot.pathing.order_utils import is_already_attack_moving_to, spread_out_point
from bot.pathing.pathing import Pathing
from sc2.bot_ai import BotAI
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.ability_id import AbilityId

TANK_SPACING = 3.0            # tanks are big units with a wide splash radius - keep more distance between them than bio needs
TANK_HOLD_ARRIVAL_RANGE = 4.0 # close enough to the hold point to dig in proactively
MIN_SIEGE_DURATION = 3.0      # once sieged, hold it this long before being allowed to unsiege again - stops flip-flopping (and wasting the morph time) when a target just briefly leaves range
SIEGE_ENGAGE_RANGE = 11.0     # siege once an enemy is within this, not the full 13 sieged range
ENEMY_HOLD_RANGE = 14.0
LIBERATOR_GUARD_RADIUS = 9.0  # how close a tank should sit to a sieged Liberator to meaningfully screen it from approaching Marines
LIBERATOR_GUARD_MAX = 2       # don't pile more than this many tanks onto guarding one Liberator - other fights still need tanks too

class Tanks:
    def __init__(self, ai: BotAI, pathing: Pathing):
        self.ai: BotAI = ai
        self.pathing: Pathing = pathing
        self.siege_since: Dict[int, float] = {}  # unit tag -> game time it became sieged, cleared once it unsieges


    def _track_siege_state(self, unit: Unit) -> None:
        if unit.type_id == UnitTypeId.SIEGETANKSIEGED:
            if unit.tag not in self.siege_since:
                self.siege_since[unit.tag] = self.ai.time
        else:
            self.siege_since.pop(unit.tag, None)


    def _can_unsiege(self, unit: Unit, shootable_targets: Optional[Units] = None) -> bool:
        """
        Stay sieged if:
        1. There is a ground target the tank can shoot within 14 range, or
        2. The tank has been sieged for less than 3 seconds.

        Otherwise the tank may unsiege.
        """
        if shootable_targets is None:
            shootable_targets = self._get_shootable_ground_targets()
        # Keep siege mode while there is anything the tank can shoot
        # within the 14-range commitment distance.
        if (shootable_targets.amount > 0 and shootable_targets.closest_distance_to(unit) <= ENEMY_HOLD_RANGE):
            return False
        # Always complete the minimum siege duration
        held_since = self.siege_since.get(unit.tag)
        timeIsUp = held_since is None or self.ai.time - held_since >= MIN_SIEGE_DURATION
        return timeIsUp


    def _get_shootable_ground_targets(self):
        shootable_targets: Units = (
        self.ai.enemy_units.filter(lambda u: (not u.is_flying and u.type_id not in ATTACK_TARGET_IGNORE_WITH_WORKERS)) | self.ai.enemy_structures.not_flying)
        return shootable_targets


    def _liberator_guard_point(self) -> Optional[Point2]:
        """Position of the sieged (Defender Mode) friendly Liberator that most needs tank cover
        right now - fewer than LIBERATOR_GUARD_MAX tanks already near it - or None if every
        currently-sieged Liberator already has enough, or there aren't any. A rooted Liberator
        can't fight or flee a Marine closing in on it at all, so a tank standing nearby to kill
        that Marine first is the only thing keeping the trade in our favor. Computed once per
        handle_attackers/retreat_to call, not per unit, to avoid a fresh unit-count scan for
        every single tank."""
        libs_ag: Units = self.ai.units(UnitTypeId.LIBERATORAG)
        if not libs_ag:
            return None
        tanks: Units = self.ai.units.of_type({UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED})
        for lib in libs_ag:
            if tanks.closer_than(LIBERATOR_GUARD_RADIUS, lib).amount < LIBERATOR_GUARD_MAX:
                return lib.position
        return None


    async def handle_attackers(self, units: Units, attack_target: Point2) -> None:
        grid = self.pathing.ground_grid
        guard_point: Optional[Point2] = self._liberator_guard_point()

        for unit in units:
            self._track_siege_state(unit)

            # tanks can't hit air at all, sieged or not - a lifted structure has to be excluded too
            close_enemies: Units = self.ai.enemy_units.filter(lambda u: not u.is_flying and u.type_id not in ATTACK_TARGET_IGNORE_WITH_WORKERS) | self.ai.enemy_structures.not_flying#.filter(lambda s: s.distance_to(unit) < 15.0 and s.type_id in DANGEROUS_STRUCTURES)

            # handle tanks
            if unit.type_id == UnitTypeId.SIEGETANK and close_enemies.amount > 0 and close_enemies.closest_distance_to(unit) <= SIEGE_ENGAGE_RANGE:
                if not unit.is_using_ability(AbilityId.SIEGEMODE_SIEGEMODE):
                    unit(AbilityId.SIEGEMODE_SIEGEMODE)
                continue
            if unit.type_id == UnitTypeId.SIEGETANKSIEGED:
                # always continue while sieged, whether or not it actually unsieges this step - a
                # sieged tank can't move or attack-move at all (the engine fires on its own), so
                # falling through to the movement code below (as this used to, whenever the
                # unsiege condition was false - i.e. the common case of still fighting) was issuing
                # move/attack orders to a unit that can't execute them
                if (close_enemies.amount == 0 or close_enemies.closest_distance_to(unit) >= 14) and self._can_unsiege(unit):
                    if not unit.is_using_ability(AbilityId.UNSIEGE_UNSIEGE):
                        unit(AbilityId.UNSIEGE_UNSIEGE)
                continue

            # no target and in danger, run away
            if not self.pathing.is_position_safe(grid, unit.position):
                self.move_to_safety(unit, grid)
                continue

            # get to the target - guard an under-protected sieged Liberator if we have one (it's
            # rooted and defenseless against the Marines that would otherwise kill it), otherwise
            # head for the fight as usual. Either way, spread out a bit so we're not all stacked
            # on the same tile - both to spread out our own splash and to not present one juicy
            # AOE target
            spread_point: Point2 = spread_out_point(unit, units, guard_point if guard_point is not None else attack_target, radius=TANK_SPACING, nudge=TANK_SPACING)
            if not is_already_attack_moving_to(unit, spread_point):
                unit.attack(spread_point)


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
        Path to pos. While holding (not actually in danger), dig in proactively once close to the
        hold point instead of only ever reacting once an enemy is already nearby - the whole point
        is to already be sieged and ready by the time the enemy arrives, including when our own
        units kite back through here. Once dug in and safe, stays sieged even with nothing visible
        right now rather than popping in and out every time a target briefly leaves detection range.
        """
        grid = self.pathing.ground_grid
        # an under-protected sieged Liberator takes over as the effective hold point - guarding
        # it is more urgent than holding a static rally point, same reasoning as handle_attackers
        guard_point: Optional[Point2] = self._liberator_guard_point()
        effective_pos: Point2 = guard_point if guard_point is not None else pos

        for unit in units:
            self._track_siege_state(unit)

            close_enemies: Units = self.ai.enemy_units.filter(lambda u: not u.is_flying and u.type_id not in ATTACK_TARGET_IGNORE_WITH_WORKERS) | self.ai.enemy_structures.not_flying
            safe: bool = self.pathing.is_position_safe(grid, unit.position)
            at_hold_point: bool = unit.position.distance_to(effective_pos) <= TANK_HOLD_ARRIVAL_RANGE

            if unit.type_id == UnitTypeId.SIEGETANKSIEGED:
                # only unsiege if we actually need to move - the hold point shifted (gated,
                # so a barely-sieged tank doesn't immediately pop back up over a minor reposition)
                if not at_hold_point and self._can_unsiege(unit):
                    if not unit.is_using_ability(AbilityId.UNSIEGE_UNSIEGE):
                        unit(AbilityId.UNSIEGE_UNSIEGE)
                continue

            if unit.type_id == UnitTypeId.SIEGETANK and safe:
                close_enough_to_fight = close_enemies.amount > 0 and close_enemies.closest_distance_to(unit) <= SIEGE_ENGAGE_RANGE
                if close_enough_to_fight or at_hold_point:
                    if not unit.is_using_ability(AbilityId.SIEGEMODE_SIEGEMODE):
                        unit(AbilityId.SIEGEMODE_SIEGEMODE)
                    continue

            if not safe:
                self.move_to_safety(unit, grid)
                continue

            spread_point: Point2 = spread_out_point(unit, units, effective_pos, radius=TANK_SPACING, nudge=TANK_SPACING)
            move_to: Point2 = self.pathing.find_path_next_point(unit.position, spread_point, grid)
            unit.move(move_to)
