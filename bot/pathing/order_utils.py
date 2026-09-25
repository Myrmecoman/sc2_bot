import math
from typing import Callable, Optional

import numpy as np

from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units


# avoid re-issuing an order a unit is already executing: repeating an Attack order
# resets the unit's attack windup in the game engine, which is a real DPS loss, not just a wasted action
def is_already_attacking(unit: Unit, target: Unit) -> bool:
    return unit.is_attacking and unit.order_target == target.tag


def is_already_attack_moving_to(unit: Unit, position: Point2, epsilon: float = 0.5) -> bool:
    return unit.is_attacking and isinstance(unit.order_target, Point2) and unit.order_target.distance_to(position) <= epsilon


def is_already_moving_to(unit: Unit, position: Point2, epsilon: float = 0.5) -> bool:
    return unit.is_moving and isinstance(unit.order_target, Point2) and unit.order_target.distance_to(position) <= epsilon


# target can be either a Unit or a Point2 (as accepted by unit.attack() itself)
def is_already_attacking_target(unit: Unit, target) -> bool:
    if isinstance(target, Point2):
        return is_already_attack_moving_to(unit, target)
    return is_already_attacking(unit, target)


def plain_point(point) -> Point2:
    """The same position as a Point2 of plain Python floats. Ares hands back numpy-typed coordinates (path points are
    int32 grid cells, safe spots int64) and `Point2.__bool__` yields a numpy bool for those, which Python rejects with a
    TypeError - so a point that came out of Ares is normalised before it is stored, and no point is ever tested for
    truth (`a or b`): compare with None instead."""
    return Point2((float(point[0]), float(point[1])))


def segment_walkable(start: Point2, end: Point2, walkable: Callable[[Point2], bool], step: float = 0.75) -> bool:
    """Is the straight line from `start` to `end` free of cells a ground unit cannot stand on? (`walkable` is
    `ai.in_pathing_grid`.) Sampled every `step`, and at the end itself."""
    length = start.distance_to(end)
    samples = max(1, int(math.ceil(length / step)))
    for i in range(1, samples + 1):
        t = i / samples
        if not walkable(Point2((start.x + (end.x - start.x) * t, start.y + (end.y - start.y) * t))):
            return False
    return True


class Crowd:
    """The positions of a group of units as one array, to ask "who stands close to me" of every unit at once. Searching the whole
    group unit by unit (`Units.closer_than`) reads every unit's position for every unit - for a 80-strong bio army a few
    milliseconds a step, just to find out who is in the way."""

    def __init__(self, units: Units):
        self._index = {u.tag: i for i, u in enumerate(units)}
        self._xy = np.array([u.position_tuple for u in units], dtype=float).reshape(-1, 2)

    def centre_of_neighbours(self, unit: Unit, radius: float) -> Optional[Point2]:
        """Where the units closer than `radius` to `unit` (other than itself) are centred; None when there are none."""
        i = self._index[unit.tag]
        gap = self._xy - self._xy[i]
        near = (gap * gap).sum(axis=1) < radius * radius
        near[i] = False
        if not near.any():
            return None
        x, y = self._xy[near].mean(axis=0)
        return Point2((float(x), float(y)))


def spread_out_point(
    unit: Unit,
    friendlies: Units,
    towards: Point2,
    radius: float = 1.25,
    nudge: float = 1.5,
    walkable: Optional[Callable[[Point2], bool]] = None,
    crowd: Optional[Crowd] = None,
) -> Point2:
    """Nudge a movement/attack point away from tightly clumped nearby friendlies while still
    heading roughly towards the objective - reduces vulnerability to AOE (splash, storm, banelings,
    a friendly siege tank's own blast). Only meant for use away from active point-blank combat, so
    it never interferes with actual targeting/firing.

    The nudged point is a few cells ahead of the unit in a STRAIGHT line towards `towards`, whereas the way there is
    rarely straight: with a wall, a cliff or a dead end in that line the unit would be sent to a spot on the far side of it
    - and pressed against the obstacle, never getting anywhere. So when `walkable` is given and the line to the nudged point
    is not all standable, the unit is sent to `towards` itself and the engine finds the real way."""
    if crowd is not None:       # (the group's positions were put in one array beforehand: see Crowd)
        centroid = crowd.centre_of_neighbours(unit, radius)
        if centroid is None or unit.position.distance_to(towards) < radius:
            return towards
    else:
        nearby: Units = friendlies.tags_not_in({unit.tag}).closer_than(radius, unit)
        if nearby.amount == 0 or unit.position.distance_to(towards) < radius:
            return towards
        centroid = Point2((
            sum(f.position.x for f in nearby) / nearby.amount,
            sum(f.position.y for f in nearby) / nearby.amount,
        ))
    if unit.position.distance_to(centroid) < 0.1:
        return towards
    away_point: Point2 = unit.position.towards(centroid, -nudge)
    hop: Point2 = away_point.towards(towards, 3)
    if walkable is not None and not segment_walkable(unit.position, hop, walkable):
        return towards
    return hop
