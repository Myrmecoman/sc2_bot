from typing import Optional, Union

import numpy as np
from sc2.bot_ai import BotAI
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

def cy_attack_ready(ai: BotAI, unit: Unit, target: Unit) -> bool:
    """Check if the unit is ready to attack the target.

    Takes into account turn rate and unit speeds

    Example:
    ```py
    from cython_extensions import cy_attack_ready

    worker = self.workers[0]
    target = self.enemy_units[0]

    attack_ready: bool = cy_attack_ready(self, worker, target)
    ```

    ```
    1.46 µs ± 5.45 ns per loop (mean ± std. dev. of 7 runs, 1,000,000 loops each)

    Python alternative:
    5.66 µs ± 21.2 ns per loop (mean ± std. dev. of 7 runs, 100,000 loops each)
    ```

    Args:
        ai: Bot object that will be running the game.
        unit: The unit we want to check.
        target: The thing we want to shoot.

    Returns:
        True if the unit is ready to attack the target, False otherwise.
    """
    ...

def cy_is_facing(unit: Unit, other_unit: int, angle_error: float) -> bool:
    """Get turn speed of unit in radians

    Example:
    ```py
    from cython_extensions import cy_is_facing

    unit: Unit = self.workers[0]
    other_unit: Unit = self.townhalls[0]
    is_facing: bool = cy_is_facing(unit, other_unit)
    ```
    ```
    323 ns ± 3.93 ns per loop (mean ± std. dev. of 7 runs, 1,000,000 loops each)

    Python-sc2's `unit.is_facing(other_unit)` alternative:
    2.94 µs ± 8 ns per loop (mean ± std. dev. of 7 runs, 100,000 loops each)
    ```

    Args:
        unit: The actual unit we are checking.
        other_unit: The unit type ID integer value.
        angle_error: Some leeway when deciding if a unit is facing the other unit.
        Defaults to 0.3.

    Returns:
        True if the unit is facing the other unit, False otherwise.

    """
    ...

def cy_pick_enemy_target(enemies: Union[Units, list[Unit]]) -> Unit:
    """Pick the best thing to shoot at out of all enemies.

    Example:
    ```py
    from cython_extensions import cy_pick_enemy_target
    from sc2.units import Units
    from sc2.unit import Unit

    enemies: Units = self.enemy_units

    target: Unit = cy_pick_enemy_target(enemies)
    ```
    ```
    70.5 µs ± 818 ns per loop (mean ± std. dev. of 7 runs, 10,000 loops each)

    Python alternative:
    115 µs ± 766 ns per loop (mean ± std. dev. of 7 runs, 10,000 loops each)
    ```

    Args:
        enemies: All enemy units we would like to check.

    Returns:
        The best unit to target.
    """
    ...

def cy_find_aoe_position(
    effect_radius: float, targets: Union[Units, list[Unit]], bonus_tags: set[int] = None
) -> Optional[np.ndarray]:
    """Find best splash target given a group of enemies.

    Big thanks to idontcodethisgame for the original code in Eris

    WARNING: Please don't spam this function, it's fine to use as required
    but is costly. For example: only use this if unit ability is ready,
    only if enemy are in combat range etc.

    Example:
    ```py
    import numpy as np
    from cython_extensions import cy_find_aoe_position
    from sc2.ids.ability_id import AbilityId
    from sc2.ids.unit_typeid import UnitTypeId
    from sc2.position import Point2
    from sc2.units import Units
    from sc2.unit import Unit

    enemies: Units = self.enemy_units

    for unit in self.units:
        if unit.type_id == UnitTypeId.RAVAGER:
            # in practice, don't do this query for every individual unit
            abilities = await self.get_available_abilities(unit)
            if AbilityId.EFFECT_CORROSIVEBILE in abilities:
                target: Optional[np.ndarray] = cy_find_aoe_position(effect_radius=1.375, targets=enemies)
                # in practise in some scenarios, you should do an extra check to
                # count how many units you would hit, this only finds position, not amount
                if pos is not None:
                    unit(AbilityId.EFFECT_CORROSIVEBILE, Point2(pos))
    ```

    Args:
        effect_radius: The radius of the effect (range).
        targets: All enemy units we would like to check.
        bonus_tags: If provided, give more value to these enemy tags.

    Returns:
        A 1D numpy array containing x and y coordinates of aoe position,
        or None.
    """
    ...

def cy_adjust_moving_formation(
    our_units: Union[Units, list[Unit]],
    target: Union[Point2, tuple[float, float]],
    fodder_tags: list[int],
    unit_multiplier: float,
    retreat_angle: float,
) -> dict[int, tuple[float, float]]:
    """Adjust units formation.

    Big thanks to idontcodethisgame for the original code in Eris

    The idea here is that we give UnitTypeId's a fodder value,
    and this cython function works out which unit we want at
    the front to absorb damage. This works by returning a dictionary
    containing tags of the non fodder units that need to move backwards
    behind the fodder and the position they should move to.

    TIP: Don't use this when combat is already active, will
    probably lead to anti-micro. Use this while moving across the
    map and pre combat.

    Example:
    ```py
    import numpy as np
    from cython_extensions import cy_find_aoe_position, cy_find_units_center_mass
    from sc2.ids.ability_id import AbilityId
    from sc2.ids.unit_typeid import UnitTypeId
    from sc2.position import Point2
    from sc2.units import Units
    from sc2.unit import Unit

    def detect_fodder_value(self, units) -> int:

        # zealot will always be fodder
        # if no zealot this will pick the next best unit type
        # stalker will never be fodder in this example
        unit_fodder_values: dict[UnitTypeId, int] = {
                UnitTypeId.STALKER: 4,
                UnitTypeId.ZEALOT: 1,
                UnitTypeId.ADEPT: 2,
                UnitTypeId.PROBE: 3,
        }

        # establish how many fodder levels there are
        unit_type_fodder_values: set[int] = {
            unit_fodder_values[u.type_id]
            for u in units
            if u.type_id in unit_fodder_values
        }

        # if there's only one fodder level, no units are fodder
        if len(unit_type_fodder_values) > 1:
            return min(unit_type_fodder_values)
        else:
            return 0

    async def on_step(self, iteration: int):
        if not self.enemy_units:
            return
        # find lowest fodder value among our units
        # will return 0 if our army only has one fodder level
        fodder_value: int = self.detect_fodder_value(self.units)

        fodder_tags = []
        units_that_need_to_move = dict()

        # there are fodder levels, calculate unit adjustment
        if fodder_value > 0:
            for unit in self.units:
                if (
                    unit.type_id in self.unit_fodder_values
                    and self.unit_fodder_values[unit.type_id] == fodder_value
                ):
                    fodder_tags.append(unit.tag)

            units_that_need_to_move = cy_adjust_moving_formation(
                self.units,
                cy_find_units_center_mass(self.enemy_units, 5.0)[0],
                fodder_tags,
                1.0,
                0.25,
            )

        for unit in self.units:
            if (
                unit.tag in units_that_need_to_move
                and unit.distance_to(self.enemy_units.center) > 9.0
            ):
                # in practise check this position is valid (pathable, in bounds etc)
                # left out here for example clarity
                unit.move(Point2(units_that_need_to_move[unit.tag]))
            else:
                unit.attack(self.enemy_units.center)
    ```

    324 µs ± 9.44 µs per loop (mean ± std. dev. of 7 runs, 1,000 loops each)

    Args:
        our_units: All our squad units, including core and fodder.
        target: The target we want the fodder to lead us to.
        fodder_tags: A list of fodder unit tags.
        unit_multiplier: How far core units should retreat when
            adjusting during combat.
        retreat_angle: Angle (in radians) for diagonal
            retreat of core units.

    Returns:
        A dictionary where keys are unit tags requiring movement
        and values are tuples of x, y coordinates.

    """
    ...

def cy_range_vs_target(unit: Unit, target: Unit) -> float:
    """Cython version of range_vs_target

    Example:
    ```py
    from cython_extensions import cy_range_vs_target
    from sc2.unit import Unit

    unit: Unit = self.units[0]
    target: Unit = self.enemies[0]

    range: float = cy_range_vs_target(unit, target)
    ```

    Args:
        unit: The unit we want to check.
        target: The target we want to check.

    Returns:
        The weapon range to the target
    """
    ...
