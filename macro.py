from custom_utils import can_build_structure

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2
from sc2.bot_ai import BotAI
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
    if self.workers.amount == 0:
        return
    location: Point2 = await self.get_next_expansion()
    if location:
        worker: Unit = self.select_build_worker(location) # select the nearest worker to that location
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
    prod_structures : Units = self.structures.of_type({UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT})

    if prod_structures.amount == 0:
        await self.build(type, near=self.main_base_ramp.barracks_correct_placement)
        return

    if prod_structures.amount == 1:
        self.first_barracks = prod_structures.first

    # build as a line from any started line
    if await try_build_on_line(self, type, prod_structures):
        return
    
    # else try to build on right or left alternatively
    if await try_build_on_line(self, type, prod_structures, -7):
        return
    if await try_build_on_line(self, type, prod_structures, 7):
        return
    
    # else well try further
    if await try_build_on_line(self, type, prod_structures, -14):
        return
    if await try_build_on_line(self, type, prod_structures, 14):
        return
    Exception("No place found")


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

async def macro(self : BotAI):

    for st in self.structures:
        if not st.is_ready and st.health_percentage < 0.1:
            st(AbilityId.CANCEL)

    if len(self.build_order) != 0 or self.workers.amount == 0:
        return

    if self.townhalls.amount >= 2 and can_build_structure(self, UnitTypeId.STARPORT, UnitTypeId.STARPORTFLYING, 1):
        await smart_build(self, UnitTypeId.STARPORT)
    if self.townhalls.amount >= 4 and can_build_structure(self, UnitTypeId.STARPORT, UnitTypeId.STARPORTFLYING, 2):
        await smart_build(self, UnitTypeId.STARPORT)

    if self.townhalls.amount >= 2 and can_build_structure(self, UnitTypeId.FACTORY, UnitTypeId.FACTORYFLYING, 1):
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

    if self.can_afford(UnitTypeId.COMMANDCENTER) and self.townhalls.amount < 15 and (self.already_pending(UnitTypeId.COMMANDCENTER) == 0 or self.minerals > 2000):
        await build_cc(self)

    # build refineries
    refineries = self.structures(UnitTypeId.REFINERY)
    active_refineries = 0
    for r in refineries:
        if r.vespene_contents > 20:
            active_refineries += 1
    if self.townhalls.amount >= 3 and active_refineries < 4 and self.can_afford(UnitTypeId.REFINERY):
        await build_gas(self)
    if self.townhalls.amount >= 4 and active_refineries < 6 and self.can_afford(UnitTypeId.REFINERY):
        await build_gas(self)
    if self.townhalls.amount >= 5 and active_refineries < 7 and self.can_afford(UnitTypeId.REFINERY):
        await build_gas(self)
    if self.townhalls.amount >= 5 and active_refineries < 8 and self.can_afford(UnitTypeId.REFINERY) and self.minerals > 1200:
        await build_gas(self)
