"""Who is in a fight.

The combat simulator does not look at where anything stands. Probed with the real simulator: the same marines against the same roaches
give the same answer 2 or 110 cells apart, in a tight ball or strung out over 80 cells - every unit it is given fights from the first
second, however far away it is. So the units the simulator is given ARE the fight: hand it our whole army against the enemy units
next to us and it credits us with every marine still walking in from the other side of the map; hand it everything we know of their
army against the front of ours and it makes the fight look far worse than it is. This module decides who is in a fight.

A unit is in a fight when it could have a weapon on a unit of the other side within FIGHT_CONTACT_SECONDS: it can already shoot it,
or it can walk into range in time (a unit that cannot move - a sieged tank, a spine crawler - has to be in range already), and
the same the other way round (a marine that cannot get at an enemy that can get at it is in the fight all the same). Units linked
to each other, however indirectly, are one fight; two skirmishes at different places are two fights, judged separately. What is on its
way but farther off than that is not part of it yet, on either side - it joins when it gets there.
"""
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial.distance import cdist

from sc2.position import Point2
from sc2.unit import Unit

from bot.army.consts import FIGHT_CONTACT_SECONDS

# python-sc2 lists speeds per "normal" game second; the game, and ai.time, run on "faster" ones
FASTER_SPEED = 1.4


@dataclass
class Fight:
    own: List[Unit]
    enemy: List[Unit]
    engaged: bool                    # each side already has a weapon on the other: the approach is over, it is a fight now (until then
                                     # the side with the longer reach - sieged tanks against marines - is getting free shots)
    center: Point2                   # centroid of our units in it
    rank: int = 0                    # 0 = the biggest fight of the step (by our units in it)


class FightMap:
    """The fights of one step, biggest first, and which of our units is in which."""

    def __init__(self, fights: Sequence[Fight] = ()):
        self.fights: List[Fight] = sorted(fights, key=lambda f: -len(f.own))
        for rank, fight in enumerate(self.fights):
            fight.rank = rank
        self._by_tag: Dict[int, Fight] = {u.tag: f for f in self.fights for u in f.own}

    def __len__(self) -> int:
        return len(self.fights)

    def fight_of(self, unit: Unit) -> Optional[Fight]:
        return self._by_tag.get(unit.tag)

    def fights_of(self, units: Iterable[Unit]) -> List[Fight]:
        """The distinct fights any of `units` is in, biggest first."""
        found = {}
        for unit in units:
            fight = self._by_tag.get(unit.tag)
            if fight is not None:
                found[fight.rank] = fight
        return [found[rank] for rank in sorted(found)]


class _Side:
    """What the contact test needs to know about one side's units, as arrays."""

    def __init__(self, units: Sequence[Unit]):
        self.position = np.array([u.position_tuple for u in units], dtype=float).reshape(-1, 2)
        self.radius = np.array([u.radius for u in units], dtype=float)
        self.speed = np.array([u.movement_speed * FASTER_SPEED for u in units], dtype=float)
        self.ground_range = np.array([u.ground_range for u in units], dtype=float)
        self.air_range = np.array([u.air_range for u in units], dtype=float)
        self.can_ground = np.array([u.can_attack_ground for u in units], dtype=bool)
        self.can_air = np.array([u.can_attack_air for u in units], dtype=bool)
        self.flying = np.array([u.is_flying for u in units], dtype=bool)


def _seconds_to_weapons(attackers: _Side, targets: _Side) -> np.ndarray:
    """(attackers x targets): seconds until each attacker has a weapon on each target - 0 when it already does, infinity when it can
    neither shoot it (a marauder and a mutalisk) nor walk to it (a sieged tank out of range)."""
    gap = cdist(attackers.position, targets.position) - attackers.radius[:, None] - targets.radius[None, :]
    flying = targets.flying[None, :]
    reach = np.where(flying, attackers.air_range[:, None], attackers.ground_range[:, None])
    can_hit = np.where(flying, attackers.can_air[:, None], attackers.can_ground[:, None])
    walk = np.maximum(gap - reach, 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        seconds = np.where(walk <= 0.0, 0.0, np.where(attackers.speed[:, None] > 0.0, walk / attackers.speed[:, None], np.inf))
    seconds[~can_hit] = np.inf
    return seconds


def find_fights(own: Sequence[Unit], enemy: Sequence[Unit], horizon: float = FIGHT_CONTACT_SECONDS) -> FightMap:
    """The fights between `own` and `enemy` (already filtered to what the simulator should see): see the module docstring."""
    if not own or not enemy:
        return FightMap()
    ours, theirs = _Side(own), _Side(enemy)
    n, m = len(own), len(enemy)
    own_to_enemy = _seconds_to_weapons(ours, theirs)                                                   # (own x enemy)
    enemy_to_own = _seconds_to_weapons(theirs, ours).T                                                 # (own x enemy)
    seconds = np.minimum(own_to_enemy, enemy_to_own)
    linked = seconds <= horizon
    rows, cols = np.nonzero(linked)
    if not len(rows):
        return FightMap()
    graph = coo_matrix((np.ones(len(rows)), (rows, n + cols)), shape=(n + m, n + m))
    _, labels = connected_components(graph, directed=False)
    own_labels, enemy_labels = labels[:n], labels[n:]
    fights: List[Fight] = []
    for label in np.unique(own_labels[linked.any(axis=1)]):
        mine = np.nonzero(own_labels == label)[0]
        opposing = np.nonzero(enemy_labels == label)[0]
        block = np.ix_(mine, opposing)
        engaged = bool((own_to_enemy[block] <= 0.0).any() and (enemy_to_own[block] <= 0.0).any())
        members = [own[i] for i in mine]
        center = Point2((float(ours.position[mine, 0].mean()), float(ours.position[mine, 1].mean())))
        fights.append(Fight(own=members, enemy=[enemy[j] for j in opposing], engaged=engaged, center=center))
    return FightMap(fights)
