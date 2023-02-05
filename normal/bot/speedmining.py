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
def get_speedmining_positions(self : BotAI) -> Dict[Point2, Point2]:
    targets = dict()
    worker_radius = self.workers[0].radius
    expansions: Dict[Point2, Units] = self.expansion_locations_dict
    for base, resources in expansions.items():
        for resource in resources:
            mining_radius = resource.radius + worker_radius
            target = resource.position.towards(base, mining_radius)
            for resource2 in resources.closer_than(mining_radius, target):
                points = get_intersections(resource.position, mining_radius, resource2.position, resource2.radius + worker_radius)
                target = min(points, key=lambda p: p.distance_to(self.start_location), default=target)
            targets[resource.position] = target
    return targets


def micro_worker(self : BotAI) -> None:

    if self.townhalls.ready.amount <= 0:
        return

    for unit in self.workers:
        if unit.is_idle:
            townhall = self.townhalls.ready.closest_to(unit)
            patch = self.mineral_field.closest_to(townhall)
            unit.gather(patch)
        if len(unit.orders) == 1: # speedmine
            target = None
            if unit.is_returning and not unit.is_carrying_vespene:
                target = self.townhalls.ready.closest_to(unit)
                move_target = target.position.towards(unit.position, target.radius + unit.radius)
            elif unit.is_gathering:
                target : Unit = self.resource_by_tag.get(unit.order_target)
                if target and not target.is_vespene_geyser and target.position in self.speedmining_positions.keys():
                    move_target = self.speedmining_positions[target.position]
            if target and not target.is_vespene_geyser and 2 * unit.radius < unit.distance_to(move_target) < SPEEDMINING_DISTANCE:
                unit.move(move_target)
                unit(AbilityId.SMART, target, True)


# Saturate refineries
def handle_refineries(self : BotAI, step: int):

    # update refineries ages and dictionary
    for r in self.gas_buildings.ready:
        if not r.tag in self.refineries_age.keys():
            self.refineries_age[r.tag] = step
    to_remove = []
    for k in self.refineries_age.keys():
        if self.gas_buildings.ready.find_by_tag(k) is None:
            to_remove.append(k)
    for i in to_remove:
        self.refineries_age.pop(i, None)

    # handle workers
    for r in self.gas_buildings.ready:
        if r.assigned_harvesters < r.ideal_harvesters and step - self.refineries_age[r.tag] > 4: # last check because when it is finished there are 0 workers altough the one building goes to it instantly
            workers: Units = self.workers.closer_than(10, r)
            if workers:
                for w in workers:
                    if not w.is_carrying_minerals and not w.is_carrying_vespene:
                        w.gather(r)
                        return
        if r.assigned_harvesters > r.ideal_harvesters or self.workers.amount <= 5:
            workers: Units = self.workers.closer_than(2, r)
            if workers:
                for w in workers:
                    if w.is_carrying_vespene:
                        w.gather(self.resources.mineral_field.closest_to(w), True)
                        return


def dispatch_workers(self : BotAI):
    # remove destroyed command centers from keys
    keys_to_delete = []
    for key in self.townhall_saturations.keys():
        if self.townhalls.ready.find_by_tag(key) is None:
            keys_to_delete.append(key)
    for i in keys_to_delete:
        del self.townhall_saturations[i]

    # add new command centers to keys and update its saturations
    maxes : Dict = {}
    for cc in self.townhalls.ready:
        if not cc.tag in self.townhall_saturations.keys():
            self.townhall_saturations[cc.tag] = []
        if len(self.townhall_saturations[cc.tag]) >= 40:
            self.townhall_saturations[cc.tag].pop(0)
        self.townhall_saturations[cc.tag].append(cc.assigned_harvesters)
        maxes[cc.tag] = max(self.townhall_saturations[cc.tag])
    
    # dispatch workers somewhere else if command center has too much of them
    for key in maxes.keys():
        cc1 = self.townhalls.ready.find_by_tag(key)
        if maxes[key] + 1 > cc1.ideal_harvesters:
            for key2 in maxes.keys():
                if key2 == key:
                    continue
                cc2 = self.townhalls.ready.find_by_tag(key2)
                if maxes[key2] + 1 < cc2.ideal_harvesters: # get workers gathering mineral from cc1 and move them to cc2
                    for w in self.workers.closer_than(10, cc1).gathering:
                        if self.mineral_field.closer_than(10, cc1).find_by_tag(w.order_target) is not None:
                            w.gather(w.position.closest(self.mineral_field.closer_than(10, cc2)))
                            maxes[key] -= 1
                            for i in range(len(self.townhall_saturations[key])):
                                self.townhall_saturations[key][i] -= 1
                            maxes[key2] += 1
                            for i in range(len(self.townhall_saturations[key2])):
                                self.townhall_saturations[key2][i] += 1
                            break


# distribute initial workers on mineral patches
def split_workers(self : BotAI) -> None:
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


def mine(self : BotAI, iteration):
    dispatch_workers(self)
    micro_worker(self)
    handle_refineries(self, iteration)