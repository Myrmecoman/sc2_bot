from typing import Union

from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

def cy_center(units: Union[Units, list[Unit]]) -> tuple[float, float]:
    """Given some units, find the center point.


    Example:
    ```py
    from ares.cython_functions.units_utils import cy_center

    centroid: Tuple[float, float] = cy_center(self.workers)

    # centroid_point2 = Point2(centroid)
    ```

    ```
    54.2 µs ± 137 ns per loop (mean ± std. dev. of 7 runs, 10,000 loops each)

    `python-sc2`'s `units.center` alternative:
    107 µs ± 255 ns per loop (mean ± std. dev. of 7 runs, 10,000 loops each)
    ```

    Parameters:
        units: Units we want to check

    Returns:
        Centroid of all units positions

    """
    ...

def cy_closest_to(
    position: Union[Point2, tuple[float, float]], units: Union[Units, list[Unit]]
) -> Unit:
    """Iterate through `units` to find closest to `position`.

    Example:
    ```py
    from cython_functions import cy_closest_to
    from sc2.unit import Unit

    closest_unit: Unit = cy_closest_to(self.start_location, self.workers)
    ```

    ```
    14.3 µs ± 135 ns per loop (mean ± std. dev. of 7 runs, 100,000 loops each)

    python-sc2's `units.closest_to()` alternative:
    98.9 µs ± 240 ns per loop (mean ± std. dev. of 7 runs, 10,000 loops each)

    If using python-sc2's `units.closest_to(Point2):
    200 µs ± 1.02 µs per loop (mean ± std. dev. of 7 runs, 1,000 loops each)
    ```

    Parameters:
        position: Position to measure distance from.
        units: Collection of units we want to check.

    Returns:
        Unit closest to `position`.

    """
    ...

def cy_find_units_center_mass(
    units: Union[Units, list[Unit]], distance: float
) -> tuple[tuple[float, float], int]:
    """Given some units, find the center mass

    Example:
    ```py
    from cython_functions import cy_find_units_center_mass
    from sc2.position import Point2

    center_mass: Point2
    num_units: int
    center_mass, num_units = cy_find_units_center_mass(self.units, 10.0)
    ```

    ```
    47.8 ms ± 674 µs per loop (mean ± std. dev. of 7 runs, 10 loops each)

    python alternative:
    322 ms ± 5.2 ms per loop (mean ± std. dev. of 7 runs, 1 loop each)
    ```

    Parameters:
        units: Collection of units we want to check.
        distance: The distance to check from the center mass.

    Returns:
        The center mass, and how many units are within `distance` of the center mass.
    """
    ...

def cy_in_attack_range(
    unit: Unit, units: Union[Units, list[Unit]], bonus_distance: float = 0.0
) -> list[Unit]:
    """Find all units that unit can shoot at.

    Doesn't check if the unit weapon is ready. See:
    `cython_functions.attack_ready`

    Example:
    ```py
    from cython_functions import cy_in_attack_range
    from sc2.unit import Unit

    in_attack_range: list[Unit] = cy_in_attack_range(self.workers[0], self.enemy_units)
    ```

    ```
    7.28 µs ± 26.3 ns per loop (mean ± std. dev. of 7 runs, 100,000 loops each)

    python-sc2's `units.in_attack_range_of(unit)` alternative:
    30.4 µs ± 271 ns per loop (mean ± std. dev. of 7 runs, 10,000 loops each)
    ```

    Parameters:
        unit: The unit to measure distance from.
        units: Collection of units we want to check.
        bonus_distance: Additional distance to consider.

    Returns:
        Units that are in attack range of `unit`.

    """
    ...

def cy_sorted_by_distance_to(
    units: Union[Units, list[Unit]], position: Point2, reverse: bool = False
) -> list[Unit]:
    """Sort units by distance to `position`

    Example:
    ```py
    from cython_functions import cy_sorted_by_distance_to
    from sc2.unit import Unit

    sorted_by_distance: list[Unit] = cy_sorted_by_distance_to(
        self.workers, self.start_location
    )
    ```

    ```
    33.7 µs ± 190 ns per loop (mean ± std. dev. of 7 runs, 10,000 loops each)

    python-sc2's `units.sorted_by_distance_to(position)` alternative:
    246 µs ± 830 ns per loop (mean ± std. dev. of 7 runs, 1,000 loops each)
    ```

    Parameters:
        units: Units we want to sort.
        position: Sort by distance to this position.
        reverse: Not currently used.

    Returns:
        Units sorted by distance to position.

    """

def cy_closer_than(
    units: Union[Units, list[Unit]],
    max_distance: float,
    position: Union[Point2, tuple[float, float]],
) -> list[Unit]:
    """Find all units closer than `distance` to `position`.

    Example:
    ```py
    from cython_functions import cy_closer_than
    from sc2.unit import Unit

    close_units: list[Unit] = cy_closer_than(
        self.workers, 5.0, self.start_location
    )
    ```

    ```
    1.37 µs ± 2.49 ns per loop (mean ± std. dev. of 7 runs, 1,000,000 loops each)

    python-sc2's `units.closer_than(distance, position)` alternative:
    12.7 µs ± 53.4 ns per loop (mean ± std. dev. of 7 runs, 100,000 loops each)
    ```

    Parameters:
        units: Units we want to check.
        max_distance: Maximum distance to consider.
        position: Position to measure distance from.
    Returns:
        Units closer than `max_distance` to `position`.

    """

def cy_further_than(
    units: Union[Units, list[Unit]],
    min_distance: float,
    position: Union[Point2, tuple[float, float]],
) -> list[Unit]:
    """Find all units further than `distance` to `position`.

    Example:
    ```py
    from cython_functions import cy_further_than
    from sc2.unit import Unit

    far_units: list[Unit] = cy_further_than(
        self.workers, 5.0, self.start_location
    )
    ```

    ```
    1.01 µs ± 2.79 ns per loop (mean ± std. dev. of 7 runs, 1,000,000 loops each)

    python-sc2's `units.further_than(distance, position)` alternative:
    12.5 µs ± 52.6 ns per loop (mean ± std. dev. of 7 runs, 100,000 loops each)
    ```

    Parameters:
        units: Units we want to check.
        min_distance: Minimum distance to consider.
        position: Position to measure distance from.
    Returns:
        Units further than `min_distance` to `position`.

    """
