"""Validation functions for safe wrappers."""

from numbers import Number

import numpy as np


def _validate_position(position, param_name: str = "position"):
    """Validate position parameter."""
    if not isinstance(position, (tuple, list)):
        raise TypeError(
            f"{param_name} must be a tuple or list, got {type(position).__name__}"
        )

    if len(position) != 2:
        raise ValueError(
            f"{param_name} must have exactly 2 elements (x, y), got {len(position)}"
        )


def _validate_units(units, param_name: str = "units", allow_empty: bool = False):
    """Validate units parameter."""
    if units is None:
        raise ValueError(f"{param_name} cannot be None")

    if not hasattr(units, "__len__"):
        raise TypeError(f"{param_name} must be a sequence, got {type(units).__name__}")

    if not allow_empty and len(units) == 0:
        raise ValueError(f"{param_name} cannot be empty")


def _validate_unit(unit, param_name: str = "unit"):
    """Validate single unit parameter."""
    if unit is None:
        raise ValueError(f"{param_name} cannot be None")

    if not hasattr(unit, "position"):
        raise ValueError(f"{param_name} must have a position attribute")


def _validate_unit_with_attack(unit):
    """Validate unit with attack capabilities."""
    if unit is None:
        raise ValueError("unit cannot be None")

    if not hasattr(unit, "can_attack"):
        raise ValueError("unit must have can_attack attribute")

    # Only validate other attributes if unit can actually attack
    if unit.can_attack:
        required_attrs = [
            "position",
            "radius",
            "air_range",
            "ground_range",
            "can_attack_air",
            "can_attack_ground",
        ]
        missing_attrs = [attr for attr in required_attrs if not hasattr(unit, attr)]
        if missing_attrs:
            raise ValueError(f"unit is missing required attributes: {missing_attrs}")


def _validate_number(value, param_name: str, allow_negative: bool = True):
    """Validate numeric parameter."""
    if not isinstance(value, Number):
        raise TypeError(f"{param_name} must be a number, got {type(value).__name__}")

    if not allow_negative and value < 0:
        raise ValueError(f"{param_name} must be non-negative, got {value}")


def _validate_bool(value, param_name: str):
    """Validate boolean parameter."""
    if not isinstance(value, bool):
        raise TypeError(f"{param_name} must be a boolean, got {type(value).__name__}")


def _validate_numpy_array(
    array, param_name: str, expected_dtype=None, expected_shape=None
):
    """Validate numpy array parameter."""
    if not isinstance(array, np.ndarray):
        raise TypeError(
            f"{param_name} must be a numpy array, got {type(array).__name__}"
        )

    if expected_dtype and array.dtype != expected_dtype:
        raise ValueError(
            f"{param_name} must have dtype {expected_dtype}, got {array.dtype}"
        )

    if expected_shape and array.shape != expected_shape:
        raise ValueError(
            f"{param_name} must have shape {expected_shape}, got {array.shape}"
        )


def _validate_grid(grid, param_name: str = "grid"):
    """Validate 2D grid parameter."""
    if not isinstance(grid, np.ndarray):
        raise TypeError(
            f"{param_name} must be a numpy array, got {type(grid).__name__}"
        )

    if grid.ndim != 2:
        raise ValueError(f"{param_name} must be a 2D array, got {grid.ndim}D")


def _validate_point_list(points, param_name: str = "points"):
    """Validate list of points parameter."""
    if not isinstance(points, (list, tuple)):
        raise TypeError(
            f"{param_name} must be a list or tuple, got {type(points).__name__}"
        )

    for i, point in enumerate(points):
        try:
            _validate_position(point, f"{param_name}[{i}]")
        except (TypeError, ValueError) as e:
            raise type(e)(f"Invalid point at index {i} in {param_name}: {e}")


# Validation functions for specific Cython functions
def _validate_cy_center(args):
    _validate_units(args["units"], "units")


def _validate_cy_closest_to(args):
    _validate_position(args["position"], "position")
    _validate_units(args["units"], "units")


def _validate_cy_find_units_center_mass(args):
    _validate_units(args["units"], "units")
    _validate_number(args["distance"], "distance", allow_negative=False)


def _validate_cy_in_attack_range(args):
    _validate_unit_with_attack(args["unit"])
    _validate_units(args["units"], "units", allow_empty=True)
    bonus_distance = args.get("bonus_distance", 0.0)
    _validate_number(bonus_distance, "bonus_distance")


def _validate_cy_sorted_by_distance_to(args):
    _validate_units(args["units"], "units", allow_empty=True)
    _validate_position(args["position"], "position")
    reverse = args.get("reverse", False)
    _validate_bool(reverse, "reverse")


def _validate_cy_closer_than(args):
    _validate_units(args["units"], "units", allow_empty=True)
    _validate_position(args["position"], "position")
    _validate_number(args["max_distance"], "max_distance", allow_negative=False)


def _validate_cy_further_than(args):
    _validate_units(args["units"], "units", allow_empty=True)
    _validate_position(args["position"], "position")
    _validate_number(args["min_distance"], "min_distance", allow_negative=False)


# Geometry validations
def _validate_cy_distance_to(args):
    _validate_position(args["p1"], "p1")
    _validate_position(args["p2"], "p2")


def _validate_cy_distance_to_squared(args):
    _validate_position(args["p1"], "p1")
    _validate_position(args["p2"], "p2")


def _validate_cy_towards(args):
    _validate_position(args["start_pos"], "start_pos")
    _validate_position(args["target_pos"], "target_pos")
    _validate_number(args["distance"], "distance")


def _validate_cy_angle_to(args):
    _validate_position(args["from_pos"], "from_pos")
    _validate_position(args["to_pos"], "to_pos")


def _validate_cy_angle_diff(args):
    _validate_number(args["a"], "a")
    _validate_number(args["b"], "b")


def _validate_cy_find_average_angle(args):
    _validate_position(args["start_point"], "start_point")
    _validate_position(args["reference_point"], "reference_point")
    points = args["points"]
    _validate_point_list(points, "points")


def _validate_cy_get_angle_between_points(args):
    _validate_position(args["point_a"], "point_a")
    _validate_position(args["point_b"], "point_b")


def _validate_cy_translate_point_along_line(args):
    _validate_position(args["point"], "point")
    _validate_number(args["a_value"], "a_value")
    _validate_number(args["distance"], "distance")


# Combat utils validations
def _validate_cy_attack_ready(args):
    _validate_unit(args["unit"], "unit")
    if not hasattr(args["unit"], "weapon_cooldown"):
        raise ValueError("unit must have weapon_cooldown attribute")


def _validate_cy_is_facing(args):
    _validate_unit(args["unit"], "unit")
    _validate_unit(args["other_unit"], "other_unit")
    angle_error = args.get("angle_error", 0.3)
    _validate_number(angle_error, "angle_error", allow_negative=False)


def _validate_cy_range_vs_target(args):
    _validate_unit(args["unit"], "unit")
    target = args["target"]
    if not hasattr(target, "position"):
        raise ValueError("target must have position attribute")
    if not hasattr(target, "radius"):
        raise ValueError("target must have radius attribute")


def _validate_cy_pick_enemy_target(args):
    _validate_units(args["enemies"], "enemies", allow_empty=True)


def _validate_cy_find_aoe_position(args):
    _validate_number(args["effect_radius"], "effect_radius", allow_negative=False)
    _validate_units(args["targets"], "targets")
    # Optional args: min_units (unsigned int), bonus_tags (set-like) are not strictly validated here.


def _validate_cy_get_turn_speed(args):
    unit_type_int = args["unit_type_int"]
    # Validate it's an integer
    if not isinstance(unit_type_int, int):
        raise TypeError("unit_type_int must be an integer")


# General utils validations
def _validate_cy_has_creep(args):
    _validate_position(args["position"], "position")
    creep_numpy_grid = args["creep_numpy_grid"]
    _validate_grid(creep_numpy_grid, "creep_numpy_grid")


def _validate_cy_in_pathing_grid_burny(args):
    _validate_position(args["position"], "position")
    pathing_numpy_grid = args["pathing_numpy_grid"]
    _validate_grid(pathing_numpy_grid, "pathing_numpy_grid")


def _validate_cy_in_pathing_grid_ma(args):
    _validate_position(args["position"], "position")
    pathing_numpy_grid = args["pathing_numpy_grid"]
    _validate_grid(pathing_numpy_grid, "pathing_numpy_grid")


def _validate_cy_unit_pending(args):
    # cy_unit_pending(bot, unit_type)
    bot = args["bot"]  # presence check only
    unit_type = args["unit_type"]
    # Validate unit_type can be either int-like enum with .name/.value or similar; keep minimal:
    if not isinstance(unit_type, int) and not hasattr(unit_type, "name"):
        # keeping this permissive to avoid breaking behavior
        pass  # do not raise here to avoid changing logic
    
def _validate_cy_structure_pending(args):
    # cy_structure_pending(bot, unit_type)
    bot = args["bot"]  # presence check only
    unit_type = args["unit_type"]
    # Validate unit_type can be either int-like enum with .name/.value or similar; keep minimal:
    if not isinstance(unit_type, int) and not hasattr(unit_type, "name"):
        # keeping this permissive to avoid breaking behavior
        pass  # do not raise here to avoid changing logic
    
    
def _validate_cy_structure_pending_ares(args):
    # cy_structure_pending_ares(bot, unit_type, include_planned)
    bot = args["bot"]  # presence check only
    unit_type = args["unit_type"]
    include_planned = args.get("include_planned", True)
    _validate_bool(include_planned, "include_planned")
    # Validate unit_type can be either int-like enum with .name/.value or similar; keep minimal:
    if not isinstance(unit_type, int) and not hasattr(unit_type, "name"):
        # keeping this permissive to avoid breaking behavior
        pass  # do not raise here to avoid changing logic
    
def _validate_cy_upgrade_pending(args):
    # cy_upgrade_pending(bot, upgrade_type)
    bot = args["bot"]  # presence check only
    upgrade_type = args["upgrade_type"]
    # Validate upgrade_type can be either int-like enum with .name/.value or similar; keep minimal:
    if not isinstance(upgrade_type, int) and not hasattr(upgrade_type, "name"):
        # keeping this permissive to avoid breaking behavior
        pass  # do not raise here to avoid changing logic


def _validate_cy_pylon_matrix_covers(args):
    _validate_position(args["position"], "position")
    pylons = args["pylons"]
    _validate_units(pylons, "pylons", allow_empty=True)
    height_grid = args["height_grid"]
    _validate_grid(height_grid, "height_grid")
    pylon_build_progress = args.get("pylon_build_progress", 1.0)
    _validate_number(pylon_build_progress, "pylon_build_progress", allow_negative=False)


# Map analysis validations
def _validate_cy_flood_fill_grid(args):
    _validate_position(args["start_point"], "start_point")
    terrain_grid = args["terrain_grid"]
    _validate_grid(terrain_grid, "terrain_grid")
    pathing_grid = args["pathing_grid"]
    _validate_grid(pathing_grid, "pathing_grid")
    _validate_number(args["max_distance"], "max_distance", allow_negative=False)
    # cutoff_points is expected to be a set; keep minimal validation to avoid breaking behavior
    _ = args["cutoff_points"]


def _validate_cy_get_bounding_box(args):
    coordinates = args["coordinates"]
    if not isinstance(coordinates, set):
        raise TypeError(f"coordinates must be a set, got {type(coordinates).__name__}")


# Numpy helper validations
def _validate_cy_all_points_below_max_value(args):
    grid = args["grid"]
    _validate_grid(grid, "grid")
    max_value = args["max_value"]
    _validate_number(max_value, "max_value")
    points_to_check = args["points_to_check"]
    _validate_point_list(points_to_check, "points_to_check")


def _validate_cy_all_points_have_value(args):
    grid = args["grid"]
    _validate_grid(grid, "grid")
    value = args["value"]
    _validate_number(value, "value")
    points = args["points"]
    _validate_point_list(points, "points")


def _validate_cy_point_below_value(args):
    _validate_position(args["position"], "position")
    grid = args["grid"]
    _validate_grid(grid, "grid")
    _validate_number(args["weight_safety_limit"], "weight_safety_limit")


def _validate_cy_points_with_value(args):
    grid = args["grid"]
    _validate_grid(grid, "grid")
    _validate_number(args["value"], "value")
    points = args["points"]
    _validate_point_list(points, "points")


def _validate_cy_last_index_with_value(args):
    grid = args["grid"]
    _validate_numpy_array(grid, "grid")
    _validate_number(args["value"], "value")
    points = args["points"]
    _validate_point_list(points, "points")


# Placement solver validations
def _validate_cy_can_place_structure(args):
    _validate_position(args["building_origin"], "building_origin")
    building_size = args["building_size"]
    if not isinstance(building_size, (tuple)):
        raise TypeError(
            f"building_size must be a tuple, got {type(building_size).__name__}"
        )

    if isinstance(building_size, tuple):
        if len(building_size) != 2:
            raise ValueError(
                f"building_size tuple must have 2 elements, got {len(building_size)}"
            )
        if not all(isinstance(s, int) for s in building_size):
            raise TypeError("building_size tuple elements must be integers")

    creep_grid = args["creep_grid"]
    _validate_grid(creep_grid, "creep_grid")

    placement_grid = args["placement_grid"]
    _validate_grid(placement_grid, "placement_grid")

    pathing_grid = args["pathing_grid"]
    _validate_grid(pathing_grid, "pathing_grid")
    # Optional args: avoid_creep, include_addon are booleans; left unvalidated to avoid behavior changes.


def _validate_cy_find_building_locations(args):

    kernel = args["kernel"]
    _validate_grid(kernel, "kernel")

    _validate_number(args["x_stride"], "x_stride", allow_negative=False)
    _validate_number(args["y_stride"], "y_stride", allow_negative=False)

    # bounds are tuples (min, max)
    x_bounds = args["x_bounds"]
    y_bounds = args["y_bounds"]
    if not (isinstance(x_bounds, tuple) and len(x_bounds) == 2):
        raise TypeError("x_bounds must be a tuple of length 2")
    if not (isinstance(y_bounds, tuple) and len(y_bounds) == 2):
        raise TypeError("y_bounds must be a tuple of length 2")

    creep_grid = args["creep_grid"]
    _validate_grid(creep_grid, "creep_grid")

    placement_grid = args["placement_grid"]
    _validate_grid(placement_grid, "placement_grid")

    pathing_grid = args["pathing_grid"]
    _validate_grid(pathing_grid, "pathing_grid")

    points_to_avoid_grid = args["points_to_avoid_grid"]
    _validate_grid(points_to_avoid_grid, "points_to_avoid_grid")

    _validate_number(args["building_width"], "building_width", allow_negative=False)
    _validate_number(args["building_height"], "building_height", allow_negative=False)
    # Optional arg: avoid_creep boolean; left unvalidated.


# Dijkstra validations
def _validate_cy_dijkstra(args):
    cost = args["cost"]
    targets = args["targets"]
    priorities = args.get("priorities")

    _validate_grid(cost, "cost")
    _validate_grid(targets, "targets")
    if priorities is not None:
        _validate_numpy_array(priorities, "priorities", cost.dtype, targets.shape[:1])
    # Optional: checks_enabled flag present in signature; validation not required for name alignment.
