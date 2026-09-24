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


MIN_AG_DURATION = 3.0
# Once sieged, keep AG mode while a worthwhile enemy is nearby.
AG_HOLD_CHECK_RANGE = 6.0
# Desired distance from the enemy when choosing the AG position.
AG_OFFSET = 4.0
# Don't try to cast right on the edge of the ability range.
CAST_BUFFER = 0.25
# Prevent repeatedly issuing morph commands during transformation.
MORPH_COMMAND_COOLDOWN = 0.5


class Liberators:
    """
    Liberators prioritize enemy Siege Tanks.

    Fighter mode:
        1. Find a Siege Tank if one exists.
        2. Otherwise find another worthwhile enemy.
        3. Move into position and morph to Defender Mode.

    Defender mode:
        - Hold for at least MIN_AG_DURATION.
        - Stay sieged while worthwhile enemies remain nearby.
        - Unsiege once there is nothing worthwhile to shoot.

    We intentionally do NOT remember which unit caused the siege.
    """

    def __init__(self, ai: BotAI, pathing: Pathing):
        self.ai: BotAI = ai
        self.pathing: Pathing = pathing

        self.ag_cast_range: float = (
            self.ai.game_data.abilities[
                AbilityId.MORPH_LIBERATORAGMODE.value
            ]._proto.cast_range
        )

        # Game time at which each Liberator entered AG mode.
        self.ag_since: dict[int, float] = {}

        # Last time we issued either morph command.
        self.last_morph_command: dict[int, float] = {}

    # ======================================================================
    # STATE
    # ======================================================================

    def _track_ag_state(self, unit: Unit) -> None:
        if unit.type_id == UnitTypeId.LIBERATORAG:
            self.ag_since.setdefault(unit.tag, self.ai.time)
        else:
            # Only clear once we actually see the unit back in Fighter mode.
            self.ag_since.pop(unit.tag, None)

    def _can_leave_ag(self, unit: Unit) -> bool:
        since = self.ag_since.get(unit.tag)

        if since is None:
            return False

        return self.ai.time - since >= MIN_AG_DURATION

    def _can_morph(self, unit: Unit) -> bool:
        last = self.last_morph_command.get(unit.tag)

        if last is None:
            return True

        return self.ai.time - last >= MORPH_COMMAND_COOLDOWN

    def _remember_morph(self, unit: Unit) -> None:
        self.last_morph_command[unit.tag] = self.ai.time

    # ======================================================================
    # TARGET SELECTION
    # ======================================================================

    def _siege_tanks(self) -> Units:
        return self.ai.enemy_units.of_type(
            {
                UnitTypeId.SIEGETANK,
                UnitTypeId.SIEGETANKSIEGED,
            }
        )

    def _other_siege_targets(self) -> Units:
        """
        Return worthwhile enemies that a Liberator AG can actually usefully
        siege on.

        Workers / ignored units are excluded.
        """
        return self.ai.enemy_units.filter(
            lambda u: (
                u.type_id not in ATTACK_TARGET_IGNORE_WITH_WORKERS
                and u.type_id
                not in {
                    UnitTypeId.SIEGETANK,
                    UnitTypeId.SIEGETANKSIEGED,
                }
            )
        )

    def _find_siege_target(self, unit: Unit) -> Optional[Unit]:
        """
        Siege Tanks ALWAYS have priority.

        If there is at least one tank, choose the closest tank.

        Otherwise choose the closest worthwhile enemy.
        """

        tanks = self._siege_tanks()

        if tanks:
            return tanks.closest_to(unit)

        enemies = self._other_siege_targets()

        if enemies:
            return enemies.closest_to(unit)

        return None

    # ======================================================================
    # MAIN ATTACK
    # ======================================================================

    async def handle_attackers(
        self,
        units: Units,
        attack_target: Point2,
    ) -> None:

        grid = self.pathing.air_grid

        for unit in units:
            self._track_ag_state(unit)

            # --------------------------------------------------------------
            # Defender Mode
            # --------------------------------------------------------------

            if unit.type_id == UnitTypeId.LIBERATORAG:
                await self._maybe_leave_ag(unit)
                continue

            # --------------------------------------------------------------
            # Fighter Mode -> try to siege something
            # --------------------------------------------------------------

            if await self._try_siege(unit, grid):
                continue

            # --------------------------------------------------------------
            # No siege target: behave like normal army support
            # --------------------------------------------------------------

            if not self.pathing.is_position_safe(
                grid,
                unit.position,
            ):
                self.move_to_safety(unit, grid)
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
            self._track_ag_state(unit)

            if unit.type_id == UnitTypeId.LIBERATORAG:
                await self._maybe_leave_ag(unit)
                continue

            if await self._try_siege(unit, grid):
                continue

            if not self.pathing.is_position_safe(
                grid,
                unit.position,
            ):
                self.move_to_safety(unit, grid)
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
        Find something to siege.

        Priority:
            Siege Tank
            -> anything else worthwhile

        Returns True if we handled the Liberator this frame.
        """

        if not self._can_morph(unit):
            return True

        target = self._find_siege_target(unit)

        if target is None:
            return False

        # Don't deliberately fly through unsafe airspace.
        if not self.pathing.is_position_safe(
            grid,
            unit.position,
        ):
            return False

        # --------------------------------------------------------------
        # Desired Defender Mode position
        # --------------------------------------------------------------

        siege_pos = target.position.towards(
            unit.position,
            AG_OFFSET,
        )

        cast_range = self.ag_cast_range - CAST_BUFFER

        # --------------------------------------------------------------
        # Already close enough to siege
        # --------------------------------------------------------------

        if unit.distance_to(siege_pos) <= cast_range:

            if not await self.ai.can_cast(
                unit,
                AbilityId.MORPH_LIBERATORAGMODE,
                siege_pos,
            ):
                # Don't overwrite the position with movement while waiting
                # for the ability to become available.
                return True

            unit(
                AbilityId.MORPH_LIBERATORAGMODE,
                siege_pos,
            )

            self._remember_morph(unit)

            return True

        # --------------------------------------------------------------
        # Approach the AG position
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
        Decide whether a Defender Mode Liberator should unsiege.

        We deliberately do NOT check the air safety grid here.

        A Liberator being exposed to AA while in AG mode is normal.
        If we used the air grid as an immediate unsiege condition, the
        Liberator could siege and instantly unsiege again.
        """

        # Never unsiege before the minimum hold duration.
        if not self._can_leave_ag(unit):
            return False

        # Is there anything worthwhile near the Liberator?
        enemies = self.ai.enemy_units.filter(
            lambda u: (
                u.type_id not in ATTACK_TARGET_IGNORE_WITH_WORKERS
            )
        )

        if enemies.closer_than(
            AG_HOLD_CHECK_RANGE,
            unit,
        ):
            # Something is still worth shooting.
            return False

        # Nothing worthwhile nearby -> return to Fighter Mode.
        if not self._can_morph(unit):
            return True

        unit(
            AbilityId.MORPH_LIBERATORAAMODE
        )

        self._remember_morph(unit)

        return True

    # ======================================================================
    # SAFETY MOVEMENT
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
