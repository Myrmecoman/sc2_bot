"""Basic Bunker crewing: load nearby bio units into a Bunker once its base is under ground threat, send them back to
the main army once it is safe again. Building the Bunker itself is macro's job (macro.py's build_bunkers) - this only
manages what already stands.

A crewed unit gets the UnitRole.CONTROL_GROUP_TWO role (Ares' own "use for anything not specified" slot - the one
CONTROL_GROUP_ONE already fills for the diversion squad, see manager.py) so the main army's own orders leave it alone
while it is garrisoned or walking over to load - the same trick HiddenBaseScouting uses to protect a sweep. Needs
UnitRole.CONTROL_GROUP_TWO added to manager.py's MANAGED_ROLES, or _sweep_roles would force it straight back to
ATTACKING every step.
"""
from typing import Dict, Set

from ares.consts import UnitRole
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.unit import Unit
from sc2.units import Units

from bot.army.consts import BIO_TYPES
from bot.army.context import ArmyContext
from bot.worker_micro import base_is_threatened

BUNKER_CREW_RANGE = 10.0    # a base this close to a visible ground threat gets its bunker crewed (matches worker_micro's BASE_DANGER_RANGE)
BUNKER_PICKUP_RANGE = 10.0  # how far from the bunker a bio unit can be and still be called in to crew it


class BunkerDefense:
    def __init__(self, ai):
        self.ai = ai
        self.crewed: Dict[int, Set[int]] = {}   # bunker tag -> tags of the units we put in it (loaded or still walking over)

    def update(self, ctx: ArmyContext, army_pool: Units) -> None:
        ai = self.ai
        bunkers = ai.structures(U.BUNKER).ready
        live_bunkers = {b.tag for b in bunkers}
        for tag in list(self.crewed):
            if tag not in live_bunkers:
                del self.crewed[tag]        # the bunker (and whoever was inside it) is gone

        alive = ai.units.tags
        taken: Set[int] = set()
        for bunker in bunkers:
            pending = self.crewed.setdefault(bunker.tag, set())
            pending &= (alive | bunker.passengers_tags)      # drop anyone who died on the way over
            if base_is_threatened(ai, bunker.position, radius=BUNKER_CREW_RANGE):
                taken |= self._crew(ctx, bunker, army_pool, pending, taken)
            else:
                self._empty(ctx, bunker, pending)

    def _crew(self, ctx: ArmyContext, bunker: Unit, army_pool: Units, pending: Set[int], taken: Set[int]) -> Set[int]:
        in_transit = pending - bunker.passengers_tags         # commanded to load, not yet actually inside
        space = bunker.cargo_left - len(in_transit)
        if space <= 0:
            return set()
        candidates = [
            u for u in army_pool
            if u.type_id in BIO_TYPES and u.tag not in taken and u.tag not in pending
            and u.distance_to(bunker) <= BUNKER_PICKUP_RANGE
        ]
        candidates.sort(key=lambda u: u.distance_to(bunker))
        picked = candidates[:space]
        for unit in picked:
            bunker(AbilityId.LOAD_BUNKER, unit)
            ctx.mediator.assign_role(tag=unit.tag, role=UnitRole.CONTROL_GROUP_TWO)
            pending.add(unit.tag)
        return {u.tag for u in picked}

    def _empty(self, ctx: ArmyContext, bunker: Unit, pending: Set[int]) -> None:
        if not pending:
            return
        if bunker.has_cargo:
            bunker(AbilityId.UNLOADALL_BUNKER, bunker.position)   # a target is not needed for this ability, but the
                                                                    # generic ability data declares one optional - give
                                                                    # its own position rather than leave it a no-op warning
        for tag in pending:
            ctx.mediator.assign_role(tag=tag, role=UnitRole.ATTACKING)
        pending.clear()
