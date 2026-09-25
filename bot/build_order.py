from bot.custom_utils import points_to_build_addon
from bot.macro import smart_build
from bot.macro import build_gas
from bot.macro import build_cc

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2, Point3
from typing import FrozenSet, Set
from sc2.bot_ai import BotAI
from sc2.data import Race

def maybe_prioritize_factory(self : BotAI):
    """Once the enemy is known to be Terran, move Factory earlier in the build order - checked
    every step (not just at game start) since a Random-pick opponent only reveals their race
    once we've actually seen a unit of theirs."""
    if self.factory_prioritized or self.enemy_race != Race.Terran:
        return
    self.factory_prioritized = True
    if UnitTypeId.FACTORY not in self.build_order:
        return
    self.build_order.remove(UnitTypeId.FACTORY)
    # factory needs both barracks (tech requirement) and a refinery (100 gas) - insert it right
    # after whichever of those is still later in the list, not just after barracks. Inserting it
    # right after barracks alone could land it BEFORE refinery (e.g. against a directly-known,
    # non-Random Terran opponent this runs on literally the first step, while the list is still
    # fully intact) - factory can then never be afforded (no gas income yet) while also
    # permanently blocking the build order from ever reaching the refinery step behind it
    insert_at = 0
    for prereq in (UnitTypeId.BARRACKS, UnitTypeId.REFINERY):
        if prereq in self.build_order:
            insert_at = max(insert_at, self.build_order.index(prereq) + 1)
    self.build_order.insert(insert_at, UnitTypeId.FACTORY)


BUILD_ORDER_TIMEOUT = 360.0 # give up on the scripted opening if it's still not done by now, and fall
                            # back to macro()'s continuously-retrying adaptive logic instead - a step
                            # stuck for any reason (no worker available, unexpected state) shouldn't be
                            # able to block macro() for the entire rest of the game
MOVE_TO_DEPOT = -1
async def early_build_order(self : BotAI):
    global MOVE_TO_DEPOT

    if len(self.build_order) == 0:
        self.build_order_critical_worker = None # covers build_order being cleared from anywhere else too (worker rush, timeout, abandoned construction)
        return

    maybe_prioritize_factory(self)

    if self.time > BUILD_ORDER_TIMEOUT:
        self.build_order = []
        return

    if self.structures_without_construction_SCVs.amount > 0:
        self.build_order = []
        return

    # SHOULD ADD CHECK HERE, IF BUILD COMMAND FAILED (SCV killed while going to build), CANCEL BUILD ORDER

    # getting ramp wall positions
    depot_placement_positions: FrozenSet[Point2] = self.main_base_ramp.corner_depots
    depots: Units = self.structures.of_type({UnitTypeId.SUPPLYDEPOT, UnitTypeId.SUPPLYDEPOTLOWERED})
    # Filter locations close to finished supply depots
    if depots:
        depot_placement_positions: Set[Point2] = {d for d in depot_placement_positions if depots.closest_distance_to(d) > 1}

    # move scv to depot position
    if self.build_order[0] == UnitTypeId.SUPPLYDEPOT and self.minerals > 25 and self.time > 1:
        location: Point2 = next(iter(depot_placement_positions))
        if location is not None:
            if MOVE_TO_DEPOT == -1 or self.workers.find_by_tag(MOVE_TO_DEPOT) is None:
                worker: Unit = self.select_build_worker(location) # select the nearest worker to that location
                if worker is None:
                    return
                worker.move(location)
                MOVE_TO_DEPOT = worker.tag
                self.build_order_critical_worker = worker.tag
            else:
                self.workers.find_by_tag(MOVE_TO_DEPOT).move(location)
    # Build depots
    if self.can_afford(UnitTypeId.SUPPLYDEPOT) and self.build_order[0] == UnitTypeId.SUPPLYDEPOT:
        target_depot_location: Point2 = depot_placement_positions.pop()
        if await self.build(UnitTypeId.SUPPLYDEPOT, near=target_depot_location, build_worker=self.workers.find_by_tag(MOVE_TO_DEPOT)):
            self.build_order.pop(0)
            MOVE_TO_DEPOT = -1
            self.build_order_critical_worker = None
        return
    # move scv to barracks position
    if self.build_order[0] == UnitTypeId.BARRACKS and self.minerals > 75 and self.time > 1:
        location = self.main_base_ramp.barracks_correct_placement
        if self.enemy_race == Race.Zerg or self.enemy_race == Race.Protoss:
            location = self.main_base_ramp.barracks_in_middle
        if location is not None:
            # keep the same committed worker across frames (like MOVE_TO_DEPOT above) instead of
            # re-picking "closest worker" every frame - otherwise a worker that's merely closer to
            # the spot this frame steals the critical-worker tag from one still walking there,
            # leaving the original unprotected mid-walk
            worker: Unit = self.workers.find_by_tag(self.build_order_critical_worker)
            if worker is None:
                worker = self.workers.closest_to(location) # select the nearest worker to that location
                if worker is None:
                    return
                self.build_order_critical_worker = worker.tag
            worker.move(location)
    # Build barracks
    if self.can_afford(UnitTypeId.BARRACKS) and self.build_order[0] == UnitTypeId.BARRACKS and self.tech_requirement_progress(UnitTypeId.BARRACKS) == 1:
        if await smart_build(self, UnitTypeId.BARRACKS):
            self.build_order.pop(0)
            self.build_order_critical_worker = None
        return
    # Build factory
    if self.can_afford(UnitTypeId.FACTORY) and self.build_order[0] == UnitTypeId.FACTORY and self.tech_requirement_progress(UnitTypeId.FACTORY) == 1:
        if await smart_build(self, UnitTypeId.FACTORY):
            self.build_order.pop(0)
        return
    # Build refinery
    if self.can_afford(UnitTypeId.REFINERY) and self.build_order[0] == UnitTypeId.REFINERY:
        if await build_gas(self):
            self.build_order.pop(0)
        return
    # move SCV to next expansion
    if self.build_order[0] == UnitTypeId.COMMANDCENTER and self.minerals > 250: # go to the next cc place when we are near able to build it
        location: Point2 = await self.get_next_expansion()
        if location is not None:
            # same reasoning as the barracks step above - keep the same committed worker instead
            # of re-picking one every frame
            worker: Unit = self.workers.find_by_tag(self.build_order_critical_worker)
            if worker is None:
                worker = self.select_build_worker(location) # select the nearest worker to that location
                if worker is None:
                    return
                self.build_order_critical_worker = worker.tag
            worker.move(location)
    # Build command center
    if self.can_afford(UnitTypeId.COMMANDCENTER) and self.build_order[0] == UnitTypeId.COMMANDCENTER:
        if await build_cc(self, build_worker=self.workers.find_by_tag(self.build_order_critical_worker)):
            self.build_order.pop(0)
            self.build_order_critical_worker = None
        return
    # Build orbital
    orbital_tech_requirement: float = self.tech_requirement_progress(UnitTypeId.ORBITALCOMMAND)
    if orbital_tech_requirement == 1 and self.can_afford(UnitTypeId.ORBITALCOMMAND) and self.build_order[0] == UnitTypeId.ORBITALCOMMAND:
        cc: Unit
        # not .idle - a CC training SCVs (which is most of the time, given build_worker() keeps it
        # busy) would never be idle, permanently stalling this step and everything after it
        for cc in self.townhalls(UnitTypeId.COMMANDCENTER).ready:
            if not cc.is_using_ability(AbilityId.UPGRADETOORBITAL_ORBITALCOMMAND):
                cc(AbilityId.UPGRADETOORBITAL_ORBITALCOMMAND)
            self.build_order.pop(0)
            return
    # Build barracks reactor
    if self.can_afford(UnitTypeId.BARRACKSREACTOR) and self.build_order[0] == UnitTypeId.BARRACKSREACTOR:
        bar: Unit
        for bar in self.structures(UnitTypeId.BARRACKS).ready.idle:
            if not bar.has_add_on:
                addon_points = points_to_build_addon(bar.position)
                if all(self.in_map_bounds(addon_point) and self.in_placement_grid(addon_point) and self.in_pathing_grid(addon_point) for addon_point in addon_points):
                    bar.build(UnitTypeId.BARRACKSREACTOR)
                    self.build_order.pop(0)
                    return
