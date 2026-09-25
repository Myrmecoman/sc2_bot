from typing import Union

import numpy as np
from sc2.position import Point2

def cy_get_bounding_box(
    coordinates: set[Point2],
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Given a set of coordinates, draw a box that fits
    all the points.

    Example:
    ```py
    from cython_extensions import cy_get_bounding_box

    points: set[Point2] = {w.position for w in self.workers}
    raw_x_bounds, raw_y_bounds = cy_get_bounding_box(points)

    ```

    Args:
        coordinates:
            The points around which the bounding box should be drawn.

    Returns:
        A tuple containing two tuples:
        - The first tuple represents the minimum and maximum x values
        (xmin, xmax).
        - The second tuple represents the minimum and maximum y values
        (ymin, ymax).

    """
    ...

def cy_flood_fill_grid(
    start_point: Union[Point2, tuple],
    terrain_grid: np.ndarray,
    pathing_grid: np.ndarray,
    max_distance: int,
    cutoff_points: set,
) -> set[tuple]:
    """Given a set of coordinates, draw a box that fits
    all the points.

    Example:
    ```py
    from cython_extensions import cy_flood_fill_grid

    all_points = terrain_flood_fill(
        start_point=self.start_location.rounded,
        terrain_grid=self.game_info.terrain_height.data_numpy.T,
        pathing_grid=self.game_info.pathing_grid.data_numpy.T,
        max_distance=40,
        choke_points={}
    )

    ```

    Parameters
    ----------
    start_point : Start algorithm from here.
    terrain_grid : Numpy array containing heights for the map.
    pathing_grid : Numpy array containing pathing values for the map.
    max_distance : The maximum distance the flood fill should reach before halting.
    cutoff_points : Points which we don't want the algorithm to pass.
    Choke points are a good use case.

    Returns
    -------
    tuple of tuple of float :
        A pair of coordinates that determine the box in the following format:
        ((xmin, xmax), (ymin, ymax))

    """
    ...
