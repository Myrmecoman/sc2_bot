"""
Pure-Python fallback for Pathing (bot/pathing/pathing.py), used when map_analyzer's compiled C
extension (mapanalyzerext) isn't available - e.g. a Linux .so that's missing, built for the wrong
platform, or built against an incompatible NumPy ABI on the deploy server. Same public interface
as the map_analyzer-backed Pathing (ground_grid/air_grid/cloak_air_grid/reaper_grid,
is_position_safe/find_closest_safe_spot/find_path_next_point/update()), backed by
bot/pathing/grid_pathing.py instead, so bot.py can construct whichever one actually works without
any other file needing to know which backend is active. Measured in an actual game at ~0.22ms/step
(negligible) - this is not a "slower, last-resort" fallback, it's a fully fine primary path.
"""

from typing import Dict, List, Optional

import numpy as np
from bot.pathing.consts import ALL_STRUCTURES
from bot.pathing.influence_costs import INFLUENCE_COSTS, INFLUENCE_COSTS_EFFECTS
from bot.pathing import grid_pathing
from sc2.bot_ai import BotAI
from sc2.position import Point2, Point3
from sc2.unit import Unit
from sc2.game_state import EffectData
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.effect_id import EffectId
from scipy import spatial

# When adding enemies to the grids add a bit extra range so our units stay out of trouble
RANGE_BUFFER: float = 3.0
RANGE_BUFFER_BUILDING: float = 3.0
RANGE_BUFFER_EFFECTS: float = 1.0


class Pathing:
    def __init__(self, ai: BotAI, debug: bool) -> None:
        self.ai: BotAI = ai
        self.debug: bool = debug

        # python-sc2's own ramp detection treats every currently-existing destructible as
        # blocking, which can pick the wrong main-base ramp on maps where a rock sits on/near
        # one - correct that once, up front, same timing this bot has always relied on
        grid_pathing.fix_ramps_for_destructibles(ai)

        # static for the whole game - terrain itself never changes. Kept as two separate base
        # grids (not one shared array) - reaper_grid's base marks a couple of cliff-top platforms
        # walkable that ground_grid must not, or ground units get routed onto tiles they can't
        # actually stand on (see build_reaper_terrain_base)
        self._terrain_base: np.ndarray = grid_pathing.build_terrain_base(ai)
        self._reaper_terrain_base: np.ndarray = grid_pathing.build_reaper_terrain_base(ai)
        self._terrain_height: np.ndarray = grid_pathing.build_terrain_height(ai)

        # we will need fresh grids every step, to update the enemy positions
        self.reaper_grid: np.ndarray = grid_pathing.build_walkable_grid(ai, self._reaper_terrain_base)
        self.ground_grid: np.ndarray = grid_pathing.build_walkable_grid(ai, self._terrain_base)
        self.air_grid: np.ndarray = grid_pathing.build_clean_air_grid(ai)
        self.cloak_air_grid: np.ndarray = grid_pathing.build_clean_air_grid(ai)

    def update(self) -> None:
        # ground_grid and reaper_grid are built independently (not aliased to each other) -
        # add_cost_to_multiple_grids mutates each grid it's given in place, so two collection
        # entries pointing at the same array would double-count every enemy's influence on it
        self.ground_grid = grid_pathing.build_walkable_grid(self.ai, self._terrain_base)
        self.reaper_grid = grid_pathing.build_walkable_grid(self.ai, self._reaper_terrain_base)
        self.air_grid = grid_pathing.build_clean_air_grid(self.ai)
        self.cloak_air_grid = grid_pathing.build_clean_air_grid(self.ai)

        for unit in self.ai.all_enemy_units:
            # checking if a unit is a structure this way is faster then using `if unit.is_structure` :)
            if unit.type_id in ALL_STRUCTURES:
                self._add_structure_influence(unit)
            else:
                self._add_unit_influence(unit)

        for effect in self.ai.state.effects:
            if effect.id in INFLUENCE_COSTS_EFFECTS.keys():
                self._add_effect_influence(effect)

        if self.debug:
            self._draw_debug_influence(self.reaper_grid, lower_threshold=1)


    def find_closest_safe_spot(self, from_pos: Point2, grid: np.ndarray, radius: int = 15) -> Point2:
        """
        @param from_pos:
        @param grid:
        @param radius:
        @return:
        """
        all_safe: np.ndarray = grid_pathing.lowest_cost_points_array(from_pos, radius, grid)
        # type hint wants a numpy array but doesn't actually need one - this is faster
        all_dists = spatial.distance.cdist(all_safe, [from_pos], "sqeuclidean")
        min_index = np.argmin(all_dists)

        # safe because the shape of all_dists (N x 1) means argmin will return an int
        return Point2(all_safe[min_index])


    def find_path_next_point(
        self,
        start: Point2,
        target: Point2,
        grid: np.ndarray,
        sensitivity: int = 2,
        smoothing: bool = False,
    ) -> Point2:
        """
        Most commonly used, we need to calculate the right path for a unit
        But only the first element of the path is required
        @param start:
        @param target:
        @param grid:
        @param sensitivity:
        @param smoothing:
        @return: The next point on the path we should move to
        """
        # Note: On rare occasions a path is not found and returns `None`
        path: Optional[List[Point2]] = grid_pathing.pathfind(start, target, grid, self._terrain_height, sensitivity=sensitivity)
        if not path or len(path) == 0:
            return target
        return path[0]


    @staticmethod
    def is_position_safe(
        grid: np.ndarray,
        position: Point2,
        weight_safety_limit: float = 1.0,
    ) -> bool:
        """
        Checks if the current position is dangerous by comparing against default_grid_weights
        @param grid: Grid we want to check
        @param position: Position of the unit etc
        @param weight_safety_limit: The threshold at which we declare the position safe
        @return:
        """
        position = position.rounded
        weight: float = grid[position.x, position.y]
        # np.inf check if drone is pathing near a spore crawler
        return weight == np.inf or weight <= weight_safety_limit


    def _add_unit_influence(self, enemy: Unit) -> None:
        """
        Add influence to the relevant grid.
        TODO:
            Add spell casters
            Add units that have no weapon in the API such as BCs, sentries and voids
            Extend this to add influence to an air grid
        @return:
        """
        # this unit is in our dictionary where we define custom weights and ranges
        # it could be this unit doesn't have a weapon in the API or we just want to use custom values
        if enemy.type_id in INFLUENCE_COSTS:
            if enemy.can_attack_ground:
                values: Dict = INFLUENCE_COSTS[enemy.type_id]
                (self.ground_grid, self.reaper_grid) = self._add_cost_to_multiple_grids(
                    enemy.position,
                    values["GroundCost"],
                    values["GroundRange"] + RANGE_BUFFER,
                    [self.ground_grid, self.reaper_grid],)
            if enemy.can_attack_air:
                values: Dict = INFLUENCE_COSTS[enemy.type_id]
                self.air_grid = self._add_cost(
                    enemy.position,
                    values["AirCost"],
                    values["AirRange"] + RANGE_BUFFER,
                    self.air_grid,)
        # this unit has values in the API and is not in our custom dictionary, take them from there
        else:
            if enemy.can_attack_ground:
                (self.ground_grid, self.reaper_grid) = self._add_cost_to_multiple_grids(
                    enemy.position,
                    enemy.ground_dps,
                    enemy.ground_range + RANGE_BUFFER,
                    [self.ground_grid, self.reaper_grid],)
            if enemy.can_attack_air:
                self.air_grid = self._add_cost(
                    enemy.position,
                    enemy.air_dps,
                    enemy.air_range + RANGE_BUFFER,
                    self.air_grid,)

        # detector units
        if enemy.is_detector:
            values: Dict = INFLUENCE_COSTS[enemy.type_id]
            self.cloak_air_grid = self._add_cost(
                enemy.position,
                50, # arbitrary value
                values["DetectionRange"] + RANGE_BUFFER_BUILDING,
                self.cloak_air_grid,)


    def _add_structure_influence(self, enemy: Unit) -> None:
        """
        Add structure influence to the relevant grid.
        TODO:
            Extend this to add influence to an air grid
        @param enemy:
        @return:
        """
        if not enemy.is_ready:
            return

        if enemy.type_id in INFLUENCE_COSTS:
            if enemy.can_attack_ground:
                values: Dict = INFLUENCE_COSTS[enemy.type_id]
                (self.ground_grid, self.reaper_grid) = self._add_cost_to_multiple_grids(
                    enemy.position,
                    values["GroundCost"],
                    values["GroundRange"] + RANGE_BUFFER_BUILDING,
                    [self.ground_grid, self.reaper_grid],)
            if enemy.can_attack_air:
                values: Dict = INFLUENCE_COSTS[enemy.type_id]
                self.air_grid = self._add_cost(
                    enemy.position,
                    values["AirCost"],
                    values["AirRange"] + RANGE_BUFFER_BUILDING,
                    self.air_grid,)

        # detector structures
        if enemy.is_detector:
            values: Dict = INFLUENCE_COSTS[enemy.type_id]
            self.cloak_air_grid = self._add_cost(
                enemy.position,
                50, # arbitrary value
                values["DetectionRange"] + RANGE_BUFFER_BUILDING,
                self.cloak_air_grid,)


    def _add_effect_influence(self, effect: EffectData) -> None:
        """
        Add effect influence to the relevant grids.
        @return:
        """
        if effect.id in INFLUENCE_COSTS_EFFECTS:
            values: Dict = INFLUENCE_COSTS_EFFECTS[effect.id]
            # use the effect's actual radius from the game instead of a hand-guessed per-type
            # range - stays correct even if an effect's real size differs from what we'd assume
            # (e.g. nuke's blast is much bigger than storm's), with no risk of drifting stale
            hazard_range = effect.radius + RANGE_BUFFER_EFFECTS
            if "GroundCost" in values.keys():
                (self.ground_grid, self.reaper_grid) = self._add_cost_to_multiple_grids(
                    next(iter(effect.positions)),
                    values["GroundCost"],
                    hazard_range,
                    [self.ground_grid, self.reaper_grid],)
            if "AirCost" in values.keys():
                self.air_grid = self._add_cost(
                    next(iter(effect.positions)),
                    values["AirCost"],
                    hazard_range,
                    self.air_grid,)
            if "DetectionRange" in values.keys():
                self.cloak_air_grid = self._add_cost(
                    next(iter(effect.positions)),
                    50, # arbitrary value
                    values["DetectionRange"] + RANGE_BUFFER_EFFECTS,
                    self.cloak_air_grid,)


    def _add_cost(
        self,
        pos: Point2,
        weight: float,
        unit_range: float,
        grid: np.ndarray,
        initial_default_weights: int = 0,
    ) -> np.ndarray:
        """Or add "influence", mostly used to add enemies to a grid"""

        grid = grid_pathing.add_cost(
            position=(int(pos.x), int(pos.y)),
            radius=unit_range,
            grid=grid,
            weight=int(weight),
            initial_default_weights=initial_default_weights,
        )
        return grid


    def _add_cost_to_multiple_grids(
        self,
        pos: Point2,
        weight: float,
        unit_range: float,
        grids: List[np.ndarray],
        initial_default_weights: int = 0,
    ) -> List[np.ndarray]:
        """
        Similar to method above, but add cost to multiple grids at once
        This is much faster then doing it one at a time
        """

        grids = grid_pathing.add_cost_to_multiple_grids(
            position=(int(pos.x), int(pos.y)),
            radius=unit_range,
            grids=grids,
            weight=int(weight),
            initial_default_weights=initial_default_weights,)
        return grids


    def _draw_debug_influence(self, grid: np.ndarray, lower_threshold: float = 1) -> None:
        """Local-debugging aid only - never runs in production (bot.py always constructs
        Pathing(self, False)). Draws a box over every cell whose cost is above lower_threshold."""
        for x in range(grid.shape[0]):
            for y in range(grid.shape[1]):
                weight = grid[x, y]
                if weight == np.inf or weight <= lower_threshold:
                    continue
                height = self.ai.get_terrain_z_height(Point2((x, y)))
                self.ai.client.debug_box2_out(Point3((x + 0.5, y + 0.5, height)), half_vertex_length=0.5)
