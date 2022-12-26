from custom_utils import points_to_build_addon
from macro import smart_build
from macro import build_gas
from macro import build_cc

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2, Point3
from typing import FrozenSet, Set
from sc2.bot_ai import BotAI

MOVE_TO_DEPOT = -1
async def early_build_order(self : BotAI):
    global MOVE_TO_DEPOT

    if len(self.build_order) == 0:
        return
    if self.structures_without_construction_SCVs.amount > 0:
        self.build_order = []
        return

    # getting ramp wall positions
    depot_placement_positions: FrozenSet[Point2] = self.main_base_ramp.corner_depots
    # barracks_placement_position = self.main_base_ramp.barracks_in_middle # If you prefer to have the barracks in the middle without room for addons, use the following instead
    depots: Units = self.structures.of_type({UnitTypeId.SUPPLYDEPOT, UnitTypeId.SUPPLYDEPOTLOWERED})
    # Filter locations close to finished supply depots
    if depots:
        depot_placement_positions: Set[Point2] = {d for d in depot_placement_positions if depots.closest_distance_to(d) > 1}

    # move scv to depot position
    if self.build_order[0] == UnitTypeId.SUPPLYDEPOT and len(depot_placement_positions) < 2:
        location: Point2 = next(iter(depot_placement_positions))
        if location:
            if MOVE_TO_DEPOT == -1 or self.workers.find_by_tag(MOVE_TO_DEPOT) is None:
                worker: Unit = self.select_build_worker(location) # select the nearest worker to that location
                if worker is None:
                    return
                worker.move(location)
                MOVE_TO_DEPOT = worker.tag
            else:
                self.workers.find_by_tag(MOVE_TO_DEPOT).move(location)
    # Build depots
    if self.can_afford(UnitTypeId.SUPPLYDEPOT) and self.build_order[0] == UnitTypeId.SUPPLYDEPOT:
        target_depot_location: Point2 = depot_placement_positions.pop()
        await self.build(UnitTypeId.SUPPLYDEPOT, near=target_depot_location)
        self.build_order.pop(0)
        return
    # Build barracks
    if self.can_afford(UnitTypeId.BARRACKS) and self.build_order[0] == UnitTypeId.BARRACKS and self.tech_requirement_progress(UnitTypeId.BARRACKS) == 1:
        await smart_build(self, UnitTypeId.BARRACKS)
        self.build_order.pop(0)
        return
    # Build factory
    if self.can_afford(UnitTypeId.FACTORY) and self.build_order[0] == UnitTypeId.FACTORY and self.tech_requirement_progress(UnitTypeId.FACTORY) == 1:
        await smart_build(self, UnitTypeId.FACTORY)
        self.build_order.pop(0)
        return
    # Build refinery
    if self.can_afford(UnitTypeId.REFINERY) and self.build_order[0] == UnitTypeId.REFINERY:
        await build_gas(self)
        self.build_order.pop(0)
        return
    # move SCV to next expansion
    if self.build_order[0] == UnitTypeId.COMMANDCENTER:
        location: Point2 = await self.get_next_expansion()
        if location:
            worker: Unit = self.select_build_worker(location) # select the nearest worker to that location
            if worker is None:
                return
            worker.move(location)
    # Build command center
    if self.can_afford(UnitTypeId.COMMANDCENTER) and self.build_order[0] == UnitTypeId.COMMANDCENTER:
        await build_cc(self)
        self.build_order.pop(0)
        return
    # Build orbital
    orbital_tech_requirement: float = self.tech_requirement_progress(UnitTypeId.ORBITALCOMMAND)
    if orbital_tech_requirement == 1 and self.can_afford(UnitTypeId.ORBITALCOMMAND) and self.build_order[0] == UnitTypeId.ORBITALCOMMAND:
        cc: Unit
        for cc in self.townhalls(UnitTypeId.COMMANDCENTER).idle:
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
