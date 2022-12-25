import numpy as np
import math
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2
from sc2.bot_ai import BotAI
from typing import Dict, Iterable, List, Optional, Set


SPEEDMINING_DISTANCE = 1.8


# yield the intersection points of two circles at points p0, p1 with radii r0, r1
def get_intersections(p0: Point2, r0: float, p1: Point2, r1: float) -> Iterable[Point2]:
    p01 = p1 - p0
    d = np.linalg.norm(p01)
    if d == 0:
        return  # intersection is empty or infinite
    if d < abs(r0 - r1):
        return  # circles inside of each other
    if r0 + r1 < d:
        return  # circles too far apart
    a = (r0 ** 2 - r1 ** 2 + d ** 2) / (2 * d)
    h = math.sqrt(r0 ** 2 - a ** 2)
    pm = p0 + (a / d) * p01
    po = (h / d) * np.array([p01.y, -p01.x])
    yield pm + po
    yield pm - po


# fix workers bumping into adjacent minerals by slightly shifting the move commands
def get_speedmining_positions(self) -> Dict[Point2, Point2]:
    targets = dict()
    worker_radius = self.workers[0].radius
    expansions: Dict[Point2, Units] = self.expansion_locations_dict
    for base, resources in expansions.items():
        for resource in resources:
            mining_radius = resource.radius + worker_radius
            target = resource.position.towards(base, mining_radius)
            for resource2 in resources.closer_than(mining_radius, target):
                points = get_intersections(resource.position, mining_radius, resource2.position,
                                            resource2.radius + worker_radius)
                target = min(points, key=lambda p: p.distance_to(self.start_location), default=target)
            targets[resource.position] = target
    return targets


def micro_worker(self, unit: Unit) -> None:
    if unit.is_idle:
        if any(self.mineral_field):
            townhall = self.townhalls.closest_to(unit)
            patch = self.mineral_field.closest_to(townhall)
            unit.gather(patch)
    elif any(self.transfer_from) and any(self.transfer_to) and unit.order_target == self.transfer_from[0].tag:
        patch = self.mineral_field.closest_to(self.transfer_to.pop(0))
        self.transfer_from.pop(0)
        unit.gather(patch)
    elif any(self.transfer_from_gas) and unit.order_target in self.gas_buildings.tags and not unit.is_carrying_resource:
        unit.stop()
        self.transfer_from_gas.pop(0)
    elif any(self.transfer_to_gas) and not unit.is_carrying_resource and len(unit.orders) < 2 and unit.order_target not in self.close_minerals:
        unit.gather(self.transfer_to_gas.pop(0))
    if len(unit.orders) == 1: # speedmine
        target = None
        if unit.is_returning:
            target = self.townhalls.closest_to(unit)
            move_target = target.position.towards(unit.position, target.radius + unit.radius)
        elif unit.is_gathering:
            target = self.resource_by_tag.get(unit.order_target)
            if target:
                move_target = self.speedmining_positions[target.position]
        if target and 2 * unit.radius < unit.distance_to(move_target) < SPEEDMINING_DISTANCE:
            unit.move(move_target)
            unit(AbilityId.SMART, target, True)


def micro_structure(self, unit: Unit) -> None:
    if unit.is_vespene_geyser:
        if unit.is_ready and unit.assigned_harvesters + 1 < self.gas_harvester_target:
            self.transfer_to_gas.extend(unit for _ in range(unit.assigned_harvesters + 1, self.gas_harvester_target))
        elif self.gas_harvester_target < unit.assigned_harvesters:
            self.transfer_from_gas.extend(unit for _ in range(self.gas_harvester_target, unit.assigned_harvesters))
    elif unit.type_id == UnitTypeId.COMMANDCENTER or unit.type_id == UnitTypeId.ORBITALCOMMAND or unit.type_id == UnitTypeId.PLANETARYFORTRESS:
        if unit.is_ready:
            if 0 < unit.surplus_harvesters:
                self.transfer_from.extend(unit for _ in range(0, unit.surplus_harvesters))
            elif unit.surplus_harvesters < 0:
                self.transfer_to.extend(unit for _ in range(unit.surplus_harvesters, 0))


# Saturate refineries
def handle_refineries(self : BotAI):
    for refinery in self.gas_buildings:
        if refinery.assigned_harvesters < refinery.ideal_harvesters:
            worker: Units = self.workers.closer_than(10, refinery)
            if worker:
                worker.random.gather(refinery)


# distribute initial workers on mineral patches
def split_workers(self) -> None:
    minerals = self.expansion_locations_dict[self.start_location].mineral_field.sorted_by_distance_to(self.start_location)
    self.close_minerals = {m.tag for m in minerals[0:4]}
    assigned: Set[int] = set()
    for i in range(self.workers.amount):
        patch = minerals[i % len(minerals)]
        if i < len(minerals):
            worker = self.workers.tags_not_in(assigned).closest_to(patch) # first, each patch gets one worker closest to it
        else:
            worker = self.workers.tags_not_in(assigned).furthest_to(patch) # the remaining workers get longer paths, this usually results in double stacking without having to spam orders
        worker.gather(patch)
        assigned.add(worker.tag)
