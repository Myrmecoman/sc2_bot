"""
Complete safe wrapper functions for all Cython extensions.
Provides type validation when safe mode is enabled.
"""

import inspect
from functools import wraps
from typing import Callable, Optional

from cython_extensions.type_checking.config import is_safe_mode_enabled
from cython_extensions.type_checking.validators import (
    _validate_cy_all_points_below_max_value,
    _validate_cy_all_points_have_value,
    _validate_cy_angle_diff,
    _validate_cy_angle_to,
    _validate_cy_attack_ready,
    _validate_cy_can_place_structure,
    _validate_cy_center,
    _validate_cy_closer_than,
    _validate_cy_closest_to,
    _validate_cy_dijkstra,
    _validate_cy_distance_to,
    _validate_cy_distance_to_squared,
    _validate_cy_find_aoe_position,
    _validate_cy_find_average_angle,
    _validate_cy_find_building_locations,
    _validate_cy_find_units_center_mass,
    _validate_cy_flood_fill_grid,
    _validate_cy_further_than,
    _validate_cy_get_angle_between_points,
    _validate_cy_get_bounding_box,
    _validate_cy_get_turn_speed,
    _validate_cy_has_creep,
    _validate_cy_in_attack_range,
    _validate_cy_in_pathing_grid_burny,
    _validate_cy_in_pathing_grid_ma,
    _validate_cy_is_facing,
    _validate_cy_last_index_with_value,
    _validate_cy_pick_enemy_target,
    _validate_cy_point_below_value,
    _validate_cy_points_with_value,
    _validate_cy_pylon_matrix_covers,
    _validate_cy_range_vs_target,
    _validate_cy_sorted_by_distance_to,
    _validate_cy_towards,
    _validate_cy_translate_point_along_line,
    _validate_cy_unit_pending,
    _validate_cy_structure_pending,
    _validate_cy_structure_pending_ares,
    _validate_cy_upgrade_pending
)


def safe_wrapper(validation_func: Optional[Callable] = None):
    """
    Decorator to create safe wrappers that conditionally apply validation.

    Args:
        validation_func: Function to validate arguments before calling the original
    """

    def decorator(original_func):
        @wraps(original_func)
        def wrapper(*args, **kwargs):
            if is_safe_mode_enabled() and validation_func:
                try:
                    # Get parameter names for better error messages
                    sig = inspect.signature(original_func)
                    bound_args = sig.bind(*args, **kwargs)
                    bound_args.apply_defaults()
                    validation_func(bound_args.arguments)
                except (TypeError, ValueError, KeyError) as e:
                    # Enhance error message with function name if not already present
                    # KeyError indicates validator expects different parameter names than wrapper signature
                    func_name = original_func.__name__
                    error_msg = str(e)

                    # Check if function name is already in the error message
                    if not error_msg.startswith(func_name):
                        enhanced_msg = f"{func_name}: {error_msg}"
                        raise type(e)(enhanced_msg) from e
                    else:
                        raise
            return original_func(*args, **kwargs)

        return wrapper

    return decorator


# Combat utils
from cython_extensions.combat_utils import (
    cy_adjust_moving_formation as _cy_adjust_moving_formation,
)
from cython_extensions.combat_utils import cy_attack_ready as _cy_attack_ready
from cython_extensions.combat_utils import cy_find_aoe_position as _cy_find_aoe_position
from cython_extensions.combat_utils import cy_get_turn_speed as _cy_get_turn_speed
from cython_extensions.combat_utils import cy_is_facing as _cy_is_facing
from cython_extensions.combat_utils import cy_pick_enemy_target as _cy_pick_enemy_target
from cython_extensions.combat_utils import cy_range_vs_target as _cy_range_vs_target

# Dijkstra
from cython_extensions.dijkstra import cy_dijkstra as _cy_dijkstra

# General utils
from cython_extensions.general_utils import cy_has_creep as _cy_has_creep
from cython_extensions.general_utils import (
    cy_in_pathing_grid_burny as _cy_in_pathing_grid_burny,
)
from cython_extensions.general_utils import (
    cy_in_pathing_grid_ma as _cy_in_pathing_grid_ma,
)
from cython_extensions.general_utils import (
    cy_pylon_matrix_covers as _cy_pylon_matrix_covers,
)
from cython_extensions.general_utils import cy_unit_pending as _cy_unit_pending
from cython_extensions.general_utils import cy_structure_pending as _cy_structure_pending
from cython_extensions.general_utils import cy_structure_pending_ares as _cy_structure_pending_ares
from cython_extensions.general_utils import cy_upgrade_pending as _cy_upgrade_pending

# Geometry
from cython_extensions.geometry import cy_angle_diff as _cy_angle_diff
from cython_extensions.geometry import cy_angle_to as _cy_angle_to
from cython_extensions.geometry import cy_distance_to as _cy_distance_to
from cython_extensions.geometry import cy_distance_to_squared as _cy_distance_to_squared
from cython_extensions.geometry import cy_find_average_angle as _cy_find_average_angle
from cython_extensions.geometry import cy_find_correct_line as _cy_find_correct_line
from cython_extensions.geometry import (
    cy_get_angle_between_points as _cy_get_angle_between_points,
)
from cython_extensions.geometry import cy_towards as _cy_towards
from cython_extensions.geometry import (
    cy_translate_point_along_line as _cy_translate_point_along_line,
)

# Map analysis
from cython_extensions.map_analysis import cy_flood_fill_grid as _cy_flood_fill_grid
from cython_extensions.map_analysis import cy_get_bounding_box as _cy_get_bounding_box

# Numpy helper
from cython_extensions.numpy_helper import (
    cy_all_points_below_max_value as _cy_all_points_below_max_value,
)
from cython_extensions.numpy_helper import (
    cy_all_points_have_value as _cy_all_points_have_value,
)
from cython_extensions.numpy_helper import (
    cy_last_index_with_value as _cy_last_index_with_value,
)
from cython_extensions.numpy_helper import cy_point_below_value as _cy_point_below_value
from cython_extensions.numpy_helper import cy_points_with_value as _cy_points_with_value

# Placement solver
from cython_extensions.placement_solver import (
    cy_can_place_structure as _cy_can_place_structure,
)
from cython_extensions.placement_solver import (
    cy_find_building_locations as _cy_find_building_locations,
)

# Import all original Cython functions
# Units utils
from cython_extensions.units_utils import cy_center as _cy_center
from cython_extensions.units_utils import cy_closer_than as _cy_closer_than
from cython_extensions.units_utils import cy_closest_to as _cy_closest_to
from cython_extensions.units_utils import (
    cy_find_units_center_mass as _cy_find_units_center_mass,
)
from cython_extensions.units_utils import cy_further_than as _cy_further_than
from cython_extensions.units_utils import cy_in_attack_range as _cy_in_attack_range
from cython_extensions.units_utils import (
    cy_sorted_by_distance_to as _cy_sorted_by_distance_to,
)

# ============================================================================
# UNITS UTILS WRAPPERS
# ============================================================================


@safe_wrapper(_validate_cy_center)
def cy_center(units):
    """Type-safe wrapper for cy_center."""
    return _cy_center(units)


@safe_wrapper(_validate_cy_closest_to)
def cy_closest_to(position, units):
    """Type-safe wrapper for cy_closest_to."""
    return _cy_closest_to(position, units)


@safe_wrapper(_validate_cy_find_units_center_mass)
def cy_find_units_center_mass(units, distance: float):
    """Type-safe wrapper for cy_find_units_center_mass."""
    return _cy_find_units_center_mass(units, float(distance))


@safe_wrapper(_validate_cy_in_attack_range)
def cy_in_attack_range(unit, units, bonus_distance: float = 0.0):
    """Type-safe wrapper for cy_in_attack_range."""
    return _cy_in_attack_range(unit, units, float(bonus_distance))


@safe_wrapper(_validate_cy_sorted_by_distance_to)
def cy_sorted_by_distance_to(units, position, reverse: bool = False):
    """Type-safe wrapper for cy_sorted_by_distance_to."""
    return _cy_sorted_by_distance_to(units, position, reverse)


@safe_wrapper(_validate_cy_closer_than)
def cy_closer_than(units, max_distance: float, position):
    """Type-safe wrapper for cy_closer_than."""
    return _cy_closer_than(units, float(max_distance), position)


@safe_wrapper(_validate_cy_further_than)
def cy_further_than(units, min_distance: float, position):
    """Type-safe wrapper for cy_further_than."""
    return _cy_further_than(units, float(min_distance), position)


# ============================================================================
# GEOMETRY WRAPPERS
# ============================================================================


@safe_wrapper(_validate_cy_distance_to)
def cy_distance_to(p1, p2):
    """Type-safe wrapper for cy_distance_to."""
    return _cy_distance_to(p1, p2)


@safe_wrapper(_validate_cy_distance_to_squared)
def cy_distance_to_squared(p1, p2):
    """Type-safe wrapper for cy_distance_to_squared."""
    return _cy_distance_to_squared(p1, p2)


@safe_wrapper(_validate_cy_towards)
def cy_towards(start_pos, target_pos, distance: float):
    """Type-safe wrapper for cy_towards."""
    return _cy_towards(start_pos, target_pos, float(distance))


@safe_wrapper(_validate_cy_angle_to)
def cy_angle_to(from_pos, to_pos):
    """Type-safe wrapper for cy_angle_to."""
    return _cy_angle_to(from_pos, to_pos)


@safe_wrapper(_validate_cy_angle_diff)
def cy_angle_diff(a: float, b: float):
    """Type-safe wrapper for cy_angle_diff."""
    return _cy_angle_diff(float(a), float(b))


@safe_wrapper(_validate_cy_find_average_angle)
def cy_find_average_angle(start_point, reference_point, points):
    """Type-safe wrapper for cy_find_average_angle."""
    return _cy_find_average_angle(start_point, reference_point, points)


@safe_wrapper(_validate_cy_get_angle_between_points)
def cy_get_angle_between_points(point_a, point_b):
    """Type-safe wrapper for cy_get_angle_between_points."""
    return _cy_get_angle_between_points(point_a, point_b)


@safe_wrapper(_validate_cy_translate_point_along_line)
def cy_translate_point_along_line(point, a_value, distance: float):
    """Type-safe wrapper for cy_translate_point_along_line."""
    return _cy_translate_point_along_line(point, a_value, float(distance))


# Pass-through functions that don't need validation yet
cy_find_correct_line = _cy_find_correct_line


# ============================================================================
# COMBAT UTILS WRAPPERS
# ============================================================================


@safe_wrapper(_validate_cy_attack_ready)
def cy_attack_ready(bot, unit, target):
    """Type-safe wrapper for cy_attack_ready."""
    return _cy_attack_ready(bot, unit, target)


@safe_wrapper(_validate_cy_is_facing)
def cy_is_facing(unit, other_unit, angle_error: float = 0.3):
    """Type-safe wrapper for cy_is_facing."""
    return _cy_is_facing(unit, other_unit, angle_error)


@safe_wrapper(_validate_cy_range_vs_target)
def cy_range_vs_target(unit, target):
    """Type-safe wrapper for cy_range_vs_target."""
    return _cy_range_vs_target(unit, target)


@safe_wrapper(_validate_cy_pick_enemy_target)
def cy_pick_enemy_target(enemies):
    """Type-safe wrapper for cy_pick_enemy_target."""
    return _cy_pick_enemy_target(enemies)


@safe_wrapper(_validate_cy_find_aoe_position)
def cy_find_aoe_position(effect_radius, targets, min_units: int = 1, bonus_tags=None):
    """Type-safe wrapper for cy_find_aoe_position."""
    return _cy_find_aoe_position(effect_radius, targets, min_units, bonus_tags)


@safe_wrapper(_validate_cy_get_turn_speed)
def cy_get_turn_speed(unit, unit_type_int):
    """Type-safe wrapper for cy_get_turn_speed."""
    return _cy_get_turn_speed(unit, unit_type_int)


# Pass-through functions that don't need validation yet
cy_adjust_moving_formation = _cy_adjust_moving_formation


# ============================================================================
# GENERAL UTILS WRAPPERS
# ============================================================================


@safe_wrapper(_validate_cy_has_creep)
def cy_has_creep(creep_numpy_grid, position):
    """Type-safe wrapper for cy_has_creep."""
    return _cy_has_creep(creep_numpy_grid, position)


@safe_wrapper(_validate_cy_in_pathing_grid_burny)
def cy_in_pathing_grid_burny(pathing_numpy_grid, position):
    """Type-safe wrapper for cy_in_pathing_grid_burny."""
    return _cy_in_pathing_grid_burny(pathing_numpy_grid, position)


@safe_wrapper(_validate_cy_in_pathing_grid_ma)
def cy_in_pathing_grid_ma(pathing_numpy_grid, position):
    """Type-safe wrapper for cy_in_pathing_grid_ma."""
    return _cy_in_pathing_grid_ma(pathing_numpy_grid, position)


@safe_wrapper(_validate_cy_unit_pending)
def cy_unit_pending(bot, unit_type):
    """Type-safe wrapper for cy_unit_pending."""
    return _cy_unit_pending(bot, unit_type)

@safe_wrapper(_validate_cy_structure_pending)
def cy_structure_pending(bot, unit_type):
    """Type-safe wrapper for cy_structure_pending."""
    return _cy_structure_pending(bot, unit_type)

@safe_wrapper(_validate_cy_structure_pending_ares)
def cy_structure_pending_ares(bot, unit_type, include_planned: bool = True):
    """Type-safe wrapper for cy_structure_pending_ares."""
    return _cy_structure_pending_ares(bot, unit_type, include_planned=include_planned)

@safe_wrapper(_validate_cy_upgrade_pending)
def cy_upgrade_pending(bot, upgrade_type): 
    """Type-safe wrapper for cy_upgrade_pending."""
    return _cy_upgrade_pending(bot, upgrade_type)


@safe_wrapper(_validate_cy_pylon_matrix_covers)
def cy_pylon_matrix_covers(position, pylons, height_grid, pylon_build_progress=1.0):
    """Type-safe wrapper for cy_pylon_matrix_covers."""
    return _cy_pylon_matrix_covers(position, pylons, height_grid, pylon_build_progress)


# ============================================================================
# MAP ANALYSIS WRAPPERS
# ============================================================================


@safe_wrapper(_validate_cy_flood_fill_grid)
def cy_flood_fill_grid(
    start_point, terrain_grid, pathing_grid, max_distance, cutoff_points
):
    """Type-safe wrapper for cy_flood_fill_grid."""
    return _cy_flood_fill_grid(
        start_point, terrain_grid, pathing_grid, max_distance, cutoff_points
    )


@safe_wrapper(_validate_cy_get_bounding_box)
def cy_get_bounding_box(coordinates):
    """Type-safe wrapper for cy_get_bounding_box."""
    return _cy_get_bounding_box(coordinates)


# ============================================================================
# NUMPY HELPER WRAPPERS
# ============================================================================


@safe_wrapper(_validate_cy_all_points_below_max_value)
def cy_all_points_below_max_value(grid, max_value, points_to_check):
    """Type-safe wrapper for cy_all_points_below_max_value."""
    return _cy_all_points_below_max_value(grid, max_value, points_to_check)


@safe_wrapper(_validate_cy_all_points_have_value)
def cy_all_points_have_value(grid, value, points):
    """Type-safe wrapper for cy_all_points_have_value."""
    return _cy_all_points_have_value(grid, value, points)


@safe_wrapper(_validate_cy_point_below_value)
def cy_point_below_value(grid, position, weight_safety_limit=1.0):
    """Type-safe wrapper for cy_point_below_value."""
    return _cy_point_below_value(grid, position, weight_safety_limit)


@safe_wrapper(_validate_cy_points_with_value)
def cy_points_with_value(grid, value, points):
    """Type-safe wrapper for cy_points_with_value."""
    return _cy_points_with_value(grid, value, points)


@safe_wrapper(_validate_cy_last_index_with_value)
def cy_last_index_with_value(grid, value, points):
    """Type-safe wrapper for cy_last_index_with_value."""
    return _cy_last_index_with_value(grid, value, points)


# ============================================================================
# PLACEMENT SOLVER WRAPPERS
# ============================================================================


@safe_wrapper(_validate_cy_can_place_structure)
def cy_can_place_structure(
    building_origin,
    building_size,
    creep_grid,
    placement_grid,
    pathing_grid,
    avoid_creep=True,
    include_addon=False,
    skip_creep_check=False,
):
    """Type-safe wrapper for cy_can_place_structure."""
    return _cy_can_place_structure(
        building_origin,
        building_size,
        creep_grid,
        placement_grid,
        pathing_grid,
        avoid_creep,
        include_addon,
        skip_creep_check,
    )


@safe_wrapper(_validate_cy_find_building_locations)
def cy_find_building_locations(
    kernel,
    x_stride,
    y_stride,
    x_bounds,
    y_bounds,
    creep_grid,
    placement_grid,
    pathing_grid,
    points_to_avoid_grid,
    building_width,
    building_height,
    avoid_creep=True,
):
    """Type-safe wrapper for cy_find_building_locations."""
    return _cy_find_building_locations(
        kernel,
        x_stride,
        y_stride,
        x_bounds,
        y_bounds,
        creep_grid,
        placement_grid,
        pathing_grid,
        points_to_avoid_grid,
        building_width,
        building_height,
        avoid_creep,
    )


# ============================================================================
# DIJKSTRA WRAPPERS
# ============================================================================


@safe_wrapper(_validate_cy_dijkstra)
def cy_dijkstra(cost, targets, priorities=None, checks_enabled=True):
    """Type-safe wrapper for cy_dijkstra."""
    return _cy_dijkstra(cost, targets, priorities, checks_enabled)


# ============================================================================
# EXPORT ALL FUNCTIONS
# ============================================================================

__all__ = [
    # Units utils
    "cy_center",
    "cy_closest_to",
    "cy_find_units_center_mass",
    "cy_in_attack_range",
    "cy_sorted_by_distance_to",
    "cy_closer_than",
    "cy_further_than",
    # Geometry
    "cy_distance_to",
    "cy_distance_to_squared",
    "cy_towards",
    "cy_angle_to",
    "cy_angle_diff",
    "cy_find_average_angle",
    "cy_find_correct_line",
    "cy_get_angle_between_points",
    "cy_translate_point_along_line",
    # Combat utils
    "cy_adjust_moving_formation",
    "cy_attack_ready",
    "cy_find_aoe_position",
    "cy_get_turn_speed",
    "cy_is_facing",
    "cy_pick_enemy_target",
    "cy_range_vs_target",
    # General utils
    "cy_has_creep",
    "cy_in_pathing_grid_burny",
    "cy_in_pathing_grid_ma",
    "cy_pylon_matrix_covers",
    "cy_unit_pending",
    "cy_structure_pending",
    "cy_structure_pending_ares",
    "cy_upgrade_pending",
    # Map analysis
    "cy_flood_fill_grid",
    "cy_get_bounding_box",
    # Numpy helper
    "cy_all_points_below_max_value",
    "cy_all_points_have_value",
    "cy_last_index_with_value",
    "cy_point_below_value",
    "cy_points_with_value",
    # Placement solver
    "cy_can_place_structure",
    "cy_find_building_locations",
    # Dijkstra
    "cy_dijkstra",
]
