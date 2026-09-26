import math
from typing import Callable, List, Optional

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


def path_length(start, path) -> Optional[float]:
    """How long the walk from `start` along `path` (the points Ares' `find_raw_path` returns) is; None when there is no path."""
    if path is None or len(path) == 0:
        return None
    length, x, y = 0.0, float(start[0]), float(start[1])
    for point in path:
        px, py = float(point[0]), float(point[1])
        length += math.hypot(px - x, py - y)
        x, y = px, py
    return length


def ground_free(grid: np.ndarray, x: float, y: float) -> bool:
    """Can a ground unit stand on the cell of (x, y)? `grid` is Ares' clean ground grid (`get_cached_ground_grid`, [x, y]): np.inf where
    the terrain is not walkable and under rocks, minerals and the footprint of a building - a townhall's 5x5 included."""
    i, j = int(x), int(y)
    return 0 <= i < grid.shape[0] and 0 <= j < grid.shape[1] and grid[i, j] != np.inf


def reachable_from_ground(grid: np.ndarray, position, reach: float = 0.75) -> bool:
    """Can an SCV get to a flying unit hovering over `position`? Not when it hovers over the middle of a building, over minerals or over a
    cliff: there is nothing within `reach` (the flyer's radius) for the SCV to stand on, it stops at the edge, out of repair range."""
    x, y = float(position[0]), float(position[1])
    return any(ground_free(grid, x + dx, y + dy) for dx, dy in ((0.0, 0.0), (reach, 0.0), (-reach, 0.0), (0.0, reach), (0.0, -reach)))


def open_ground_near(grid: np.ndarray, point: Point2, max_distance: float, limit: int = 12) -> List[Point2]:
    """The nearest `limit` cells (centres) within `max_distance` of `point` with room around them on the clean ground grid: the cell and its
    four neighbours are walkable, so a flyer can hover over it with an SCV standing under it. Nearest first."""
    x0, x1 = max(1, int(point.x - max_distance)), min(grid.shape[0] - 1, int(point.x + max_distance) + 1)
    y0, y1 = max(1, int(point.y - max_distance)), min(grid.shape[1] - 1, int(point.y + max_distance) + 1)
    if x1 <= x0 or y1 <= y0:
        return []
    free = grid[x0 - 1: x1 + 1, y0 - 1: y1 + 1] != np.inf
    room = free[1:-1, 1:-1] & free[:-2, 1:-1] & free[2:, 1:-1] & free[1:-1, :-2] & free[1:-1, 2:]
    xs, ys = np.nonzero(room)
    cx, cy = xs + x0 + 0.5, ys + y0 + 0.5
    gap = np.hypot(cx - point.x, cy - point.y)
    near = np.nonzero(gap <= max_distance)[0]
    near = near[np.argsort(gap[near], kind="stable")][:limit]
    return [Point2((float(cx[i]), float(cy[i]))) for i in near]


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
