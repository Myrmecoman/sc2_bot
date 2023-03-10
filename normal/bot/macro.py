from bot.custom_utils import can_build_structure
from bot.custom_utils import get_safest_expansion

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2, Point3
from typing import FrozenSet, Set
from sc2.bot_ai import BotAI
from sc2.data import Race
import math


async def build_gas(self : BotAI):
    for cc in self.townhalls.ready:
        vgs: Units = self.vespene_geyser.closer_than(12, cc)
        for vg in vgs:
            if await self.can_place_single(UnitTypeId.REFINERY, vg.position):
                workers: Units = self.workers.gathering
                if workers:
                    worker: Unit = workers.closest_to(vg)
                    worker.build_gas(vg)
                    break


async def build_cc(self : BotAI):
    location: Point2 = await get_safest_expansion(self)
    if location:
        worker: Unit = self.select_build_worker(location) # select the nearest worker to that location
        if worker is None:
            return
        self.worker_assigned_to_expand[worker.tag] = worker
        worker.build(UnitTypeId.COMMANDCENTER, location)


async def try_build_on_line(self : BotAI, type : UnitTypeId, prod_structures : Units, shift = 0):
    for i in prod_structures:
        if await self.can_place_single(type, Point2((i.position.x + shift, i.position.y + 3))) and await self.can_place_single(type, Point2((i.position.x + shift, i.position.y + 6))):
            await self.build(type, near=Point2((i.position.x + shift, i.position.y + 3)))
            return True
        if await self.can_place_single(type, Point2((i.position.x + shift, i.position.y - 3))) and await self.can_place_single(type, Point2((i.position.x + shift, i.position.y - 6))):
            await self.build(type, near=Point2((i.position.x + shift, i.position.y - 3)))
            return True
    return False


async def smart_build(self : BotAI, type : UnitTypeId):

    if not self.can_afford(UnitTypeId.BARRACKS) or self.tech_requirement_progress(UnitTypeId.BARRACKS) != 1:
        return False

    prod_structures : Units = self.structures.of_type({UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT})

    if prod_structures.amount == 0 and self.main_base_ramp.barracks_in_middle:
        worker: Unit = self.workers.closest_to(self.main_base_ramp.barracks_in_middle) # pretty unsafe but works and should not pose any issue
        if worker is None:
            return False
        pos = self.main_base_ramp.barracks_correct_placement
        if self.enemy_race == Race.Zerg or self.enemy_race == Race.Protoss:
            pos = self.main_base_ramp.barracks_in_middle
        if self.can_place_single(type, pos):
            worker.build(type, pos)
            return True
        return False

    # build as a line from any started line
    if await try_build_on_line(self, type, prod_structures):
        return True
    
    # else try to build on right or left alternatively
    if await try_build_on_line(self, type, prod_structures, -7):
        return True
    if await try_build_on_line(self, type, prod_structures, 7):
        return True
    
    # else well try further
    if await try_build_on_line(self, type, prod_structures, -14):
        return True
    if await try_build_on_line(self, type, prod_structures, 14):
        return True
    # no place found
    return False


HALF_OFFSET = Point2((.5, .5))
async def smart_build_behind_mineral(self : BotAI, type : UnitTypeId):
    # try all ccs and find average position of its mineral fields
    for cc in self.townhalls.ready:
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
        for i in range(20):
            position = cc.position.towards_with_random_angle(Point2((x, y)), 9, (math.pi / 3))
            position_further = cc.position.towards_with_random_angle(Point2((x, y)), 12, (math.pi / 3))
            position.rounded.offset(HALF_OFFSET)
            position_further.rounded.offset(HALF_OFFSET)
            if await self.can_place_single(type, position):
                await self.build(type, near=position, max_distance=4)
                return
            if await self.can_place_single(type, position_further):
                await self.build(type, near=position_further, max_distance=4)
                return
        print("Could not place tech building behind mineral lines")


def repair_buildings(self : BotAI):

    if self.worker_rushed and not self.army_advisor.is_wall_closed():
        return
    
    # adding tag if needs to be repaired, else remove it
    for i in self.structures.ready:
        if i.health_percentage > 0.9:
            if i.tag in self.worker_assigned_to_repair.keys():
                self.worker_assigned_to_repair.pop(i.tag)
            continue
        if i.tag in self.worker_assigned_to_repair.keys():
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
            if self.workers.find_by_tag(worker_tag) is not None:
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
            if wo.distance_to(i) < 30 and (total_repairing < 2 or total_repairing < 4 and i.health_percentage < 0.5):
                wo(AbilityId.EFFECT_REPAIR_SCV, i)
                self.worker_assigned_to_repair[key].append(wo.tag)
                total_repairing = len(self.worker_assigned_to_repair[key])


def cancel_building(self : BotAI):
    for st in self.structures:
        if not st.is_ready and st.health_percentage < 0.1:
            st(AbilityId.CANCEL)


def resume_building_construction(self : BotAI):
    # checking if it is actually safe to resume construction
    for i in self.structures_without_construction_SCVs:
        if (self.enemy_units.amount != 0 and self.enemy_units.closest_distance_to(i)) < 8 or (not self.army_advisor.is_wall_closed() and (self.worker_rushed or self.army_advisor.zergling_rushed)):
            return
    
    # update dictionary if building or worker died
    to_remove = [] # list of elements to remove from dictionary
    for k in self.worker_assigned_to_resume_building.keys():
        if self.structures.find_by_tag(k) is None or self.units.find_by_tag(self.worker_assigned_to_resume_building[k]) is None:
            to_remove.append(k)
    for i in to_remove:
        self.worker_assigned_to_resume_building.pop(i, None)

    # assign a worker for each building
    for i in self.structures_without_construction_SCVs:
        if i.tag in self.worker_assigned_to_resume_building.keys():
            continue
        if self.workers.gathering.amount == 0:
            continue
        worker = self.workers.gathering.closest_to(i)
        self.worker_assigned_to_resume_building[i.tag] = worker.tag
        worker(AbilityId.SMART, i)


async def macro(self : BotAI):

    cancel_building(self)
    repair_buildings(self)
    resume_building_construction(self)

    if len(self.build_order) != 0 or self.workers.amount == 0:
        return

    if self.townhalls.amount >= 2 and can_build_structure(self, UnitTypeId.STARPORT, UnitTypeId.STARPORTFLYING, 1):
        await smart_build(self, UnitTypeId.STARPORT)
    if self.townhalls.amount >= 4 and can_build_structure(self, UnitTypeId.STARPORT, UnitTypeId.STARPORTFLYING, 2):
        await smart_build(self, UnitTypeId.STARPORT)

    if self.townhalls.amount >= 1 and can_build_structure(self, UnitTypeId.FACTORY, UnitTypeId.FACTORYFLYING, 1):
        await smart_build(self, UnitTypeId.FACTORY)
    
    if self.townhalls.amount >= 1 and can_build_structure(self, UnitTypeId.BARRACKS, UnitTypeId.BARRACKSFLYING, 1):
        await smart_build(self, UnitTypeId.BARRACKS)
    if self.townhalls.amount >= 2 and can_build_structure(self, UnitTypeId.BARRACKS, UnitTypeId.BARRACKSFLYING, 2):
        await smart_build(self, UnitTypeId.BARRACKS)
    if self.townhalls.amount >= 3 and can_build_structure(self, UnitTypeId.BARRACKS, UnitTypeId.BARRACKSFLYING, 5):
        await smart_build(self, UnitTypeId.BARRACKS)
    if self.townhalls.amount >= 4 and can_build_structure(self, UnitTypeId.BARRACKS, UnitTypeId.BARRACKSFLYING, 8):
        await smart_build(self, UnitTypeId.BARRACKS)

    if self.townhalls.amount >= 3 and can_build_structure(self, UnitTypeId.ENGINEERINGBAY, None, 2):
        await smart_build_behind_mineral(self, UnitTypeId.ENGINEERINGBAY)

    if (self.already_pending_upgrade(UpgradeId.TERRANINFANTRYARMORSLEVEL1) > 0.3 or self.already_pending_upgrade(UpgradeId.TERRANINFANTRYWEAPONSLEVEL1)) > 0.3 and can_build_structure(self, UnitTypeId.ARMORY, None, 1):
        await smart_build_behind_mineral(self, UnitTypeId.ARMORY)
    if self.already_pending_upgrade(UpgradeId.TERRANINFANTRYWEAPONSLEVEL3) == 1 and can_build_structure(self, UnitTypeId.ARMORY, None, 2):
        await smart_build_behind_mineral(self, UnitTypeId.ARMORY)

    if (self.already_pending_upgrade(UpgradeId.TERRANINFANTRYARMORSLEVEL3) == 1 or self.already_pending_upgrade(UpgradeId.TERRANINFANTRYWEAPONSLEVEL3)) == 1 and can_build_structure(self, UnitTypeId.FUSIONCORE, None, 1):
        await smart_build_behind_mineral(self, UnitTypeId.FUSIONCORE)

    if self.can_afford(UnitTypeId.COMMANDCENTER) and self.townhalls.amount < 20 and (self.already_pending(UnitTypeId.COMMANDCENTER) == 0 or self.minerals > 2000):
        await build_cc(self)

    # get refineries count
    refineries = self.structures(UnitTypeId.REFINERY)
    active_refineries = 0
    for r in refineries:
        if r.vespene_contents > 20:
            active_refineries += 1
    for w in self.workers:
        if isinstance(w.order_target, int) and self.vespene_geyser.find_by_tag(w.order_target) is not None:
            active_refineries += 1
    
    # build refineries
    if self.worker_rushed and not self.army_advisor.is_wall_closed() and self.structures.of_type(UnitTypeId.REFINERY).amount != 0:
        if self.structure_type_build_progress(UnitTypeId.REFINERY) < 1:
            self.structures.of_type(UnitTypeId.REFINERY).first(AbilityId.CANCEL)
    if self.townhalls.amount >= 1 and active_refineries < 1 and self.can_afford(UnitTypeId.REFINERY) and self.structures(UnitTypeId.BARRACKS).amount > 0 and (not self.worker_rushed or self.army_advisor.is_wall_closed()):
        await build_gas(self)
    if self.townhalls.amount >= 2 and active_refineries < 2 and self.can_afford(UnitTypeId.REFINERY):
        await build_gas(self)
    if self.townhalls.amount >= 2 and self.structures(UnitTypeId.STARPORT).amount > 0 and active_refineries < 3 and self.can_afford(UnitTypeId.REFINERY):
        await build_gas(self)
    if self.townhalls.amount >= 3 and active_refineries < 4 and self.can_afford(UnitTypeId.REFINERY):
        await build_gas(self)
    if self.townhalls.amount >= 4 and active_refineries < 6 and self.can_afford(UnitTypeId.REFINERY):
        await build_gas(self)
    if self.townhalls.amount >= 5 and active_refineries < 7 and self.can_afford(UnitTypeId.REFINERY):
        await build_gas(self)
    if self.townhalls.amount >= 5 and active_refineries < 8 and self.can_afford(UnitTypeId.REFINERY) and self.minerals > 1200:
        await build_gas(self)
