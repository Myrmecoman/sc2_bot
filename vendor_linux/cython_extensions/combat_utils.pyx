from libc.math cimport atan2, cos, exp, fabs, log, pi, sin, sqrt

import numpy as np

cimport numpy as np

from scipy.optimize import differential_evolution

from cython_extensions.geometry import cy_angle_diff, cy_angle_to, cy_distance_to
from cython_extensions.map_analysis import cy_get_bounding_box
from cython_extensions.turn_rate import TURN_RATE
from cython_extensions.unit_data import UNIT_DATA
from cython_extensions.units_utils import cy_center, cy_find_units_center_mass

UNIT_DATA_INT_KEYS = {k.value: v for k, v in UNIT_DATA.items()}
TURN_RATE_INT_KEYS = {k.value: v for k, v in TURN_RATE.items()}

cpdef double cy_get_turn_speed(unit, unsigned int unit_type_int):
    """Returns turn speed of unit in radians"""
    cdef double turn_rate

    turn_rate = TURN_RATE_INT_KEYS.get(unit_type_int, 500.0)
    return turn_rate * 1.4 * pi / 180

cpdef double cy_range_vs_target(unit, target):
    """Get the range of a unit to a target."""
    if unit.can_attack_air and target.is_flying:
        return unit.air_range
    else:
        return unit.ground_range

cpdef bint cy_is_facing(unit, other_unit, double angle_error=0.3):
    cdef:
        (double, double) p1 = unit.position
        (double, double) p2 = other_unit.position
        double angle, angle_difference
        double unit_facing = unit.facing

    angle = atan2(
        p2[1] - p1[1],
        p2[0] - p1[0],
    )
    if angle < 0:
        angle += pi * 2
    angle_difference = fabs(angle - unit_facing)
    return angle_difference < angle_error

cpdef bint cy_attack_ready(bot, unit, target):
    """
    Determine whether the unit can attack the target by the time the unit faces the target.
    Thanks Sasha for writing this out.
    """
    cdef:
        unsigned int unit_type_int = unit._proto.unit_type
        int weapon_cooldown
        double angle, distance, move_time, step_time, turn_time, unit_speed
        (float, float) unit_pos
        (float, float) target_pos

    # fix for units, where this method returns False so the unit moves
    # but the attack animation is still active, so the move command cancels the attack
    # need to think of a better fix later, but this is better than a unit not attacking
    # and still better than using simple weapon.cooldown == 0 micro
    weapon_cooldown = unit.weapon_cooldown
    # if weapon_cooldown > 7: # and unit_type_int == 91:  # 91 == UnitID.HYDRALISK
    #     return True
    # prevents crash, since unit can't move
    if unit_type_int == 503:  # 503 == UnitID.LURKERMPBURROWED
        return True
    if not unit.can_attack:
        return False
    # Time elapsed per game step
    step_time = bot.client.game_step / 22.4

    unit_pos = unit.position
    target_pos = target.position
    # Time it will take for unit to turn to face target
    angle = cy_angle_diff(
        unit.facing, cy_angle_to(unit_pos, target_pos)
    )
    turn_time = angle / cy_get_turn_speed(unit, unit_type_int)

    # Time it will take for unit to move in range of target
    distance = (
        cy_distance_to(unit_pos, target_pos)
        - unit.radius
        - target.radius
        - cy_range_vs_target(unit, target)
    )
    distance = max(0, distance)
    unit_speed = (unit.real_speed + 1e-16) * 1.4
    move_time = distance / unit_speed

    return step_time + turn_time + move_time >= weapon_cooldown / 22.4

cpdef object cy_pick_enemy_target(object enemies):
    """For best enemy target from the provided enemies
    TODO: If there are multiple units that can be killed, pick the highest value one
        Unit parameter to allow for this in the future

    For now this returns the lowest health enemy
    """
    cdef:
        object returned_unit
        unsigned int num_enemies, x
        double lowest_health, total_health

    num_enemies = len(enemies)
    returned_unit = enemies[0]
    lowest_health = 999.9
    for x in range(num_enemies):
        unit = enemies[x]
        total_health = unit.health + unit.shield
        if total_health < lowest_health:
            lowest_health = total_health
            returned_unit = unit

    return returned_unit

cdef (double, double) rotate_by_angle((double, double) vec, double angle):
    cdef double cos_angle = np.cos(angle)
    cdef double sin_angle = np.sin(angle)
    cdef double new_x = vec[0] * cos_angle - vec[1] * sin_angle
    cdef double new_y = vec[0] * sin_angle + vec[1] * cos_angle
    return (new_x, new_y)

cpdef dict cy_adjust_moving_formation(
        object our_units,
        (double, double) target,
        list fodder_tags,
        double unit_multiplier,
        double retreat_angle
):
    cdef:
        dict unit_repositioning = {}
        int num_units, index
        unsigned int len_fodder_tags
        (double, double) our_center, our_adjusted_position, sincos, core_left_rotate, core_right_rotate
        (double, double) unit_pos, new_position, fodder_mean, adjusted_unit_position, unit_sincos
        double angle_to_origin, core_left_x_offset, core_left_y_offset, core_right_x_offset, core_right_y_offset
        double fodder_mean_distance, angle_to_target, fodder_x_offset, fodder_y_offset
        double c_distance = 0.0
        list core_units = []
        list fodder_units = []

    len_fodder_tags = len(fodder_tags)

    # If there are no fodder tags, none of the units will need their positions adjusted
    if len_fodder_tags == 0:
        return unit_repositioning

    # Find the center of the units
    our_center = cy_find_units_center_mass(our_units, 6.0)[0]

    # start getting the angle by applying a translation that moves the enemy to the origin
    our_adjusted_position = (our_center[0] - target[0], our_center[1] - target[1])

    # use atan2 to get the angle
    angle_to_origin = np.arctan2(our_adjusted_position[1], our_adjusted_position[0])

    # We need sine and cosine so that we can give the correct retreat position
    sincos = (np.sin(angle_to_origin), np.cos(angle_to_origin))

    # Rotate offsets by +/- retreat angle degrees so that core units move diagonally backwards
    core_left_rotate = rotate_by_angle((sincos[1], sincos[0]), retreat_angle)
    core_right_rotate = rotate_by_angle((sincos[1], sincos[0]), -retreat_angle)

    core_left_x_offset = core_left_rotate[1] * unit_multiplier
    core_left_y_offset = core_left_rotate[0] * unit_multiplier
    core_right_x_offset = core_right_rotate[1] * unit_multiplier
    core_right_y_offset = core_right_rotate[0] * unit_multiplier

    for unit in our_units:
        if unit.tag in fodder_tags:
            fodder_units.append(unit)
        else:
            core_units.append(unit)

    # Determine which core units need to move based on the mean fodder distance
    fodder_mean = cy_find_units_center_mass(fodder_units, 7.0)[0]
    fodder_mean_distance = (fodder_mean[0] - target[0]) ** 2 + (fodder_mean[1] - target[1]) ** 2

    num_units = len(core_units)
    # Identify if a core unit is closer to the enemy than the fodder mean

    for index in range(num_units):
        unit = core_units[index]
        unit_pos = unit.position
        unit_tag = unit.tag

        c_distance = (unit_pos[0] - target[0]) ** 2 + (unit_pos[1] - target[1]) ** 2

        if c_distance < fodder_mean_distance:
            adjusted_unit_position = (unit_pos[0] - target[0], unit_pos[1] - target[1])
            angle_to_target = atan2(adjusted_unit_position[1], adjusted_unit_position[0])
            unit_sincos = (sin(angle_to_target), cos(angle_to_target))

            if unit_sincos[1] > 0.0:
                # If cosine of angle is greater than 0, the unit is to the right of the line so move right diagonally
                new_position = (unit_pos[0] + core_right_x_offset, unit_pos[1] + core_right_y_offset)
                unit_repositioning[unit_tag] = new_position
            else:
                # Otherwise, go left diagonally
                new_position = (unit_pos[0] + core_left_x_offset, unit_pos[1] + core_left_y_offset)
                unit_repositioning[unit_tag] = new_position

    return unit_repositioning


cdef double optimization_function(
    const double[:] params,
    object targets,
    double effect_radius,
    set bonus_tags
):
    """
    Function for optimization.
    """
    cdef double x = params[0]
    cdef double y = params[1]
    cdef double i, j, y_offset, dist, exponent, denominator, fraction, append_value
    cdef double radius
    cdef double result = 0.0
    cdef double log_effect = log(1 + effect_radius)
    cdef bint is_bonus_tag

    for unit in targets:
        is_bonus_tag = unit.tag in bonus_tags
        if is_bonus_tag:
            result += 2.0
            continue
        radius = unit.radius
        i, j = unit.position

        y_offset = log_effect + log(1 + radius)
        dist = sqrt(((x - i) ** 2 + (y - j) ** 2))
        exponent = 100 * (log(dist + 1) - y_offset)
        denominator = 1 + exp(exponent)
        fraction = 2 / denominator
        append_value = -1.0 * (fraction - 1.0)
        result += append_value
    return result

# Wrapper for the optimization function
cdef double f_wrapper(
    const double[:] params,
    object targets,
    double effect_radius,
    set bonus_tags
):
    return optimization_function(params, targets, effect_radius, bonus_tags)

cpdef cy_find_aoe_position(
    double effect_radius,
    object targets,
    unsigned int min_units = 1,
    bonus_tags = None,
):
    """
    Find the best place to put an AoE effect so that it hits the most units.
    """
    cdef unsigned int len_targets = len(targets)
    if not bonus_tags:
        bonus_tags = set()
    if len_targets == 0:
        return None
    elif len_targets == 1:
        return targets[0].position

    (x_min, x_max), (y_min, y_max) = cy_get_bounding_box({u.position_tuple for u in targets})
    bounds = [(x_min, x_max), (y_min, y_max)]

    result = differential_evolution(
        f_wrapper,
        bounds=bounds,
        args=(targets, effect_radius, bonus_tags),
        tol=1e-10
    )
    if result.success:
        return result.x
    else:
        return None
