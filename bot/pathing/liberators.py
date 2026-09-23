import numpy as np
from typing import Dict
from bot.pathing.consts import ATTACK_TARGET_IGNORE_WITH_WORKERS
from bot.pathing.order_utils import is_already_attack_moving_to
from bot.pathing.pathing import Pathing
from sc2.bot_ai import BotAI
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId

MIN_AG_DURATION = 3.0    # once sieged (Defender Mode), hold it this long before being allowed to un-morph - stops flip-flopping the way tanks.py's MIN_SIEGE_DURATION does
AG_HOLD_CHECK_RANGE = 6.0  # once sieged, still worth holding this position as long as something enemy is within this of it


class Liberators:
    """Liberators specifically hunt enemy Siege Tanks: morph to Defender Mode (AG) on top of a
    tank cluster and let the splash do the work, rather than trying to be a general-purpose unit.
    Tanks.py has the other half of this - see its _liberator_guard_point - biasing our own tanks
    toward guarding a sieged Liberator from the marines that would otherwise pick it off while it
    can't move or fight back against ground units at all."""

    def __init__(self, ai: BotAI, pathing: Pathing):
        self.ai: BotAI = ai
        self.pathing: Pathing = pathing
        self.ag_since: Dict[int, float] = {}  # unit tag -> game time it morphed to Defender Mode, cleared once it un-morphs
        self.ag_cast_range: float = self.ai.game_data.abilities[AbilityId.MORPH_LIBERATORAGMODE.value]._proto.cast_range

    def _track_ag_state(self, unit: Unit) -> None:
        if unit.type_id == UnitTypeId.LIBERATORAG:
            if unit.tag not in self.ag_since:
                self.ag_since[unit.tag] = self.ai.time
        else:
            self.ag_since.pop(unit.tag, None)

    def _can_leave_ag(self, unit: Unit) -> bool:
        held_since = self.ag_since.get(unit.tag)
        return held_since is None or self.ai.time - held_since >= MIN_AG_DURATION

    def _nearby_enemy_tanks(self, unit: Unit) -> Units:
        return self.ai.enemy_units.of_type({UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED}).closer_than(self.ag_cast_range, unit)

    async def handle_attackers(self, units: Units, attack_target: Point2) -> None:
        grid = self.pathing.air_grid  # still a flying unit in both modes - vulnerable to anything with anti-air, e.g. Marines

        for unit in units:
            self._track_ag_state(unit)

            if unit.type_id == UnitTypeId.LIBERATORAG:
                # either it un-morphs (danger/nothing left to hit) or it stays sieged and the
                # engine fires on its own - no other order to issue for it either way
                await self._maybe_leave_ag(unit, grid)
                continue

            if await self._try_siege_tanks(unit, grid):
                continue

            # no tanks worth sieging right now - not a dedicated hunter otherwise, just stay with
            # the army like any other support unit (Medivac/Raven) rather than freelancing.
            # attack-move (not plain move): Fighter mode still has a real, if secondary,
            # anti-air weapon and may as well use it opportunistically while travelling
            if not self.pathing.is_position_safe(grid, unit.position):
                self.move_to_safety(unit, grid)
                continue
            if not is_already_attack_moving_to(unit, attack_target):
                unit.attack(attack_target)

    async def retreat_to(self, units: Units, pos: Point2):
        """
        Hold near pos, but still snipe enemy Siege Tanks on sight while waiting - sieging on tanks
        is valuable whether or not the main army has committed to a full push, same reasoning
        Tanks.retreat_to already uses for proactively digging in.
        """
        grid = self.pathing.air_grid
        for unit in units:
            self._track_ag_state(unit)

            if unit.type_id == UnitTypeId.LIBERATORAG:
                await self._maybe_leave_ag(unit, grid)
                continue

            if await self._try_siege_tanks(unit, grid):
                continue

            if not self.pathing.is_position_safe(grid, unit.position):
                self.move_to_safety(unit, grid)
                continue

            move_to: Point2 = self.pathing.find_path_next_point(unit.position, pos, grid)
            unit.move(move_to)


    async def _try_siege_tanks(self, unit: Unit, grid: np.ndarray) -> bool:
        """For a mobile (Fighter mode) Liberator: hunt enemy Siege Tanks and
        morph into Defender Mode at a point 4 units away from the tank.

        The Liberator approaches only far enough for the desired Defender Mode
        position to be within cast range. It does not approach the tank itself.
        """
        AG_OFFSET = 4.0
        CAST_BUFFER = 0.25

        tanks: Units = self.ai.enemy_units.of_type({
            UnitTypeId.SIEGETANK,
            UnitTypeId.SIEGETANKSIEGED,
        })

        if not tanks:
            return False

        if not self.pathing.is_position_safe(grid, unit.position):
            return False

        # Pick the closest tank.
        target: Unit = tanks.closest_to(unit)

        # The desired Defender Mode position is 4 units toward the Liberator
        # from the tank.
        siege_pos: Point2 = target.position.towards(
            unit.position,
            AG_OFFSET,
        )

        # If the desired siege position is within cast range, siege now.
        if unit.distance_to(siege_pos) <= self.ag_cast_range - CAST_BUFFER:
            if await self.ai.can_cast(
                unit,
                AbilityId.MORPH_LIBERATORAGMODE,
                siege_pos,
            ):
                unit(
                    AbilityId.MORPH_LIBERATORAGMODE,
                    siege_pos,
                )
                return True

            # We are close enough to cast, but the ability isn't currently
            # available. Don't issue another movement order.
            return False

        # We are too far away to cast at the desired siege position.
        #
        # Move toward the position from which siege_pos will be castable.
        # This keeps the Liberator approximately:
        #
        #     CAST_RANGE
        #          |
        #          v
        #    Lib -------- siege_pos ---- 4 ---- Tank
        #
        # rather than moving directly onto the tank.
        approach_distance: float = (
            self.ag_cast_range - CAST_BUFFER
        )

        approach_pos: Point2 = siege_pos.towards(
            unit.position,
            approach_distance,
        )

        move_to: Point2 = self.pathing.find_path_next_point(
            unit.position,
            approach_pos,
            grid,
        )

        unit.move(move_to)
        return True


    async def _maybe_leave_ag(self, unit: Unit, grid: np.ndarray) -> bool:
        """For a sieged (Defender Mode) Liberator: un-morph and retreat if it's genuinely in
        danger (never gated behind the minimum hold, same as Tanks - real danger always wins), or
        if nothing enemy is left near it worth staying for once the minimum hold has passed.
        Returns True if it un-morphed (caller should stop processing this unit this step - the
        unit is mid-transformation and can't take another order yet anyway)."""
        safe: bool = self.pathing.is_position_safe(grid, unit.position)
        still_worth_it: bool = self.ai.enemy_units.filter(
            lambda u: u.type_id not in ATTACK_TARGET_IGNORE_WITH_WORKERS
        ).closer_than(AG_HOLD_CHECK_RANGE, unit).amount > 0

        if not safe or (not still_worth_it and self._can_leave_ag(unit)):
            if not unit.is_using_ability(AbilityId.MORPH_LIBERATORAAMODE):
                unit(AbilityId.MORPH_LIBERATORAAMODE)
            return True
        return False

    def move_to_safety(self, unit: Unit, grid: np.ndarray):
        """
        Find a close safe spot on our grid
        Then path to it
        """
        safe_spot: Point2 = self.pathing.find_closest_safe_spot(unit.position, grid)
        move_to: Point2 = self.pathing.find_path_next_point(unit.position, safe_spot, grid)
        unit.move(move_to)
