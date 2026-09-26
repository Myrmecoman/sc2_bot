"""Per-step snapshot of everything unit controllers need, computed once instead of once per unit."""
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np

from ares.consts import UnitTreeQueryType
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from sc2.ids.upgrade_id import UpgradeId

from bot.army.consts import (
    ATTACK_TARGET_IGNORE,
    BANELING_KITE_MARGIN,
    BANELING_TYPES,
    ENEMY_WORKER_TYPES,
    LOCAL_FIGHT_RADIUS,
    MELEE_KITE_MARGIN,
    MELEE_KITE_MAX_SPEED_RATIO,
    MELEE_RANGE_THRESHOLD,
    NEAR_ENEMY_RADIUS,
)
from bot.army.local_fight import FightMap

# what an enemy unit is to a shooter, see ArmyContext._kind
_GROUND_TARGET, _AIR_TARGET, _BANELING, _MELEE = 1, 2, 4, 8


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

        # who is in which fight this step (local_fight.py); the army manager fills it once the roles are sorted out
        self.fights: FightMap = FightMap()

        self._near: Dict[int, Units] = {}
        self._near_visible: Dict[int, List[Unit]] = {}
        self._banelings: Dict[int, List[Unit]] = {}
        self._wide: Dict[Tuple[int, float], Units] = {}
        self._kinds: Dict[int, Tuple[Unit, int]] = {}
        self._baneling_present: Optional[bool] = None
        self._melee: Dict[int, List[Unit]] = {}
        self._melee_present: Optional[bool] = None
        self.tank_closest: Dict[int, Optional[float]] = {}      # tank tag -> distance to what it could shoot (units/tanks.py)

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

    def _kind(self, enemy: Unit) -> int:
        """What an enemy unit is to a shooter (a _GROUND_TARGET / _AIR_TARGET / _BANELING mask), worked out once per step: every unit
        of ours goes through everything near it, and each of these checks is a read of the unit's protobuf - a big army in front of
        a big army made those reads the most expensive thing the army code did."""
        entry = self._kinds.get(id(enemy))
        if entry is None:
            kind = 0
            if not enemy.is_memory and not enemy.is_hallucination:
                type_id = enemy.type_id
                if type_id in BANELING_TYPES:
                    kind |= _BANELING
                if type_id not in ATTACK_TARGET_IGNORE:
                    kind |= _AIR_TARGET if enemy.is_flying else _GROUND_TARGET
                    # (a Baneling has a rule of its own, workers are not what a fight is about, a building with no weapon is not a threat)
                    if (
                        not enemy.is_flying and not enemy.is_structure and type_id not in BANELING_TYPES
                        and type_id not in ENEMY_WORKER_TYPES and 0 < enemy.ground_range <= MELEE_RANGE_THRESHOLD
                    ):
                        kind |= _MELEE
            # the unit is kept in the entry so that its id cannot be handed to another object while the step is still running
            entry = self._kinds[id(enemy)] = (enemy, kind)
        return entry[1]

    def targets_near(self, unit: Unit) -> List[Unit]:
        """Enemies within reach of a decision that are visible right now and worth shooting at: no ghosts, no
        changelings/eggs/larva, nothing this unit cannot hit (a Marauder cannot shoot air, tanks neither, ...)."""
        cached = self._near_visible.get(unit.tag)
        if cached is not None:
            return cached
        wanted = (_AIR_TARGET if unit.can_attack_air else 0) | (_GROUND_TARGET if unit.can_attack_ground else 0)
        targets: List[Unit] = [e for e in self.enemies_near(unit) if self._kind(e) & wanted]
        self._near_visible[unit.tag] = targets
        return targets

    def banelings_near(self, unit: Unit) -> List[Unit]:
        """Banelings visible right now within LOCAL_FIGHT_RADIUS of the unit: the one enemy the kiting controllers always
        back away from (see units/common.kite_from_banelings)."""
        cached = self._banelings.get(unit.tag)
        if cached is None:
            if self._baneling_present is None:
                # (remembered ghosts count here: this only decides whether to look closer, which filters them out again)
                self._baneling_present = any(e.type_id in BANELING_TYPES for e in self.ai.enemy_units)
            cached = [] if not self._baneling_present else [
                e for e in self.enemies_near(unit) if self._kind(e) & _BANELING and e.distance_to(unit) <= LOCAL_FIGHT_RADIUS
            ]
            self._banelings[unit.tag] = cached
        return cached

    def _melee_enemies(self, unit: Unit, radius: float) -> List[Unit]:
        if self._melee_present is None:
            self._melee_present = any(self._kind(e) & _MELEE for e in self.ai.enemy_units)
        if not self._melee_present:
            return []
        return [e for e in self.enemies_near(unit) if self._kind(e) & _MELEE and e.distance_to(unit) <= radius]

    def close_melee(self, unit: Unit) -> List[Unit]:
        """The melee-only enemies (Zealots, Zerglings, ...) visible right now inside the unit's own weapon range plus MELEE_KITE_MARGIN, and
        not much faster than it: the ones it steps back from while its weapon is on cooldown (see units/bio.py). A melee unit that is
        much faster than the unit (MELEE_KITE_MAX_SPEED_RATIO) cannot be kited: no step back gains distance on it."""
        cached = self._melee.get(unit.tag)
        if cached is None:
            speed = max(unit.real_speed, 0.1) * MELEE_KITE_MAX_SPEED_RATIO
            cached = [e for e in self._melee_enemies(unit, unit.ground_range + MELEE_KITE_MARGIN) if e.real_speed <= speed]
            self._melee[unit.tag] = cached
        return cached

    def melee_within(self, unit: Unit, radius: float) -> List[Unit]:
        """Every melee-only enemy visible right now within `radius` of the unit (however fast)."""
        return self._melee_enemies(unit, radius)

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
