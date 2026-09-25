from typing import Optional, Union

import numpy as np
from sc2.ids.unit_typeid import UnitTypeId as UnitID
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

def cy_has_creep(creep_numpy_grid: np.ndarray, position: Point2) -> bool:
    """
    Check if a position has creep.

    Example:
    ```py
    from cython_functions import cy_has_creep
    from sc2.position import Point2

    position: Point2 = self.start_location

    has_creep: bool = cy_has_creep(
        self.state.creep.data_numpy,
        position
    )
    ```

    ```
    243 ns ± 4.4 ns per loop (mean ± std. dev. of 7 runs, 1,000,000 loops each)
    ```

    Args:
        creep_numpy_grid: Position to check for power.
        position: The pylons we want to check.


    Returns:
        True if `position` has creep, False otherwise.
    """
    ...

def cy_in_pathing_grid_ma(pathing_numpy_grid: np.ndarray, position: Point2) -> bool:
    """
    Check if a position is pathable. This is optimized for use with
    numpy pathing grids from MapAnalyzer that contain enemy influence.
    The grids passed in here are already transposed vs the burnysc2
    default pathing grid.
    This may work with other custom numpy pathing grids that contain float values.

    Example using ares sc2 (which has MapAnalyzer grids):
    ```py
    from cython_functions import cy_in_pathing_grid_ma
    from sc2.position import Point2

    position: Point2 = self.start_location
    # ares function to get pathing grid containing enemy influence
    grid: np.ndarray = self.mediator.get_ground_grid

    is_pathable: bool = cy_in_pathing_grid_ma(
        grid, position
    )
    ```

    ```
    243 ns ± 1.51 ns per loop (mean ± std. dev. of 7 runs, 1,000,000 loops each)
    ```

    Args:
        pathing_numpy_grid: The 2D grid to check on.
        position: The postions we want to check.


    Returns:
        True if `position` is pathable, False otherwise.
    """
    ...

def cy_in_pathing_grid_burny(pathing_numpy_grid: np.ndarray, position: Point2) -> bool:
    """
    Check if a position is pathable. This is optimized for use with
    the numpy pathing grid found in burnysc2.
    `self.game_info.pathing_grid.data_numpy` which only contains
    0s and 1s.

    This is a fast replacement for `self.in_pathing_grid(position)` function
    in burnysc2.

    If using MapAnalyzer grids or some other type of numpy grid,
    check out `cy_in_pathing_grid_ma` instead/

    Example using burny sc2:
    ```py
    from cython_functions import cy_in_pathing_grid_burny
    from sc2.position import Point2

    position: Point2 = self.start_location

    is_pathable: bool = cy_in_pathing_grid_burny(
        self.game_info.pathing_grid.data_numpy,
        position
    )
    ```

    ```
    243 ns ± 1.51 ns per loop (mean ± std. dev. of 7 runs, 1,000,000 loops each)
    ```

    Args:
        pathing_numpy_grid: The 2D grid to check on.
        position: The postions we want to check.


    Returns:
        True if `position` is pathable, False otherwise.
    """
    ...

def cy_pylon_matrix_covers(
    position: Union[Point2, tuple[float, float]],
    pylons: Union[Units, list[Unit]],
    height_grid: np.ndarray,
    pylon_build_progress: Optional[float] = 1.0,
) -> bool:
    """Check if a position is powered by a pylon.

    Example:
    ```py
    from cython_functions import cy_pylon_matrix_covers
    from sc2.position import Point2

    # check if start location is powered by pylon
    position: Point2 = self.start_location

    can_place_structure_here: bool = cy_pylon_matrix_covers(
        position,
        self.structures(UnitTypeId.PYLON),
        self.game_info.terrain_height.data_numpy
    )
    ```

    ```
    1.85 µs ± 8.72 ns per loop (mean ± std. dev. of 7 runs, 1,000,000 loops each)
    ```

    Args:
        position: Position to check for power.
        pylons: The pylons we want to check.
        height_grid: Height grid supplied from `python-sc2` as a numpy array.
        pylon_build_progress: If less than 1.0, check near pending pylons.
            Default is 1.0.

    Returns:
        True if `position` has power, False otherwise.

    """

def cy_unit_pending(ai: "BotAI", unit_type: UnitID) -> int:
    """Check how many unit_type are pending.

    Faster unit specific alternative to `python-sc2`'s `already_pending`

    Example:
    ```py
    from cython_functions import cy_unit_pending
    from sc2.ids.unit_typeid import UnitTypeId

    num_marines_pending: int = cy_unit_pending(UnitTypeId.MARINE)
    ```
    ```
    453 ns ± 9.35 ns per loop (mean ± std. dev. of 7 runs, 1,000,000 loops each)

    Python-sc2 `already_pending` alternative:
    2.82 µs ± 29 ns per loop (mean ± std. dev. of 7 runs, 100,000 loops each)
    ```

    Args:
        ai: Bot object that will be running the game.
        unit_type: Unit type we want to check.

    Returns:
        How many unit_type are currently building.


    """

def cy_structure_pending(ai: "BotAI", unit_type: UnitID) -> int:
    """Check how many structures of unit_type are pending
    Faster structure specific alternative to `python-sc2`'s `already_pending`
    
    Attention: This only counts buildings that are being constructed, or are in unit.order_queue.
    It does not count buildings, which are in a plan to be built, but have not started construction yet.
    
    
    Example:
    ```py
    from cython_functions import cy_structure_pending
    from sc2.ids.unit_typeid import UnitTypeId
    num_pylons_pending: int = cy_structure_pending(self, UnitTypeId.PYLON)
    ```

    
    ```
    Benchmarked in a realistic scenario since caching is involved:
    Simulated calling function 8 times per frame
    Total time for 8 calls:

    Cython version:
    7.82 μs ± 78.8 ns per loop (mean ± std. dev. of 7 runs, 100,000 loops each)

    Python-sc2 `already_pending` alternative:
    36.2 μs ± 1.38 μs per loop (mean ± std. dev. of 7 runs, 10,000 loops each)

    Called only once per frame:

    Cython version:
    5.18 μs ± 51.2 ns per loop (mean ± std. dev. of 7 runs, 100,000 loops each)

    Python-sc2 `already_pending` alternative:
    22.6 μs ± 363 ns per loop (mean ± std. dev. of 7 runs, 10,000 loops each)
    ```
    Args:
        ai: Bot object that will be running the game.
        unit_type: Unit type we want to check.
    Returns:
        How many structures of unit_type are currently building.
    """
    
    
def cy_structure_pending_ares(ai: "BotAI", unit_type: UnitID, include_planned=True) -> int:
    """Check how many structures of unit_type are pending
    Faster structure specific alternative to `python-sc2`'s `already_pending`

    Attention: Use only when your bot is based on Ares SC2.
    This version includes buildings that are planned by Ares
    
    
    
    Example:
    ```py
    from cython_functions import cy_structure_pending_ares
    from sc2.ids.unit_typeid import UnitTypeId
    num_pylons_pending: int = cy_structure_pending_ares(self, UnitTypeId.PYLON, include_planned=True)
    ```

    
    ```
    Cython version (without Ares planned buildings):
    907 ns ± 3.5 ns per loop (mean ± std. dev. of 7 runs, 1,000,000 loops each)
    Cython version (with Ares planned buildings):
    ~1µs
    Python-sc2 `already_pending` alternative:
    2.06 µs ± 6.49 ns per loop (mean ± std. dev. of 7 runs, 100,000 loops each)
    ```
    Args:
        ai: Bot object that will be running the game.
        unit_type: Unit type we want to check.
        include_planned: Whether to include Ares planned buildings. Default is True.
    Returns:
        How many structures of unit_type are currently building.
    """


def cy_upgrade_pending(ai: "BotAI", upgrade_type: UpgradeId) -> float:
    """Check if a specific upgrade is pending.

    Faster upgrade specific alternative to `python-sc2`'s `already_pending`

    Example:
    ```py
    from cython_functions import cy_upgrade_pending
    from sc2.ids.upgrade_id import UpgradeId

    banshee_cloak_pending: float = cy_upgrade_pending(self, UpgradeId.BANSHEECLOAK)
    ```
    ```
    922 ns ± 5.9 ns per loop (mean ± std. dev. of 7 runs, 1,000,000 loops each)

    Python-sc2 `already_pending` alternative:
    3.41 μs ± 28.3 ns per loop (mean ± std. dev. of 7 runs, 100,000 loops each)
    ```

    Args:
        ai: Bot object that will be running the game.
        upgrade_type: Upgrade type we want to check.

    Returns:
        0 if the upgrade is not started, 
        1 if finished,
        Value between 0 and 1 if pending.
    """