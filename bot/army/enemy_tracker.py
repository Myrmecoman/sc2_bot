"""Persistent knowledge of the enemy army: every unit we have ever seen is still alive until we see it die.

Ares keeps its own memory of unseen enemy units (UnitMemoryManager), but forgets them after 30 seconds - that
is fine for pathing influence and kiting, and wrong for deciding whether a push is worth taking: an enemy army
that walked into the fog 40 seconds ago did not stop existing. This tracker has NO time-based decay, on purpose
(the same rule the previous army advisor followed): a unit leaves it only through `remove()` (death event).

The sim needs `Unit`-like objects, so what is stored is the last `Unit` snapshot per tag. Snapshots must never be
used for `unit.distance_to(other_unit)` - the distance matrix python-sc2 uses is per-frame and a snapshot's index
is stale; use position-based helpers (cy_closer_than, Point2.distance_to, ...) on them.
"""
from typing import Dict, Iterable, List, Optional, Set

from s2clientprotocol import raw_pb2

from ares.dicts.unit_data import UNIT_DATA

from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit
from sc2.units import Units

from bot.army.consts import ENEMY_NON_ARMY_TYPES

# a snapshot older than this is fed to the simulator at full health/shield - a unit that has been out of sight
# that long has regenerated / been repaired / healed
HEAL_AFTER_SECONDS = 30.0

_DEFAULT_SUPPLY = 2.0   # used for a unit type nothing knows the supply of - a middling guess beats a crash


class EnemyTracker:
    def __init__(self, ai):
        self.ai = ai
        self._snapshots: Dict[int, Unit] = {}
        self._last_seen: Dict[int, float] = {}
        self._healed: Dict[int, Unit] = {}          # tag -> full-health copy of the snapshot (built lazily)
        self._visible_tags: Set[int] = set()
        self._known_cache: Optional[Units] = None
        self._known_cache_loop: int = -1
        # supply of enemy army units we have watched die - they are no longer alive, but they tell us how much of
        # their army we have actually SEEN (so a counter-push after wiping their army is not mistaken for "blind")
        self.killed_supply: float = 0.0

    # ------------------------------------------------------------------------------------------------------------
    # updating
    # ------------------------------------------------------------------------------------------------------------
    def update(self, visible_enemy_units: Iterable[Unit]) -> None:
        """Call once per step with the enemy units observed THIS frame (not Ares' remembered ghosts)."""
        now: float = self.ai.time
        self._visible_tags = set()
        for unit in visible_enemy_units:
            if unit.type_id in ENEMY_NON_ARMY_TYPES or unit.is_hallucination or unit.is_structure:
                continue
            tag = unit.tag
            self._visible_tags.add(tag)
            previous = self._snapshots.get(tag)
            if previous is None or previous.type_id != unit.type_id:
                self._healed.pop(tag, None)          # morphed (siege, cocoon, ...) - old healed copy is the wrong type
            self._snapshots[tag] = unit
            self._last_seen[tag] = now
            self._healed.pop(tag, None)              # fresh sighting supersedes any healed copy
        self._known_cache = None

    def remove(self, tag: int) -> None:
        """A death event - the only way a unit ever leaves the tracker. (Also called for our own units' deaths; those
        were never tracked, so it does nothing then.)"""
        snapshot = self._snapshots.pop(tag, None)
        if snapshot is not None:
            self.killed_supply += self.supply_of(snapshot.type_id)
        self._last_seen.pop(tag, None)
        self._healed.pop(tag, None)
        self._visible_tags.discard(tag)
        self._known_cache = None

    # ------------------------------------------------------------------------------------------------------------
    # queries
    # ------------------------------------------------------------------------------------------------------------
    def __len__(self) -> int:
        return len(self._snapshots)

    def age_of(self, tag: int) -> float:
        seen = self._last_seen.get(tag)
        return float("inf") if seen is None else self.ai.time - seen

    def amount_of_type(self, type_id: UnitTypeId) -> int:
        return sum(1 for snap in self._snapshots.values() if snap.type_id == type_id)

    def types_known(self) -> Set[UnitTypeId]:
        return {snap.type_id for snap in self._snapshots.values()}

    def total_supply(self) -> float:
        """Supply of the enemy army units believed alive."""
        return sum(self.supply_of(snap.type_id) for snap in self._snapshots.values())

    def total_seen_supply(self) -> float:
        """Alive plus killed: how much of their army we have laid eyes on, whatever became of it since."""
        return self.total_supply() + self.killed_supply

    def supply_of(self, type_id: UnitTypeId) -> float:
        """Ares' unit table has the right value for every army unit (zerglings 0.5, ravagers 3, archons 4, ...)."""
        entry = UNIT_DATA.get(type_id)
        if entry is not None:
            return float(entry["supply"])
        try:
            return float(self.ai.calculate_supply_cost(type_id))
        except Exception:  # noqa: BLE001
            return _DEFAULT_SUPPLY

    def unseen_tags(self) -> Set[int]:
        return set(self._snapshots) - self._visible_tags

    def known_army(self) -> Units:
        """Every enemy army unit we believe is alive: the live object where we can see it right now, the last
        snapshot (healed to full once stale) where we can't. Sim input and counting only - see the module docstring
        about distances. Cached per game loop."""
        loop = self.ai.state.game_loop
        if self._known_cache is not None and self._known_cache_loop == loop:
            return self._known_cache
        result: List[Unit] = []
        for tag, snap in self._snapshots.items():
            if tag in self._visible_tags:
                result.append(snap)
            elif self.age_of(tag) > HEAL_AFTER_SECONDS:
                result.append(self._healed_copy(tag, snap))
            else:
                result.append(snap)
        self._known_cache = Units(result, self.ai)
        self._known_cache_loop = loop
        return self._known_cache

    def _healed_copy(self, tag: int, snap: Unit) -> Unit:
        copy = self._healed.get(tag)
        if copy is None:
            proto = raw_pb2.Unit()
            proto.CopyFrom(snap._proto)
            proto.health = proto.health_max
            proto.shield = proto.shield_max
            copy = Unit(proto, self.ai, distance_calculation_index=snap.distance_calculation_index,
                        base_build=snap.base_build)
            self._healed[tag] = copy
        return copy
