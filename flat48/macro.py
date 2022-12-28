from custom_utils import can_build_structure

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2
from sc2.bot_ai import BotAI
import math


async def build_cc(self : BotAI):
    location: Point2 = await self.get_next_expansion()
    if location:
        worker: Unit = self.select_build_worker(location) # select the nearest worker to that location
        if worker is None:
            return
        worker.build(UnitTypeId.COMMANDCENTER, location)


async def smart_build(self : BotAI, type : UnitTypeId):
    await self.build(type, near=self.townhalls.first.position.towards(self.game_info.map_center, -8))


HALF_OFFSET = Point2((.5, .5))
async def smart_build_behind_mineral(self : BotAI, type : UnitTypeId):
    # try all ccs and find average position of its mineral fields
    for cc in self.townhalls:
        mfs: Units = self.mineral_field.closer_than(10, cc)
        if mfs.amount == 0:
            continue
        x = 0
        y = 0
        for i in mfs:
            x += i.position.x
            y += i.position.y
        x = x // mfs.amount
        y = y // mfs.amount
        # try to place at a few positions
        for i in range(30):
            position = cc.position.towards_with_random_angle(Point2((x, y)), 11, (math.pi / 3))
            position.rounded.offset(HALF_OFFSET)
            if await self.can_place_single(type, position):
                await self.build(type, near=position, max_distance=4)
                return
        print("Could not place tech building behind mineral lines")


def repair_buildings(self : BotAI):

    if self.worker_rushed:
        return

    # adding tag if needs to be repaired, else remove it
    for i in self.structures.ready:
        nb_enemy_workers_around = 0
        for w in self.enemy_units.of_type({UnitTypeId.SCV, UnitTypeId.PROBE, UnitTypeId.DRONE}):
            if w.distance_to(i) < 5:
                nb_enemy_workers_around += 1
        if i.health_percentage > 0.9 or nb_enemy_workers_around > 2:
            if i.tag in self.worker_assigned_to_repair.keys():
                self.worker_assigned_to_repair.pop(i.tag)
            continue
        if i.tag in self.worker_assigned_to_repair:
            continue
        self.worker_assigned_to_repair[i.tag] = []
    
    for key in self.worker_assigned_to_repair.keys():
        if self.structures.find_by_tag(key) is None: # the building died
            continue
        total_repairing = len(self.worker_assigned_to_repair[key])
        
        # removing dead SCVs from the lists
        new_value = []
        for i in range(total_repairing):
            worker_tag = self.worker_assigned_to_repair[key][i]
            if self.units.of_type({UnitTypeId.SCV}).find_by_tag(worker_tag) is not None:
                new_value.append(worker_tag)
        self.worker_assigned_to_repair[key] = new_value
        total_repairing = len(self.worker_assigned_to_repair[key])

        i = self.structures.find_by_tag(key)
        if total_repairing >= 4 or (i.health_percentage >= 0.5 and total_repairing >= 2):
            continue
        
        sorted_workers : Units = self.workers.sorted(lambda x: x.distance_to(i))
        for wo in sorted_workers:
            if wo.is_repairing or wo.is_constructing_scv:
                continue
            if wo.distance_to(i) < 30 and total_repairing < 2:
                wo(AbilityId.EFFECT_REPAIR_SCV, i)
                self.worker_assigned_to_repair[key].append(wo.tag)
                total_repairing = len(self.worker_assigned_to_repair[key])
            if wo.distance_to(i) < 30 and total_repairing < 4 and i.health_percentage < 0.5:
                wo(AbilityId.EFFECT_REPAIR_SCV, i)
                self.worker_assigned_to_repair[key].append(wo.tag)
                total_repairing = len(self.worker_assigned_to_repair[key])


def cancel_building(self : BotAI):
    for st in self.structures:
        if not st.is_ready and st.health_percentage < 0.1:
            st(AbilityId.CANCEL)


def resume_building_construction(self : BotAI):
    # checking if it is actually safe to resume construction
    for i in self.structures:
        if self.enemy_units.amount != 0 and self.enemy_units.closest_distance_to(i) < 12:
            return

    for i in self.structures_without_construction_SCVs:
        if self.workers.gathering.amount == 0:
            return
        worker = self.workers.gathering.closest_to(i)
        worker(AbilityId.EFFECT_REPAIR_SCV, i)


async def macro(self : BotAI):

    cancel_building(self)
    repair_buildings(self)
    resume_building_construction(self)

    if self.townhalls.amount >= 1 and can_build_structure(self, UnitTypeId.BARRACKS, UnitTypeId.BARRACKSFLYING, 5):
        await smart_build_behind_mineral(self, UnitTypeId.BARRACKS)
    if self.townhalls.amount >= 2 and can_build_structure(self, UnitTypeId.BARRACKS, UnitTypeId.BARRACKSFLYING, 9):
        await smart_build_behind_mineral(self, UnitTypeId.BARRACKS)

    if self.can_afford(UnitTypeId.COMMANDCENTER) and self.townhalls.amount < 3 and (self.already_pending(UnitTypeId.COMMANDCENTER) == 0 or self.minerals > 2000):
        await build_cc(self)
