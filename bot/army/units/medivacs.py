"""Medivacs: heal (Ares MedivacHeal keeps them out of anti-air fire), boost when it is ready, and otherwise follow the
army instead of flying ahead of it."""
from ares.behaviors.combat.individual import MedivacHeal
from ares.consts import UnitTreeQueryType
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit
from sc2.units import Units

from bot.army.context import ArmyContext
from bot.army.orders import GroupOrders
from bot.army.units.common import attack_move, follow_point, path_move, run

HEAL_SEARCH_RADIUS = 10.0   # allied units within this of a medivac are considered for healing
BEHIND_OFFSET = 4.0         # while holding, sit this far behind the bio position (away from the enemy)


class MedivacController:
    def __init__(self, ai):
        self.ai = ai

    def control(self, units: Units, orders: GroupOrders, ctx: ArmyContext) -> None:
        if not units:
            return
        nearby_allies = ctx.mediator.get_units_in_range(
            start_points=list(units),
            distances=HEAL_SEARCH_RADIUS,
            query_tree=UnitTreeQueryType.AllOwn,
            return_as_dict=True,
        )
        for unit in units:
            self._control_unit(unit, orders, ctx, nearby_allies.get(unit.tag, []))

    def _control_unit(self, unit: Unit, orders: GroupOrders, ctx: ArmyContext, allies) -> None:
        # Afterburners whenever they are off cooldown (not optimal, but far better than never using them)
        if AbilityId.EFFECT_MEDIVACIGNITEAFTERBURNERS in unit.abilities:
            unit(AbilityId.EFFECT_MEDIVACIGNITEAFTERBURNERS)

        # heal the closest hurt biological unit; MedivacHeal itself moves the medivac out of anti-air range first
        if run(self.ai, MedivacHeal(unit=unit, close_allied=list(allies), grid=ctx.air_grid, keep_safe=True)):
            return

        # nothing to heal (and safe): keep up with the army
        point = follow_point(orders)
        if orders.aggressive:
            attack_move(unit, point)
            return
        point = point - orders.front * BEHIND_OFFSET
        if unit.distance_to(point) > orders.hold_radius:
            path_move(self.ai, ctx, unit, point)
