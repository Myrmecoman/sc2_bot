"""
This provides a wrapper for the MapAnalyzer library
Here we are only using the Pathing module in MapAnalyzer, there are more features to explore!
We add enemy influence to the pathing grids
And implement pathing methods our units can use
"""

from typing import Dict, List, Optional

import numpy as np
from bot.pathing.consts import ALL_STRUCTURES
from bot.pathing.influence_costs import INFLUENCE_COSTS
from sc2.bot_ai import BotAI
from sc2.position import Point2
from sc2.unit import Unit
from scipy import spatial

from MapAnalyzer import MapData

# When adding enemies to the grids add a bit extra range so our units stay out of trouble
RANGE_BUFFER: float = 3.0
RANGE_BUFFER_BUILDING: float = 3.0


class Pathing:
    def __init__(self, ai: BotAI, debug: bool) -> None:
        self.ai: BotAI = ai
        self.debug: bool = debug

        # initialize MapAnalyzer library
        self.map_data: MapData = MapData(ai)

        # we will need fresh grids every step, to update the enemy positions

        # for reapers / colossus we need a special grid to use the cliffs
        self.reaper_grid: np.ndarray = self.map_data.get_climber_grid()
        # ground grid not actually used in this example, but is setup ready to go for other ground units
        self.ground_grid: np.ndarray = self.map_data.get_pyastar_grid()
        # air grid if needed, would need to add enemy influence
        self.air_grid: np.ndarray = self.map_data.get_clean_air_grid()
        # air grid for cloaked units indicating zones without detection
        self.cloak_air_grid: np.ndarray = self.map_data.get_clean_air_grid()

    def update(self) -> None:
        self.ground_grid = self.map_data.get_pyastar_grid()
        self.reaper_grid = self.map_data.get_climber_grid()
        self.air_grid = self.map_data.get_clean_air_grid()
        self.cloak_air_grid = self.map_data.get_clean_air_grid()

        for unit in self.ai.all_enemy_units:
            # checking if a unit is a structure this way is faster then using `if unit.is_structure` :)
            if unit.type_id in ALL_STRUCTURES:
                self._add_structure_influence(unit)
            else:
                self._add_unit_influence(unit)

        # TODO: Add effect influence like storm, ravager biles, nukes etc
        #   `for effect in self.ai.state.effects: ...`

        if self.debug:
            self.map_data.draw_influence_in_game(self.reaper_grid, lower_threshold=1)


    def find_closest_safe_spot(self, from_pos: Point2, grid: np.ndarray, radius: int = 15) -> Point2:
        """
        @param from_pos:
        @param grid:
        @param radius:
        @return:
        """
        all_safe: np.ndarray = self.map_data.lowest_cost_points_array(from_pos, radius, grid)
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
        path: Optional[List[Point2]] = self.map_data.pathfind(start, target, grid, sensitivity=sensitivity, smoothing=smoothing)
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


    def _add_cost(
        self,
        pos: Point2,
        weight: float,
        unit_range: float,
        grid: np.ndarray,
        initial_default_weights: int = 0,
    ) -> np.ndarray:
        """Or add "influence", mostly used to add enemies to a grid"""

        grid = self.map_data.add_cost(
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

        grids = self.map_data.add_cost_to_multiple_grids(
            position=(int(pos.x), int(pos.y)),
            radius=unit_range,
            grids=grids,
            weight=int(weight),
            initial_default_weights=initial_default_weights,)
        return grids
