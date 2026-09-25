"""Per-step snapshot of everything unit controllers need, computed once instead of once per unit."""
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np

from ares.consts import UnitTreeQueryType
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from sc2.ids.upgrade_id import UpgradeId

from bot.army.consts import ATTACK_TARGET_IGNORE, BANELING_KITE_MARGIN, BANELING_TYPES, LOCAL_FIGHT_RADIUS, NEAR_ENEMY_RADIUS


class ArmyContext:
    """Built at the start of each army update, after Ares' managers have run (so grids/memory are current)."""

    def __init__(self, ai, positioning):
        self.ai = ai
        self.mediator = ai.mediator
        self.time: float = ai.time
        self.positioning = positioning
        # where the army stands when it is not attacking, and the geometry around that spot
        self.hold_point: Point2 = positioning.hold_point()
        self.front: Point2 = positioning.front_vector(self.hold_point)
        self.bio_position: Point2 = positioning.bio_position(self.hold_point)
        self.enemy_start: Point2 = ai.enemy_start_locations[0]

        # influence grids from Ares (already include enemy units + effects; ghosts of recently seen enemies too)
        self.ground_grid: np.ndarray = self.mediator.get_ground_grid
        self.air_grid: np.ndarray = self.mediator.get_air_grid
        self.climber_grid: np.ndarray = self.mediator.get_climber_grid

        self.stim_researched: bool = ai.already_pending_upgrade(UpgradeId.STIMPACK) == 1
        self.cloak_researched: bool = ai.already_pending_upgrade(UpgradeId.BANSHEECLOAK) == 1

        self._near: Dict[int, Units] = {}
        self._near_visible: Dict[int, List[Unit]] = {}
        self._banelings: Dict[int, List[Unit]] = {}
        self._wide: Dict[Tuple[int, float], Units] = {}

    # ------------------------------------------------------------------------------------------------------------
    # nearby enemies
    # ------------------------------------------------------------------------------------------------------------
    def prefetch_near(self, units: Iterable[Unit], radius: float = NEAR_ENEMY_RADIUS) -> None:
        """One batched KD-tree query for all our army units. Structures and remembered ghosts are included in the
        result (that is what Ares' trees contain) - use `targets_near` for "things I can shoot right now"."""
        unit_list = [u for u in units if u.tag not in self._near]
        if not unit_list:
            return
        result = self.mediator.get_units_in_range(
            start_points=unit_list,
            distances=radius,
            query_tree=UnitTreeQueryType.AllEnemy,
            return_as_dict=True,
        )
        for unit in unit_list:
            self._near[unit.tag] = result.get(unit.tag, Units([], self.ai))

    def enemies_near(self, unit: Unit) -> Units:
        """Everything hostile within NEAR_ENEMY_RADIUS: units, structures, and remembered (out of vision) ghosts."""
        cached = self._near.get(unit.tag)
        if cached is None:
            self.prefetch_near([unit])
            cached = self._near.get(unit.tag, Units([], self.ai))
        return cached

    def enemies_within(self, unit: Unit, radius: float) -> Units:
        """Like `enemies_near`, for a radius of the caller's choosing (a separate query, cached per radius). For units
        whose reach is larger than NEAR_ENEMY_RADIUS once the size of what they shoot at is added: a sieged tank's
        range is 13 edge to edge, which is 16.6 centre to centre for a Hatchery."""
        key = (unit.tag, radius)
        cached = self._wide.get(key)
        if cached is None:
            result = self.mediator.get_units_in_range(
                start_points=[unit], distances=radius, query_tree=UnitTreeQueryType.AllEnemy, return_as_dict=True
            )
            cached = result.get(unit.tag, Units([], self.ai))
            self._wide[key] = cached
        return cached

    def targets_near(self, unit: Unit) -> List[Unit]:
        """Enemies within reach of a decision that are visible right now and worth shooting at: no ghosts, no
        changelings/eggs/larva, nothing this unit cannot hit (a Marauder cannot shoot air, tanks neither, ...)."""
        cached = self._near_visible.get(unit.tag)
        if cached is not None:
            return cached
        can_air, can_ground = unit.can_attack_air, unit.can_attack_ground
        targets: List[Unit] = []
        for e in self.enemies_near(unit):
            if e.is_memory or e.type_id in ATTACK_TARGET_IGNORE or e.is_hallucination:
                continue
            if e.is_flying:
                if not can_air:
                    continue
            elif not can_ground:
                continue
            targets.append(e)
        self._near_visible[unit.tag] = targets
        return targets

    def banelings_near(self, unit: Unit) -> List[Unit]:
        """Banelings visible right now within LOCAL_FIGHT_RADIUS of the unit: the one enemy the kiting controllers always
        back away from (see units/common.kite_from_banelings)."""
        cached = self._banelings.get(unit.tag)
        if cached is None:
            cached = [
                e for e in self.enemies_near(unit)
                if e.type_id in BANELING_TYPES and not e.is_memory and not e.is_hallucination
                and e.distance_to(unit) <= LOCAL_FIGHT_RADIUS
            ]
            self._banelings[unit.tag] = cached
        return cached

    def close_banelings(self, unit: Unit) -> List[Unit]:
        """The banelings from `banelings_near` that are inside the unit's own weapon range (plus BANELING_KITE_MARGIN): the
        ones it must step back from on cooldown, and must not walk into."""
        reach = unit.ground_range + BANELING_KITE_MARGIN
        return [b for b in self.banelings_near(unit) if b.distance_to(unit) <= reach]

    # ------------------------------------------------------------------------------------------------------------
    # grids
    # ------------------------------------------------------------------------------------------------------------
    def grid_for(self, unit: Unit) -> np.ndarray:
        return self.air_grid if unit.is_flying else self.ground_grid

    def is_safe(self, unit: Unit, grid: Optional[np.ndarray] = None) -> bool:
        """Is the unit's current position free of enemy influence on `grid` (default: its own ground/air grid)?"""
        return self.mediator.is_position_safe(grid=self.grid_for(unit) if grid is None else grid, position=unit.position)
