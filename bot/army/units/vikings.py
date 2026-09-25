"""Vikings (air mode): dedicated hit-and-run. They ALWAYS kite - no hold-and-trade, no pushing in - because at 135 HP
with no shields and no real armor a Viking cannot afford to eat a free hit for the sake of holding ground."""
from cython_extensions import cy_attack_ready, cy_closest_to, cy_in_attack_range, cy_pick_enemy_target

from ares.behaviors.combat.individual import StutterUnitBack
from sc2.unit import Unit
from sc2.units import Units

from bot.army.context import ArmyContext
from bot.army.orders import GroupOrders
from bot.army.units.common import attack_move, attack_unit, follow_point, kite_away, path_move, run



class VikingController:
    def __init__(self, ai):
        self.ai = ai

    def control(self, units: Units, orders: GroupOrders, ctx: ArmyContext) -> None:
        ctx.prefetch_near(units)
        for unit in units:
            self._control_unit(unit, orders, ctx)

    def _control_unit(self, unit: Unit, orders: GroupOrders, ctx: ArmyContext) -> None:
        targets = ctx.targets_near(unit)     # a Viking in air mode can only hit flying units, so that is all it sees
        if not targets:
            self._no_fight(unit, orders, ctx)
            return

        in_range = cy_in_attack_range(unit, targets)
        target: Unit = cy_pick_enemy_target(in_range) if in_range else cy_closest_to(unit.position, targets)

        # shoot when ready, otherwise back away from danger - StutterUnitBack is exactly that pair of rules
        if run(self.ai, StutterUnitBack(unit=unit, target=target, kite_via_pathing=True, grid=ctx.air_grid)):
            return
        # safe and on cooldown: close the distance to the target rather than idling
        attack_unit(unit, target)

    def _no_fight(self, unit: Unit, orders: GroupOrders, ctx: ArmyContext) -> None:
        # nothing to shoot - still never idle in a dangerous spot
        if kite_away(self.ai, ctx, unit):
            return
        point = follow_point(orders)
        if orders.aggressive:
            attack_move(unit, point)
        elif unit.distance_to(point) > orders.hold_radius:
            path_move(self.ai, ctx, unit, point)
