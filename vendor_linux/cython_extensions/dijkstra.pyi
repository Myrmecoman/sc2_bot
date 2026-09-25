import numpy as np

class DijkstraPathing:
    """Result of Dijkstras algorithm containing distance and forward pointer grids."""

    def get_distance(
        self, source: tuple[float, float], upper_bound: bool = False
    ) -> float:
        """Get the pathing distance from a given source to the nearest target.

        Args:
            source: Start point.
            upper_bound: If `True`, return the current distance estimate without
                advancing the heap. Defaults to `False`.

        Returns:
            The lowest cost from source to any of the targets.

        """
        ...

    def get_path(
        self, source: tuple[float, float], limit: int = 0, max_distance: int = 1
    ) -> list[tuple[int, int]]:
        """Follow the path from a given source using the forward pointer grids.

        Args:
            source: Start point.
            limit: Maximum length of the returned path. Defaults to 0 indicating no limit.
            max_distance: Size of the search region for a valid starting point. Defaults to 1.

        Returns:
            The lowest cost path from source to any of the targets.

        """
        ...

    def get_distance_grid(self, upper_bound: bool = False) -> np.ndarray:
        """Get the full pathing distance grid.

        Args:
            upper_bound: If `True`, return the current distance estimates without
                advancing the heap. Defaults to `False`.

        Returns:
            Readonly pathing distance grid with the same shape as the cost grid.

        """
        ...

def cy_dijkstra(
    cost_grid: np.ndarray,
    targets: np.ndarray,
    priorities: np.ndarray | None = None,
    checks_enabled: bool = True,
) -> DijkstraPathing:
    """Run Dijkstras algorithm on a grid, yielding many-target-shortest paths for each position.

    Example:
    ```py
    from cython_extensions import cy_dijkstra

    cost = np.where(bot.game_info.pathing_grid.data_numpy.T == 1, 1.0, np.inf)
    targets = np.array([u.position.rounded for u in bot.enemy_units])
    priorities = np.array([-u.distance_to(bot.start_location) for u in bot.enemy_units])     # optional
    pathing = cy_dijkstra(cost, targets, priorities=priorities)

    for unit in bot.units:
        path = pathing.get_path(unit.position.rounded, limit=7)  # path limit is optional
        unit.move(Point2(path[-1]))
    ```

    Args:
        cost_grid: Cost grid. Entries must be positive. Set unpathable cells to infinity.
        targets: Target array of shape (*, 2) containing x and y coordinates of the target points.
        priorities: Optional vector with one priority value per target. Higher values make
            targets more attractive.
        checks_enabled: Pass False to deactivate grid value and target coordinates checks. Defaults to True.

    Returns:
        Pathfinding object containing distances and pointer grids.

    """
    ...
