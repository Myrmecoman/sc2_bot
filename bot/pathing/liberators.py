import numpy as np
from typing import Optional

from bot.pathing.consts import ATTACK_TARGET_IGNORE_WITH_WORKERS
from bot.pathing.order_utils import is_already_attack_moving_to
from bot.pathing.pathing import Pathing

from sc2.bot_ai import BotAI
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId


# ---------------------------------------------------------------------------
# Liberator behaviour
# ---------------------------------------------------------------------------

# Once we COMMAND the Liberator to siege, it cannot be ordered to unsiege
# until this much game time has passed.
#
# This timer starts at the MORPH_LIBERATORAGMODE command, NOT when
# UnitTypeId.LIBERATORAG happens to appear in the observation.
MIN_AG_DURATION = 3.0
# Once the minimum AG lock has expired, keep AG mode if there is something
# worthwhile close enough to shoot.
AG_HOLD_CHECK_RANGE = 6.0
# Put the desired AG position this far from the target.
AG_OFFSET = 4.0
# Stay slightly inside the actual ability range.
CAST_BUFFER = 0.25
# Do not spam morph commands.
MORPH_COMMAND_COOLDOWN = 0.5


class Liberators:
    """
    Liberator controller.

    Fighter mode:
        - Siege enemy Siege Tanks first.
        - If there are no tanks, siege another worthwhile enemy.
        - If there is nothing to siege, behave normally with the army.

    Defender mode:
        - Once we issue the siege command, AG is LOCKED for MIN_AG_DURATION.
        - After that, remain AG while worthwhile enemies are nearby.
        - Unsiege only when there is nothing worthwhile nearby.

    IMPORTANT:
        The AG lock starts when MORPH_LIBERATORAGMODE is issued.
        We do not rely on observing LIBERATORAG to start the timer.
    """

    def __init__(self, ai: BotAI, pathing: Pathing):
        self.ai: BotAI = ai
        self.pathing: Pathing = pathing

        self.ag_cast_range: float = (
            self.ai.game_data.abilities[
                AbilityId.MORPH_LIBERATORAGMODE.value
            ]._proto.cast_range
        )

        # ------------------------------------------------------------------
        # AG state
        # ------------------------------------------------------------------

        # unit tag -> earliest game time at which we may unsiege
        #
        # This is created AT THE MOMENT WE ISSUE THE SIEGE COMMAND.
        self.ag_locked_until: dict[int, float] = {}

        # Last morph command issued for each Liberator.
        self.last_morph_command: dict[int, float] = {}

    # ======================================================================
    # STATE
    # ======================================================================

    def _ag_is_locked(self, unit: Unit) -> bool:
        """
        True if this Liberator is still inside its mandatory AG hold period.
        """

        locked_until = self.ag_locked_until.get(unit.tag)

        if locked_until is None:
            return False

        return self.ai.time < locked_until

    def _can_morph(self, unit: Unit) -> bool:
        """
        Small command cooldown so we don't spam morph orders.
        """

        last = self.last_morph_command.get(unit.tag)

        if last is None:
            return True

        return (
            self.ai.time - last
            >= MORPH_COMMAND_COOLDOWN
        )

    def _remember_morph(self, unit: Unit) -> None:
        self.last_morph_command[unit.tag] = self.ai.time

    def _lock_ag(self, unit: Unit) -> None:
        """
        Start the AG hold timer immediately when we issue the siege command.
        """

        self.ag_locked_until[unit.tag] = (
            self.ai.time + MIN_AG_DURATION
        )

    def _clear_ag_state(self, unit: Unit) -> None:
        self.ag_locked_until.pop(unit.tag, None)

    # ======================================================================
    # TARGET SELECTION
    # ======================================================================

    def _siege_tanks(self) -> Units:
        """
        Enemy Siege Tanks have absolute priority.
        """

        return self.ai.enemy_units.of_type(
            {
                UnitTypeId.SIEGETANK,
                UnitTypeId.SIEGETANKSIEGED,
            }
        )

    def _other_siege_targets(self) -> Units:
        """
        Fallback targets when there are no Siege Tanks.

        Workers / ignored targets are excluded.
        """

        return self.ai.enemy_units.filter(
            lambda u: (
                u.type_id
                not in ATTACK_TARGET_IGNORE_WITH_WORKERS
                and u.type_id
                not in {
                    UnitTypeId.SIEGETANK,
                    UnitTypeId.SIEGETANKSIEGED,
                }
            )
        )

    def _find_siege_target(
        self,
        unit: Unit,
    ) -> Optional[Unit]:
        """
        Target priority:

            1. Siege Tank
            2. Anything else worthwhile

        We do NOT remember the target after sieging.
        """

        tanks = self._siege_tanks()

        if tanks:
            return tanks.closest_to(unit)

        enemies = self._other_siege_targets()

        if enemies:
            return enemies.closest_to(unit)

        return None

    # ======================================================================
    # HANDLE ATTACKERS
    # ======================================================================

    async def handle_attackers(
        self,
        units: Units,
        attack_target: Point2,
    ) -> None:

        grid = self.pathing.air_grid

        for unit in units:

            # --------------------------------------------------------------
            # Defender Mode
            # --------------------------------------------------------------

            if unit.type_id == UnitTypeId.LIBERATORAG:

                await self._maybe_leave_ag(unit)

                continue

            # --------------------------------------------------------------
            # Fighter Mode
            # --------------------------------------------------------------

            if await self._try_siege(
                unit,
                grid,
            ):
                continue

            # --------------------------------------------------------------
            # No siege target
            # --------------------------------------------------------------

            if not self.pathing.is_position_safe(
                grid,
                unit.position,
            ):
                self.move_to_safety(
                    unit,
                    grid,
                )
                continue

            if not is_already_attack_moving_to(
                unit,
                attack_target,
            ):
                unit.attack(attack_target)

    # ======================================================================
    # RETREAT
    # ======================================================================

    async def retreat_to(
        self,
        units: Units,
        pos: Point2,
    ):
        grid = self.pathing.air_grid

        for unit in units:

            # --------------------------------------------------------------
            # Defender Mode
            # --------------------------------------------------------------

            if unit.type_id == UnitTypeId.LIBERATORAG:

                await self._maybe_leave_ag(unit)

                continue

            # --------------------------------------------------------------
            # Fighter Mode
            # --------------------------------------------------------------

            if await self._try_siege(
                unit,
                grid,
            ):
                continue

            if not self.pathing.is_position_safe(
                grid,
                unit.position,
            ):
                self.move_to_safety(
                    unit,
                    grid,
                )
                continue

            move_to = self.pathing.find_path_next_point(
                unit.position,
                pos,
                grid,
            )

            unit.move(move_to)

    # ======================================================================
    # FIGHTER -> AG
    # ======================================================================

    async def _try_siege(
        self,
        unit: Unit,
        grid: np.ndarray,
    ) -> bool:
        """
        Try to put a Fighter-mode Liberator into Defender Mode.

        Tanks have priority.

        Once the morph command is successfully issued, the AG lock starts
        IMMEDIATELY.
        """

        # Don't spam commands while a previous morph command is still fresh.
        if not self._can_morph(unit):
            return True

        target = self._find_siege_target(unit)

        if target is None:
            return False

        # Don't fly into an unsafe position just to siege.
        if not self.pathing.is_position_safe(
            grid,
            unit.position,
        ):
            return False

        # --------------------------------------------------------------
        # Calculate desired AG position
        # --------------------------------------------------------------

        siege_pos = target.position.towards(
            unit.position,
            AG_OFFSET,
        )

        cast_range = (
            self.ag_cast_range
            - CAST_BUFFER
        )

        # --------------------------------------------------------------
        # Close enough to morph
        # --------------------------------------------------------------

        if unit.distance_to(siege_pos) <= cast_range:

            if not await self.ai.can_cast(
                unit,
                AbilityId.MORPH_LIBERATORAGMODE,
                siege_pos,
            ):
                # We are in position, but cannot cast yet.
                #
                # IMPORTANT:
                # Do NOT move away.
                return True

            # ----------------------------------------------------------
            # ISSUE THE SIEGE COMMAND
            # ----------------------------------------------------------

            unit(
                AbilityId.MORPH_LIBERATORAGMODE,
                siege_pos,
            )

            self._remember_morph(unit)

            # ----------------------------------------------------------
            # THIS IS THE IMPORTANT FIX
            # ----------------------------------------------------------
            #
            # Start the AG lock RIGHT NOW.
            #
            # We do NOT wait for:
            #
            #     unit.type_id == LIBERATORAG
            #
            # because the observation of the transformation can occur
            # later and state tracking should not determine whether the
            # unit immediately gets an unsiege command.
            self._lock_ag(unit)

            return True

        # --------------------------------------------------------------
        # Too far away -> approach
        # --------------------------------------------------------------

        approach_pos = siege_pos.towards(
            unit.position,
            cast_range,
        )

        move_to = self.pathing.find_path_next_point(
            unit.position,
            approach_pos,
            grid,
        )

        unit.move(move_to)

        return True

    # ======================================================================
    # AG -> FIGHTER
    # ======================================================================

    async def _maybe_leave_ag(
        self,
        unit: Unit,
    ) -> bool:
        """
        Decide whether an AG Liberator should unsiege.

        There is NO air-grid safety check here.

        Most importantly:

            if ag_locked_until has not expired:
                DO NOTHING.

        This prevents the immediate siege -> unsiege behaviour.
        """

        # --------------------------------------------------------------
        # HARD AG LOCK
        # --------------------------------------------------------------
        #
        # This is the first check.
        #
        # Nothing else is allowed to cause an unsiege before this expires.
        #

        if self._ag_is_locked(unit):
            return False

        # --------------------------------------------------------------
        # After the lock expires, look for worthwhile targets nearby.
        # --------------------------------------------------------------

        enemies = self.ai.enemy_units.filter(
            lambda u: (
                u.type_id
                not in ATTACK_TARGET_IGNORE_WITH_WORKERS
            )
        )

        if enemies.closer_than(
            AG_HOLD_CHECK_RANGE,
            unit,
        ):
            # There is still something to shoot.
            return False

        # --------------------------------------------------------------
        # Nothing worthwhile nearby -> unsiege
        # --------------------------------------------------------------

        if not self._can_morph(unit):
            return True

        unit(
            AbilityId.MORPH_LIBERATORAAMODE
        )

        self._remember_morph(unit)

        # Remove the lock after actually deciding to leave AG.
        self._clear_ag_state(unit)

        return True

    # ======================================================================
    # SAFETY
    # ======================================================================

    def move_to_safety(
        self,
        unit: Unit,
        grid: np.ndarray,
    ):
        safe_spot = self.pathing.find_closest_safe_spot(
            unit.position,
            grid,
        )

        move_to = self.pathing.find_path_next_point(
            unit.position,
            safe_spot,
            grid,
        )

        unit.move(move_to)
