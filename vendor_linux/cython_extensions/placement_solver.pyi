import numpy as np

def cy_can_place_structure(
    building_origin: tuple[int, int],
    building_size: tuple[int, int],
    creep_grid: np.ndarray,
    placement_grid: np.ndarray,
    pathing_grid: np.ndarray,
    avoid_creep: bool = True,
    include_addon: bool = False,
    skip_creep_check: bool = False,
) -> bool:
    """Simulate whether a structure can be placed at `building_origin`
    Fast alternative to python-sc2 `can_place`

    Example:
    ```py
    from cython_extensions import cy_can_place_structure

    can_place: bool = cy_can_place_structure(
        (155, 45),
        (3, 3),
        self.ai.state.creep.data_numpy,
        self.ai.game_info.placement_grid.data_numpy,
        self.ai.game_info.pathing_grid.data_numpy,
        avoid_creep=self.race != Race.Zerg,
        include_addon=False,
    )
    ```

    ```
    1.21 µs ± 891 ns per loop (mean ± std. dev. of 1000 runs, 10 loops each)
    ```

    Parameters:
        building_origin: The top left corner of the intended structure.
        building_size: For example: (3, 3) for barracks.
            (2, 2) for depot,
            (5, 5) for command center.
        creep_grid: Creep grid.
        placement_grid:
        pathing_grid:
        avoid_creep: Ensure this is False if checking Zerg structures.
        include_addon: Check if there is room for addon too.
        skip_creep_check: Useful for hatchery or nydus canals.
            They can place on or off creep.

    Returns:
        Can we place structure at building_origin?


    """
    ...

def cy_find_building_locations(
    kernel: np.ndarray,
    x_stride: int,
    y_stride: int,
    x_bounds: tuple[int, int],
    y_bounds: tuple[int, int],
    creep_grid: np.ndarray,
    placement_grid: np.ndarray,
    pathing_grid: np.ndarray,
    points_to_avoid_grid: np.ndarray,
    building_width: int,
    building_height: int,
    avoid_creep: bool = True,
) -> list[tuple[float, float]]:
    """Use a convolution pass to find all possible building locations in an area
    Check `ares-sc2` for a full example of using this to calculate
    building formations.

    https://github.com/AresSC2/ares-sc2/blob/main/src/ares/managers/placement_manager.py

    Example:
    ```py
    from cython_extensions import cy_find_building_locations

    # find 3x3 locations, making room for addons.
    # check out map_analysis.cy_get_bounding_box to calculate
    # raw_x_bounds and raw_x_bounds
    three_by_three_positions = cy_find_building_locations(
        kernel=np.ones((5, 3), dtype=np.uint8),
        x_stride=5,
        y_stride=3,
        x_bounds=raw_x_bounds,
        y_bounds=raw_y_bounds,
        creep_grid=creep_grid,
        placement_grid=placement_grid,
        pathing_grid=pathing_grid,
        points_to_avoid_grid=self.points_to_avoid_grid,
        building_width=3,
        building_height=3,
        avoid_creep=True
    )

    ```

    ```
    64.8 µs ± 4.05 µs per loop (mean ± std. dev. of 1000 runs, 10 loops each)
    ```

    Parameters:
        kernel: The size of the sliding window that scans this area.
        x_stride: The x distance the kernel window moves each step.
        y_stride: The y distance the kernel window moves downwards.
        x_bounds: The starting point of the algorithm.
        y_bounds: The end point of the algorithm.
        creep_grid:
        placement_grid:
        pathing_grid:
        points_to_avoid_grid: Grid containing `1`s where we shouldn't
            place anything.
        building_width:
        building_height:
        avoid_creep: Ensure this is False if checking Zerg structures.

    Returns:
        Final list of positions that make up the building formation.


    """
    ...
