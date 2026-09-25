"""Everything without a dedicated controller (Hellions/Hellbats, Thors, Battlecruisers, Widow Mines, Ghosts, landed
Vikings ...): attack the nearest thing, and hit-and-run only when we actually outrange it - otherwise backing off
just throws away damage uptime, since the enemy can hit us back anyway."""
from cython_extensions import cy_closest_to

from ares.behaviors.combat.individual import StutterUnitBack
from sc2.unit import Unit
from sc2.units import Units

from bot.army.context import ArmyContext
from bot.army.orders import GroupOrders
from bot.army.units.common import attack_move, attack_unit, follow_point, path_move, run



class GenericController:
    def __init__(self, ai):
        self.ai = ai

    def control(self, units: Units, orders: GroupOrders, ctx: ArmyContext) -> None:
        ctx.prefetch_near(units)
        for unit in units:
            targets = ctx.targets_near(unit)
            if not targets:
                point = follow_point(orders, walkable=None if unit.is_flying else self.ai.in_pathing_grid)
                if orders.aggressive:
                    attack_move(unit, point)
                elif unit.distance_to(point) > orders.hold_radius:
                    path_move(self.ai, ctx, unit, point)
                continue
            nearest: Unit = cy_closest_to(unit.position, targets)
            # the range that matters is the one the enemy would hit US with, and the one we hit IT with
            enemy_range = nearest.air_range if unit.is_flying else nearest.ground_range
            my_range = unit.air_range if nearest.is_flying else unit.ground_range
            if 0 < enemy_range < my_range:
                if run(self.ai, StutterUnitBack(unit=unit, target=nearest, kite_via_pathing=True,
                                                grid=ctx.grid_for(unit))):
                    continue
            attack_unit(unit, nearest)
