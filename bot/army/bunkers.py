"""Basic Bunker crewing: load nearby bio units into a Bunker once its base is under ground threat - or, proactively,
once the enemy is believed to be committing to a one-base all-in (army_advisor.enemy_likely_one_base, no need to wait
for their army to actually show up at our door first) - and send the crew back to the main army once neither is true
any more, OR once the main army is actually attacking: there is no point leaving a few Marines idle in a Bunker while
the rest of the army marches off to fight - they come along and the push is that much bigger - UNLESS something is
genuinely, visibly threatening that exact base right now, which always wins (never abandon an active defense just
because the army happens to be attacking somewhere else). Building the Bunker itself is macro's job (macro.py's
build_bunkers) - this only manages what already stands.

The proactive "one-base all-in" hold is time-boxed (ONE_BASE_ALL_IN_GRACE below): enemy_likely_one_base is a live,
undecaying read (true for as long as we have not seen a second enemy townhall - which can be the entire game, if the
enemy really is one-basing or we simply never scout their natural) and manager.py's own `attacking` is the strict,
sim-committed whole-army push flag (requires a maxed or grouped-and-winning army - see _update_push_state) - NOT just
"our units are out and visibly fighting". A real game report (bunkers never unloading despite the player watching
their own army attack) traced to exactly this: `one_base_all_in` can outlast any single push, or stay true for a game
where `attacking` never once meets its own bar, so pending.clear() in _empty() could never run. Past the grace window
the precaution is dropped regardless of `attacking` - the all-in either already happened (threatened catches that) or
it did not, and either way hoarding Marines forever against one that never comes is pure loss.

The crew pool is the main army AND any base-defense detachment already heading the same way (manager.py passes both
roles in) - a detachment sent to answer the very threat that is also asking the bunker to crew is a far more likely
source of nearby bodies than hoping the main army happens to already be standing on top of this specific base.

A crewed unit gets the UnitRole.CONTROL_GROUP_TWO role (Ares' own "use for anything not specified" slot - the one
CONTROL_GROUP_ONE already fills for the diversion squad, see manager.py) so the main army's own orders leave it alone
while it is garrisoned or walking over to load - the same trick HiddenBaseScouting uses to protect a sweep. Needs
UnitRole.CONTROL_GROUP_TWO added to manager.py's MANAGED_ROLES, or _sweep_roles would force it straight back to
ATTACKING every step.
"""
from typing import Dict, Optional, Set

from ares.consts import UnitRole
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.unit import Unit
from sc2.units import Units

from bot.army.consts import BIO_TYPES
from bot.army.context import ArmyContext
from bot.worker_micro import base_is_threatened

BUNKER_CREW_RANGE = 10.0    # a base this close to a visible ground threat gets its bunker crewed (matches worker_micro's BASE_DANGER_RANGE)
BUNKER_PICKUP_RANGE = 20.0  # how far from the bunker a bio unit can be and still be called in to crew it - wider than the
                            # threat-detection range itself, since the main army holding elsewhere is the common case, not
                            # a unit already standing right on top of the bunker
ONE_BASE_ALL_IN_GRACE = 180.0  # how long the proactive one-base-all-in hold outlasts `attacking` staying false before it is
                                # dropped anyway (UNVERIFIED number - long enough to cover a slow one-base tech timing, short
                                # enough that a suspicion that never pans out does not hoard Marines for the rest of the game)


class BunkerDefense:
    def __init__(self, ai):
        self.ai = ai
        self.crewed: Dict[int, Set[int]] = {}   # bunker tag -> tags of the units we put in it (loaded or still walking over)
        self.one_base_all_in_since: Optional[float] = None   # game time the current one_base_all_in streak started, or None

    def update(self, ctx: ArmyContext, army_pool: Units, attacking: bool) -> None:
        ai = self.ai
        bunkers = ai.structures(U.BUNKER).ready
        live_bunkers = {b.tag for b in bunkers}
        for tag in list(self.crewed):
            if tag not in live_bunkers:
                del self.crewed[tag]        # the bunker (and whoever was inside it) is gone

        alive = ai.units.tags
        one_base_all_in = ai.army_advisor.enemy_likely_one_base
        if one_base_all_in:
            if self.one_base_all_in_since is None:
                self.one_base_all_in_since = ai.time
            one_base_all_in = ai.time - self.one_base_all_in_since < ONE_BASE_ALL_IN_GRACE
        else:
            self.one_base_all_in_since = None
        taken: Set[int] = set()
        for bunker in bunkers:
            pending = self.crewed.setdefault(bunker.tag, set())
            pending &= (alive | bunker.passengers_tags)      # drop anyone who died on the way over
            threatened = base_is_threatened(ai, bunker.position, radius=BUNKER_CREW_RANGE)
            if threatened or (one_base_all_in and not attacking):
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
