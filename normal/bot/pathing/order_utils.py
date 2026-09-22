from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units


# avoid re-issuing an order a unit is already executing: repeating an Attack order
# resets the unit's attack windup in the game engine, which is a real DPS loss, not just a wasted action
def is_already_attacking(unit: Unit, target: Unit) -> bool:
    return unit.is_attacking and unit.order_target == target.tag


def is_already_attack_moving_to(unit: Unit, position: Point2, epsilon: float = 0.5) -> bool:
    return unit.is_attacking and isinstance(unit.order_target, Point2) and unit.order_target.distance_to(position) <= epsilon


def is_already_moving_to(unit: Unit, position: Point2, epsilon: float = 0.5) -> bool:
    return unit.is_moving and isinstance(unit.order_target, Point2) and unit.order_target.distance_to(position) <= epsilon


# target can be either a Unit or a Point2 (as accepted by unit.attack() itself)
def is_already_attacking_target(unit: Unit, target) -> bool:
    if isinstance(target, Point2):
        return is_already_attack_moving_to(unit, target)
    return is_already_attacking(unit, target)


def spread_out_point(unit: Unit, friendlies: Units, towards: Point2, radius: float = 1.25, nudge: float = 1.5) -> Point2:
    """Nudge a movement/attack point away from tightly clumped nearby friendlies while still
    heading roughly towards the objective - reduces vulnerability to AOE (splash, storm, banelings,
    a friendly siege tank's own blast). Only meant for use away from active point-blank combat, so
    it never interferes with actual targeting/firing."""
    nearby: Units = friendlies.tags_not_in({unit.tag}).closer_than(radius, unit)
    if nearby.amount == 0 or unit.position.distance_to(towards) < radius:
        return towards
    centroid: Point2 = Point2((
        sum(f.position.x for f in nearby) / nearby.amount,
        sum(f.position.y for f in nearby) / nearby.amount,
    ))
    if unit.position.distance_to(centroid) < 0.1:
        return towards
    away_point: Point2 = unit.position.towards(centroid, -nudge)
    return away_point.towards(towards, 3)
