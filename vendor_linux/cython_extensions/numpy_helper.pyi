from typing import Union

import numpy as np
from sc2.position import Point2

def cy_last_index_with_value(
    grid: np.ndarray, value: int, points: list[tuple[int, int]]
) -> int:
    """Finds the last index with the matching value, stopping as soon as a
    value doesn't match.
    Returns -1 if points is empty or the first value doesn't match

    Example:
    ```py
    from cython_extensions import cy_last_index_with_value

    grid = self.game_info.pathing_grid.data_numpy.T
    points: list[Point2] = [w.position.rounded for w in self.workers]
    last_pathable_index = cy_last_index_with_value(grid, 1, points)

    ```

    Parameters:
        grid: The grid to check `points` on.
        value: The value we are looking for.
        points: Points we want to check

    Returns:
        The last index in `points` that has `value`

    """
    ...

def cy_point_below_value(
    grid: np.ndarray,
    position: Point2 | tuple[float, float],
    weight_safety_limit: float = 1.0,
) -> bool:
    """Check a position on a 2D grid.
    Is it below `weight_safety_limit`?
    Useful for checking enemy influence on a position.

    Example:
    ```py
    from cython_extensions import cy_point_below_value

    # pretend grid has enemy influence added
    grid = self.game_info.pathing_grid.data_numpy.T
    safe: bool = cy_point_below_value(grid, self.start_location)
    ```

    ```
    987 ns ± 10.1 ns per loop (mean ± std. dev. of 7 runs, 1,000,000 loops each)

    Python alternative:
    4.66 µs ± 64.8 ns per loop (mean ± std. dev. of 7 runs, 100,000 loops each)
    ```

    Parameters:
        grid: The grid to check.
        position: 2D coordinate to check on grid.
        weight_safety_limit: (default = 1.0) We want to check
            if the point is less than or equal to this.

    Returns:
        The last index in `points` that has `value`.

    """
    ...

def cy_points_with_value(
    grid: np.ndarray, value: float, points: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Check points on grid, and return those that equal `value`

    Example:
    ```py
    from cython_extensions import cy_points_with_value
    import numpy as np

    # pretend grid has enemy influence added
    grid: np.ndarray = self.game_info.pathing_grid.data_numpy.T
    safe: bool = cy_points_with_value(
        grid, 1.0, [self.start_location.rounded]
    )

    ```

    Parameters:
        grid: The grid to check.
        value: 2D coordinate to check on grid.
        points: List of points we are checking.

    Returns:
        All points that equal `value` on grid.

    """
    ...

def cy_all_points_below_max_value(
    grid: np.ndarray, value: float, points_to_check: list[tuple[int, int]]
) -> bool:
    """Check points on grid, and return True if they are all below
    `value`.

    Example:
    ```py
    from cython_extensions import cy_all_points_below_max_value

    # pretend grid has enemy influence added
    grid = self.game_info.pathing_grid.data_numpy.T
    all_safe: bool = cy_all_points_below_max_value(
        grid, 1.0, [self.start_location.rounded]
    )

    ```

    Parameters:
        grid: The grid to check.
        value: The max value.
        points_to_check: List of points we are checking.

    Returns:
        Are all points_to_check below value?


    """
    ...

def cy_all_points_have_value(
    grid: np.ndarray, value: float, points: list[tuple[int, int]]
) -> bool:
    """Check points on grid, and return True if they are all equal
    `value`.

    Example:
    ```py
    from cython_extensions import cy_all_points_have_value

    # pretend grid has enemy influence added
    grid = self.game_info.pathing_grid.data_numpy.T
    all_safe: bool = cy_all_points_have_value(
        grid, 1.0, [self.start_location.rounded]
    )

    ```

    Parameters:
        grid: The grid to check.
        value: The max value.
        points: List of points we are checking.

    Returns:
        Are all points equal value?

    """
    ...
