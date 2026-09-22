"""
Self-contained grid-based pathfinding: builds walkability/danger grids straight from
python-sc2's own raw pathing/placement/terrain-height data plus this bot's own structure/
destructible/resource knowledge, and pathfinds over them with A*. No third-party map-analysis
library, no compiled C extension - replaces what normal/map_analyzer/ used to provide.

Grid convention throughout this module and pathing.py: 2D float32 numpy arrays, [x, y] indexed
(grid[x, y]), where a cell's value is its movement cost and np.inf means unwalkable. This matches
how pathing.py's consumers already read grids (e.g. is_position_safe does grid[position.x, position.y]).
python-sc2's own raw PixelMap data (pathing_grid, placement_grid, terrain_height) is [y, x] indexed
instead, so every place this module reads one of those, it transposes first.
"""

import heapq
import itertools
import math
from typing import Dict, List, Optional, Tuple

import numpy as np
from sc2.bot_ai import BotAI
from sc2.game_info import Ramp
from sc2.position import Point2
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId

SQRT2 = math.sqrt(2.0)


# ---------------------------------------------------------------------------------------------
# destructible rock/debris footprints - sizes and (for the two diagonal shapes) exact per-row
# offsets, ported verbatim from the old map_analyzer/destructibles.py + utils.py. These come from
# observed per-map geometry, not something to derive generically - kept unrolled rather than
# parameterized so there's no risk of subtly transposing/reversing a hand-tuned shape.
# ---------------------------------------------------------------------------------------------

destructable_2x2 = {UnitTypeId.ROCKS2X2NONCONJOINED, UnitTypeId.DEBRIS2X2NONCONJOINED}

destructable_4x4 = {
    UnitTypeId.DESTRUCTIBLECITYDEBRIS4X4,
    UnitTypeId.DESTRUCTIBLEDEBRIS4X4,
    UnitTypeId.DESTRUCTIBLEICE4X4,
    UnitTypeId.DESTRUCTIBLEROCK4X4,
    UnitTypeId.DESTRUCTIBLEROCKEX14X4,
}

destructable_4x2 = {
    UnitTypeId.DESTRUCTIBLECITYDEBRIS2X4HORIZONTAL,
    UnitTypeId.DESTRUCTIBLEICE2X4HORIZONTAL,
    UnitTypeId.DESTRUCTIBLEROCK2X4HORIZONTAL,
    UnitTypeId.DESTRUCTIBLEROCKEX12X4HORIZONTAL,
}

destructable_2x4 = {
    UnitTypeId.DESTRUCTIBLECITYDEBRIS2X4VERTICAL,
    UnitTypeId.DESTRUCTIBLEICE2X4VERTICAL,
    UnitTypeId.DESTRUCTIBLEROCK2X4VERTICAL,
    UnitTypeId.DESTRUCTIBLEROCKEX12X4VERTICAL,
}

destructable_6x2 = {
    UnitTypeId.DESTRUCTIBLECITYDEBRIS2X6HORIZONTAL,
    UnitTypeId.DESTRUCTIBLEICE2X6HORIZONTAL,
    UnitTypeId.DESTRUCTIBLEROCK2X6HORIZONTAL,
    UnitTypeId.DESTRUCTIBLEROCKEX12X6HORIZONTAL,
}

destructable_2x6 = {
    UnitTypeId.DESTRUCTIBLECITYDEBRIS2X6VERTICAL,
    UnitTypeId.DESTRUCTIBLEICE2X6VERTICAL,
    UnitTypeId.DESTRUCTIBLEROCK2X6VERTICAL,
    UnitTypeId.DESTRUCTIBLEROCKEX12X6VERTICAL,
}

destructable_4x12 = {
    UnitTypeId.DESTRUCTIBLEROCKEX1VERTICALHUGE,
    UnitTypeId.DESTRUCTIBLEICEVERTICALHUGE,
}

destructable_12x4 = {
    UnitTypeId.DESTRUCTIBLEROCKEX1HORIZONTALHUGE,
    UnitTypeId.DESTRUCTIBLEICEHORIZONTALHUGE,
}

destructable_6x6 = {
    UnitTypeId.DESTRUCTIBLECITYDEBRIS6X6,
    UnitTypeId.DESTRUCTIBLEDEBRIS6X6,
    UnitTypeId.DESTRUCTIBLEICE6X6,
    UnitTypeId.DESTRUCTIBLEROCK6X6,
    UnitTypeId.DESTRUCTIBLEROCKEX16X6,
}

destructable_BLUR = {
    UnitTypeId.DESTRUCTIBLECITYDEBRISHUGEDIAGONALBLUR,
    UnitTypeId.DESTRUCTIBLEDEBRISRAMPDIAGONALHUGEBLUR,
    UnitTypeId.DESTRUCTIBLEICEDIAGONALHUGEBLUR,
    UnitTypeId.DESTRUCTIBLEROCKEX1DIAGONALHUGEBLUR,
    UnitTypeId.DESTRUCTIBLERAMPDIAGONALHUGEBLUR,
}

destructable_ULBR = {
    UnitTypeId.DESTRUCTIBLECITYDEBRISHUGEDIAGONALULBR,
    UnitTypeId.DESTRUCTIBLEDEBRISRAMPDIAGONALHUGEULBR,
    UnitTypeId.DESTRUCTIBLEICEDIAGONALHUGEULBR,
    UnitTypeId.DESTRUCTIBLEROCKEX1DIAGONALHUGEULBR,
    UnitTypeId.DESTRUCTIBLERAMPDIAGONALHUGEULBR,
}


def set_destructible_footprint(grid: np.ndarray, unit: Unit, status: float) -> None:
    """Sets a destructible rock/debris unit's footprint to `status` in `grid`, in place."""
    type_id = unit.type_id
    pos = unit.position
    name = unit.name

    if name == "MineralField450":
        x = int(pos.x) - 1
        y = int(pos.y)
        grid[x:x + 2, y] = status
    elif type_id in destructable_2x2:
        w, h = 2, 2
        x, y = int(pos.x - w / 2), int(pos.y - h / 2)
        grid[x:x + w, y:y + h] = status
    elif type_id in destructable_2x4:
        w, h = 2, 4
        x, y = int(pos.x - w / 2), int(pos.y - h / 2)
        grid[x:x + w, y:y + h] = status
    elif type_id in destructable_4x2:
        w, h = 4, 2
        x, y = int(pos.x - w / 2), int(pos.y - h / 2)
        grid[x:x + w, y:y + h] = status
    elif type_id in destructable_4x4:
        w, h = 4, 4
        x, y = int(pos.x - w / 2), int(pos.y - h / 2)
        grid[x:x + w, y:y + h] = status
    elif type_id in destructable_6x2:
        w, h = 6, 2
        x, y = int(pos.x - w / 2), int(pos.y - h / 2)
        grid[x:x + w, y:y + h] = status
    elif type_id in destructable_2x6:
        w, h = 2, 6
        x, y = int(pos.x - w / 2), int(pos.y - h / 2)
        grid[x:x + w, y:y + h] = status
    elif type_id in destructable_12x4:
        w, h = 12, 4
        x, y = int(pos.x - w / 2), int(pos.y - h / 2)
        grid[x:x + w, y:y + h] = status
    elif type_id in destructable_4x12:
        w, h = 4, 12
        x, y = int(pos.x - w / 2), int(pos.y - h / 2)
        grid[x:x + w, y:y + h] = status
    elif type_id in destructable_6x6:
        # some maps' 6x6 rocks are a tile off from a true square - matches the old library's
        # hand-tuned exception rather than a plain square block
        w, h = 6, 6
        x, y = int(pos.x - w / 2), int(pos.y - h / 2)
        grid[x:x + w, (y + 1):(y + h - 1)] = status
        grid[(x + 1):(x + w - 1), y:(y + h)] = status
    elif type_id in destructable_BLUR:
        x_ref = int(pos.x - 5)
        y_pos = int(pos.y)
        grid[(x_ref + 6):(x_ref + 6 + 2), y_pos + 4] = status
        grid[(x_ref + 5):(x_ref + 5 + 4), y_pos + 3] = status
        grid[(x_ref + 4):(x_ref + 4 + 6), y_pos + 2] = status
        grid[(x_ref + 3):(x_ref + 3 + 7), y_pos + 1] = status
        grid[(x_ref + 2):(x_ref + 2 + 7), y_pos] = status
        grid[(x_ref + 1):(x_ref + 1 + 7), y_pos - 1] = status
        grid[(x_ref + 0):(x_ref + 0 + 7), y_pos - 2] = status
        grid[(x_ref + 0):(x_ref + 0 + 6), y_pos - 3] = status
        grid[(x_ref + 1):(x_ref + 1 + 4), y_pos - 4] = status
        grid[(x_ref + 2):(x_ref + 2 + 2), y_pos - 5] = status
    elif type_id in destructable_ULBR:
        x_ref = int(pos.x - 5)
        y_pos = int(pos.y)
        grid[(x_ref + 6):(x_ref + 6 + 2), y_pos - 5] = status
        grid[(x_ref + 5):(x_ref + 5 + 4), y_pos - 4] = status
        grid[(x_ref + 4):(x_ref + 4 + 6), y_pos - 3] = status
        grid[(x_ref + 3):(x_ref + 3 + 7), y_pos - 2] = status
        grid[(x_ref + 2):(x_ref + 2 + 7), y_pos - 1] = status
        grid[(x_ref + 1):(x_ref + 1 + 7), y_pos] = status
        grid[(x_ref + 0):(x_ref + 0 + 7), y_pos + 1] = status
        grid[(x_ref + 0):(x_ref + 0 + 6), y_pos + 2] = status
        grid[(x_ref + 1):(x_ref + 1 + 4), y_pos + 3] = status
        grid[(x_ref + 2):(x_ref + 2 + 2), y_pos + 4] = status


# ---------------------------------------------------------------------------------------------
# grid construction
# ---------------------------------------------------------------------------------------------

def build_terrain_base(ai: BotAI) -> np.ndarray:
    """Static per-game base walkability from the game's own raw grids - call once, reuse."""
    pathing = ai.game_info.pathing_grid.data_numpy
    placement = ai.game_info.placement_grid.data_numpy
    return np.fmax(pathing, placement).T.astype(np.float32)


def build_reaper_terrain_base(ai: BotAI) -> np.ndarray:
    """Same as build_terrain_base, but NOT shared with ground_grid - these two cliff-top
    platforms are only reachable by a climbing unit (Reaper/Colossus), so marking them walkable
    here must not leak into regular ground units' grid, or they'd get routed onto tiles they
    can't actually stand on."""
    base = build_terrain_base(ai).copy()
    if "Submarine" in ai.game_info.map_name:
        base[116, 43] = 1
        base[51, 120] = 1
    return base


def build_terrain_height(ai: BotAI) -> np.ndarray:
    """int16, not the source data's uint8 - a same-height comparison done on unsigned data wraps
    around whenever a neighboring cell is lower than the point being tested, so it silently only
    works correctly in one direction. Only used by find_eligible_point's height check."""
    return ai.game_info.terrain_height.data_numpy.T.astype(np.int16)


def _zero_destructibles(grid: np.ndarray, ai: BotAI) -> None:
    for dest in ai.destructables:
        name = dest.name.lower()
        if "unbuildable" in name or "acceleration" in name:
            continue
        set_destructible_footprint(grid, dest, 0)


def _zero_geysers_and_minerals(grid: np.ndarray, ai: BotAI) -> None:
    for geyser in ai.vespene_geyser:
        x = int(geyser.position.x - 1.5)
        y = int(geyser.position.y - 1.5)
        grid[x:x + 3, y:y + 3] = 0
    for mineral in ai.mineral_field:
        x1 = int(mineral.position.x)
        x2 = x1 - 1
        y = int(mineral.position.y)
        grid[x1, y] = 0
        grid[x2, y] = 0


# footprint_radius is None for any building with no distinct creation ability - flying Terran
# buildings (already excluded below via .not_flying) and rich-vespene-geyser gas buildings, which
# genuinely do have a real 3x3 footprint (same as their normal counterpart) despite that
_RICH_GAS_BUILDINGS = {UnitTypeId.ASSIMILATORRICH, UnitTypeId.EXTRACTORRICH, UnitTypeId.REFINERYRICH}


def _zero_structures(grid: np.ndarray, ai: BotAI) -> None:
    nonpathables = (ai.structures.not_flying | ai.enemy_structures.not_flying).filter(
        lambda u: (u.type_id != UnitTypeId.SUPPLYDEPOTLOWERED or u.is_active)
        and (u.type_id != UnitTypeId.CREEPTUMOR or not u.is_ready)
    )
    for obj in nonpathables:
        radius = obj.footprint_radius
        if radius:
            size = round(2 * radius)
        elif obj.type_id in _RICH_GAS_BUILDINGS:
            size = 3
        else:
            size = 1
        x_start = int(obj.position.x - size / 2)
        y_start = int(obj.position.y - size / 2)
        x_end = x_start + size
        y_end = y_start + size
        grid[x_start:x_end, y_start:y_end] = 0
        if size == 5:
            # townhall-sized buildings: leave their 4 corner cells pathable
            grid[x_start, y_start] = 1
            grid[x_start, y_end - 1] = 1
            grid[x_end - 1, y_start] = 1
            grid[x_end - 1, y_end - 1] = 1


def build_walkable_grid(ai: BotAI, terrain_base: np.ndarray, default_weight: float = 1.0) -> np.ndarray:
    """Rebuilt fresh every step - structures/destructibles/resources change over the game."""
    grid = terrain_base.copy()
    _zero_destructibles(grid, ai)
    _zero_geysers_and_minerals(grid, ai)
    _zero_structures(grid, ai)
    return np.where(grid != 0, default_weight, np.inf).astype(np.float32)


def build_clean_air_grid(ai: BotAI, default_weight: float = 1.0) -> np.ndarray:
    """Air has no terrain restriction - just bounded to the playable area."""
    shape = ai.game_info.pathing_grid.data_numpy.T.shape
    grid = np.zeros(shape=shape, dtype=np.float32)
    area = ai.game_info.playable_area
    grid[area.x:area.x + area.width, area.y:area.y + area.height] = 1
    return np.where(grid == 1, default_weight, np.inf).astype(np.float32)


def fix_ramps_for_destructibles(ai: BotAI) -> None:
    """python-sc2's own ramp detection treats every currently-existing destructible as blocking,
    which can shrink or split a ramp's point set on maps where a rock sits on/near it - enough to
    change which ramp main_base_ramp ends up picking. Recompute ramp/vision-blocker points with
    destructibles treated as if they weren't there, and overwrite game_info's stored ramps -
    same correction map_analyzer used to apply, same call timing (once, at bot startup)."""
    pathing_grid = ai.game_info.pathing_grid.data_numpy.T.copy().astype(np.float32)
    for dest in ai.destructables:
        set_destructible_footprint(pathing_grid, dest, 1)

    area = ai.game_info.playable_area
    placement = ai.game_info.placement_grid.data_numpy.T
    terrain_height = ai.game_info.terrain_height.data_numpy  # stays [y,x] - matches height_at below

    xs, ys = np.nonzero(pathing_grid == 1)
    in_area = (xs >= area.x) & (xs < area.x + area.width) & (ys >= area.y) & (ys < area.y + area.height)
    xs, ys = xs[in_area], ys[in_area]
    not_buildable = placement[xs, ys] == 0
    xs, ys = xs[not_buildable], ys[not_buildable]

    def equal_height_around(x: int, y: int) -> bool:
        sliced = terrain_height[y - 1:y + 2, x - 1:x + 2]
        return len(np.unique(sliced)) == 1

    ramp_points = []
    vision_blockers = set()
    for x, y in zip(xs.tolist(), ys.tolist()):
        point = Point2((x, y))
        if equal_height_around(x, y):
            vision_blockers.add(point)
        else:
            ramp_points.append(point)

    groups = ai.game_info._find_groups(frozenset(ramp_points))
    ai.game_info.map_ramps = [Ramp(group, ai.game_info) for group in groups]
    ai.game_info.vision_blockers = frozenset(vision_blockers)


# ---------------------------------------------------------------------------------------------
# cost painting / nearest-safe-point queries (pure NumPy, no pathfinding involved)
# ---------------------------------------------------------------------------------------------

def _bounded_circle(center: np.ndarray, radius: float, shape: Tuple[int, int]) -> Tuple[np.ndarray, np.ndarray]:
    xx, yy = np.ogrid[:shape[0], :shape[1]]
    circle = (xx - center[0]) ** 2 + (yy - center[1]) ** 2
    return np.nonzero(circle <= radius ** 2)


def draw_circle(center, radius: float, shape: Tuple[int, int]) -> Tuple[np.ndarray, np.ndarray]:
    """Grid indices of every cell within `radius` of `center`, clipped to `shape`."""
    center = np.array((center[0], center[1]))
    upper_left = np.maximum(np.ceil(center - radius).astype(int), 0)
    lower_right = np.minimum(np.floor(center + radius).astype(int) + 1, np.array(shape))
    if np.any(lower_right <= upper_left):
        return np.array([], dtype=int), np.array([], dtype=int)
    shifted_center = center - upper_left
    bounding_shape = lower_right - upper_left
    rr, cc = _bounded_circle(shifted_center, radius, tuple(bounding_shape))
    return rr + upper_left[0], cc + upper_left[1]


def _add_disk_to_grid(arr: np.ndarray, position, disk: Tuple[np.ndarray, np.ndarray],
                       weight: float, safe: bool, initial_default_weights: float) -> np.ndarray:
    rr, cc = disk
    if len(rr) == 0:
        x, y = int(position[0]), int(position[1])
        if 0 <= x < arr.shape[0] and 0 <= y < arr.shape[1]:
            rr, cc = np.array([x]), np.array([y])
        else:
            return arr
    if initial_default_weights > 0:
        arr[rr, cc] = np.where(arr[rr, cc] == 1, initial_default_weights, arr[rr, cc])
    arr[rr, cc] += weight
    if safe:
        arr[rr, cc] = np.where(arr[rr, cc] < 1, 1, arr[rr, cc])
    return arr


def add_cost(position, radius: float, grid: np.ndarray, weight: float = 100.0,
             safe: bool = True, initial_default_weights: float = 0.0) -> np.ndarray:
    disk = draw_circle(position, radius, grid.shape)
    return _add_disk_to_grid(grid, position, disk, weight, safe, initial_default_weights)


def add_cost_to_multiple_grids(position, radius: float, grids: List[np.ndarray], weight: float = 100.0,
                                safe: bool = True, initial_default_weights: float = 0.0) -> List[np.ndarray]:
    """Same as add_cost but for several (independent, not-aliased) grids at once - the disk of
    affected cells only needs computing once."""
    disk = draw_circle(position, radius, grids[0].shape)
    for i, arr in enumerate(grids):
        grids[i] = _add_disk_to_grid(arr, position, disk, weight, safe, initial_default_weights)
    return grids


def lowest_cost_points_array(from_pos, radius: float, grid: np.ndarray) -> Optional[np.ndarray]:
    rr, cc = draw_circle(from_pos, radius, grid.shape)
    if len(rr) == 0:
        return None
    values = grid[rr, cc]
    lowest = np.min(values)
    mask = values == lowest
    return np.column_stack((rr[mask], cc[mask]))


# ---------------------------------------------------------------------------------------------
# A* pathfinding - the one piece with no pure-Python reference to port; everything above this
# point is adapted from map_analyzer's own (already pure-Python) source
# ---------------------------------------------------------------------------------------------

_NEIGHBOR_OFFSETS: Tuple[Tuple[int, int], ...] = (
    (-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1),
)


def _octile_heuristic(a: Tuple[int, int], b: Tuple[int, int], min_weight: float) -> float:
    dx = abs(a[0] - b[0])
    dy = abs(a[1] - b[1])
    return min_weight * (max(dx, dy) + (SQRT2 - 1) * min(dx, dy))


def _neighbors(node: Tuple[int, int], grid: np.ndarray, width: int, height: int):
    x, y = node
    for dx, dy in _NEIGHBOR_OFFSETS:
        nx, ny = x + dx, y + dy
        if not (0 <= nx < width and 0 <= ny < height):
            continue
        if grid[nx, ny] == np.inf:
            continue
        if dx != 0 and dy != 0:
            # diagonal move: both flanking orthogonal cells must be passable too, otherwise
            # this cuts through a blocked corner no unit could actually walk through
            if grid[x + dx, y] == np.inf or grid[x, y + dy] == np.inf:
                continue
            step_cost = SQRT2
        else:
            step_cost = 1.0
        yield (nx, ny), float(grid[nx, ny]) * step_cost


def astar(grid: np.ndarray, start: Tuple[int, int], goal: Tuple[int, int],
          max_nodes_expanded: int = 4000) -> Optional[List[Tuple[int, int]]]:
    """Returns the full cell path from start to goal (both included), or None if unreachable or
    the search budget runs out. Called for short-range tactical repositioning, not full-map
    routes, so a plain dict-based search is sized right for this - the node cap is just a safety
    valve against an unusually large/maze-like search rather than something expected to bite."""
    width, height = grid.shape
    if not (0 <= start[0] < width and 0 <= start[1] < height):
        return None
    if not (0 <= goal[0] < width and 0 <= goal[1] < height):
        return None
    if grid[start] == np.inf or grid[goal] == np.inf:
        return None
    if start == goal:
        return [start]

    finite = grid[grid != np.inf]
    min_weight = float(finite.min()) if finite.size > 0 else 1.0

    counter = itertools.count()
    open_heap: List[Tuple[float, int, Tuple[int, int]]] = [(0.0, next(counter), start)]
    came_from: Dict[Tuple[int, int], Tuple[int, int]] = {}
    g_score: Dict[Tuple[int, int], float] = {start: 0.0}
    closed = set()
    expanded = 0

    while open_heap:
        _, _, current = heapq.heappop(open_heap)
        if current in closed:
            continue
        if current == goal:
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            path.reverse()
            return path

        closed.add(current)
        expanded += 1
        if expanded > max_nodes_expanded:
            return None

        for neighbor, step_cost in _neighbors(current, grid, width, height):
            if neighbor in closed:
                continue
            tentative_g = g_score[current] + step_cost
            if tentative_g < g_score.get(neighbor, math.inf):
                g_score[neighbor] = tentative_g
                came_from[neighbor] = current
                f_score = tentative_g + _octile_heuristic(neighbor, goal, min_weight)
                heapq.heappush(open_heap, (f_score, next(counter), neighbor))

    return None


def find_eligible_point(point: Tuple[int, int], grid: np.ndarray, terrain_height: np.ndarray,
                         max_distance: float) -> Optional[Tuple[int, int]]:
    """A start/goal point may land on a blocked cell (inside a building, inside rocks) - nudge it
    to the nearest walkable cell instead, preferring one at the same terrain height first so we
    don't e.g. offer a low-ground point when the original was on high ground."""
    point = (int(point[0]), int(point[1]))
    if not (0 <= point[0] < grid.shape[0] and 0 <= point[1] < grid.shape[1]):
        return None
    if grid[point] != np.inf:
        return point

    target_height = int(terrain_height[point])
    rr, cc = draw_circle(point, max_distance, grid.shape)
    if len(rr) == 0:
        return None

    passable = grid[rr, cc] != np.inf
    same_height = np.abs(terrain_height[rr, cc].astype(np.int32) - target_height) < 8
    mask = passable & same_height
    if not np.any(mask):
        mask = passable
        if not np.any(mask):
            return None

    candidates = np.column_stack((rr[mask], cc[mask]))
    diffs = candidates - np.array(point)
    closest = np.argmin(np.sum(diffs * diffs, axis=1))
    return int(candidates[closest][0]), int(candidates[closest][1])


def pathfind(start: Point2, goal: Point2, grid: np.ndarray, terrain_height: np.ndarray,
             sensitivity: int = 2) -> Optional[List[Point2]]:
    start_cell = find_eligible_point((round(start.x), round(start.y)), grid, terrain_height, 10)
    goal_cell = find_eligible_point((round(goal.x), round(goal.y)), grid, terrain_height, 10)
    if start_cell is None or goal_cell is None:
        return None

    path = astar(grid, start_cell, goal_cell)
    if path is None:
        return None

    complete = [Point2(p) for p in path]
    # drop the start cell (a unit doesn't need to "move to" where it already is), keep every
    # sensitivity-th waypoint after that, always keep the true goal as the last point regardless
    skipped = complete[0:-1:sensitivity]
    if skipped:
        skipped.pop(0)
    skipped.append(complete[-1])
    return skipped
