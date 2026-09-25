from typing import Union

from sc2.position import Point2

def cy_angle_to(
    from_pos: Union[Point2, tuple[float, float]],
    to_pos: Union[Point2, tuple[float, float]],
) -> float:
    """Angle from point to other point in radians

    Args:
        from_pos: First 2D point.
        to_pos: Measure angle to this 2D point.

    Returns:
        angle: Angle in radians.

    """
    ...

def cy_angle_diff(a: float, b: float) -> float:
    """Absolute angle difference between 2 angles

    Args:
        a: First angle.
        b: Second angle.

    Returns:
        angle_difference: Difference between the two angles.
    """
    ...

def cy_distance_to(
    p1: Union[Point2, tuple[float, float]], p2: Union[Point2, tuple[float, float]]
) -> float:
    """Check distance between two Point2 positions.

    Example:
    ```py
    from cython_functions import cy_distance_to

    dist: float = cy_distance_to(
        self.start_location, self.game_info.map_center
    )
    ```
    ```
    cy_distance_to(Point2, Point2)
    157 ns ± 2.69 ns per loop (mean ± std. dev. of 7 runs, 10,000,000 loops each)

    cy_distance_to(unit1.position, unit2.position)
    219 ns ± 10.5 ns per loop (mean ± std. dev. of 7 runs, 1,000,000 loops each)

    Python alternative:

    Point1.distance_to(Point2)
    386 ns ± 2.71 ns per loop (mean ± std. dev. of 7 runs, 1,000,000 loops each)

    unit1.distance_to(unit2)
    583 ns ± 7.89 ns per loop (mean ± std. dev. of 7 runs, 1,000,000 loops each)
    ```

    Args:
        p1: First point.
        p2: Measure to this point.

    Returns:
        distance: Distance in tiles.


    """
    ...

def cy_distance_to_squared(
    p1: Union[Point2, tuple[float, float]], p2: Union[Point2, tuple[float, float]]
) -> float:
    """Similar to `cy_distance_to` but without a square root operation.
    Use this for ~1.3x speedup

    Example:
    ```python
    from cython_functions import cy_distance_to_squared

    dist: float = cy_distance_to_squared(
        self.start_location, self.game_info.map_center
    )
    ```

    Args:
        p1: First point.
        p2: Measure to this point.

    Returns:
        distance: Distance in tiles, squared.
    """
    ...

def cy_towards(
    start_pos: Point2, target_pos: Point2, distance: float
) -> tuple[float, float]:
    """Get position from start_pos towards target_pos based on distance.

    Example:
    ```py
    from cython_functions import cy_towards

    new_pos: Tuple[float, float] = cy_towards(
        self.start_location,
        self.game_info.map_center,
        12.0
    )
    ```

    Note: For performance reasons this returns the point2 as a tuple, if a
    python-sc2 Point2 is required it's up to the user to convert it.

    Example:
    ```py
    new_pos: Point2 = Point2(
        cy_towards(
            self.start_location, self.enemy_start_locations, 10.0
        )
    )
    ```

    Though for best performance it is recommended to simply work with the tuple if possible:
    ```py
    new_pos: tuple[float, float] = cy_towards(
        self.start_location, self.enemy_start_locations, 10.0
    )
    ```

    ```
    191 ns ± 0.855 ns per loop (mean ± std. dev. of 7 runs, 10,000,000 loops each)

    Python-sc2's `start_pos.towards(target_pos, distance)` alternative:
    2.73 µs ± 18.9 ns per loop (mean ± std. dev. of 7 runs, 100,000 loops each)
    ```


    Args:
        start_pos: Start from this 2D position.
        target_pos: Go towards this 2D position.
        distance: How far we go towards target_pos.

    Returns:
        The new position as a tuple of x and y coordinates.
    """
    ...

def cy_get_angle_between_points(
    point_a: Union[Point2, tuple[float, float]],
    point_b: Union[Point2, tuple[float, float]],
) -> float:
    """Get the angle between two points as if they were vectors from the origin.

    Example:
    ```py
    from cython_functions import cy_get_angle_between_points

    angle: float = cy_get_angle_between_points(
        self.start_location, self.game_info.map_center
    )
    ```

    Args:
        point_a: First point.
        point_b: Measure to this point.

    Returns:
        The angle between the two points.
    """
    ...

def cy_find_average_angle(
    start_point: Union[Point2, tuple[float, float]],
    reference_point: Union[Point2, tuple[float, float]],
    points: list[Point2],
) -> float:
    """Find the average angle between the points and the reference point.

    Given a starting point, a reference point, and a list of points, find the average
    angle between the vectors from the starting point to the reference point and the
    starting point to the points.

    Example:
    ```py
    from cython_extensions import cy_find_average_angle

    angle: float = cy_get_angle_between_points(
        self.start_location,
        self.game_info.map_center,
        [w.position for w in self.workers]
    )
    ```

    Args:
        start_point: Origin for the vectors to the other given points.
        reference_point: Vector forming one leg of the angle.
        points: Points to calculate the angle between relative
            to the reference point.

    Returns:
        Average angle in radians between the reference
        point and the given points.

    """
    ...

def cy_find_correct_line(
    points: list[Point2], base_location: Union[Point2, tuple[float, float]]
) -> tuple[tuple[float], tuple[float]]:
    """
    Given a list of points and a center point, find if there's a line such that all
    other points are above or below the line. Returns the line in the form
    Ax + By + C = 0 and the point that was used.

    If no such line is found, it returns ((0, 0, 0), <last_point_checked>).

    Args:
        points: Points that need to be on one side of the line.
        base_location: Starting point for the line.

    Returns:
        First element is the coefficients of Ax + By + C = 0.
        Second element is the point used to form the line.
    """
    ...

def cy_translate_point_along_line(
    point: Union[Point2, tuple[float, float]], a_value: float, distance: float
) -> tuple[float, float]:
    """
    Translates a point along a line defined by a slope value.

    This function moves a given point along a line in a direction
    determined by the slope `a_value`, by a specified `distance`.
    The new point after translation is returned.

    Args:
        point: The point to be translated, given as either a `Point2`
        object or a tuple of `(x, y)` coordinates.
        a_value: The slope of the line along which the point will be moved.
        distance: The distance to move the point along the line.

    Returns:
        A tuple representing the new position of the point
        after translation.
    """
    ...
