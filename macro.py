from custom_utils import can_build_structure

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2
from sc2.bot_ai import BotAI


async def macro(self : BotAI):
    if len(self.build_order) != 0:
        return

    if self.townhalls.amount >= 2 and can_build_structure(self, UnitTypeId.STARPORT, 1):
        await self.build(UnitTypeId.STARPORT, near=self.townhalls.ready.first.position.towards(self.game_info.map_center, 8))
    if self.townhalls.amount >= 4 and can_build_structure(self, UnitTypeId.STARPORT, 2):
        await self.build(UnitTypeId.STARPORT, near=self.townhalls.ready.first.position.towards(self.game_info.map_center, 8))
    if self.townhalls.amount >= 2 and can_build_structure(self, UnitTypeId.FACTORY, 1):
        await self.build(UnitTypeId.FACTORY, near=self.townhalls.ready.first.position.towards(self.game_info.map_center, 8))
    if self.townhalls.amount >= 2 and can_build_structure(self, UnitTypeId.BARRACKS, 2):
        await self.build(UnitTypeId.BARRACKS, near=self.townhalls.ready.first.position.towards(self.game_info.map_center, 8))
    if self.townhalls.amount >= 3 and can_build_structure(self, UnitTypeId.BARRACKS, 5):
        await self.build(UnitTypeId.BARRACKS, near=self.townhalls.ready.first.position.towards(self.game_info.map_center, 8))
    if self.townhalls.amount >= 4 and can_build_structure(self, UnitTypeId.BARRACKS, 8):
        await self.build(UnitTypeId.BARRACKS, near=self.townhalls.ready.first.position.towards(self.game_info.map_center, 8))
    if self.townhalls.amount >= 3 and can_build_structure(self, UnitTypeId.ENGINEERINGBAY, 2):
        await self.build(UnitTypeId.ENGINEERINGBAY, near=self.townhalls.ready.first.position.towards(self.game_info.map_center, 8))
    if (self.already_pending_upgrade(UpgradeId.TERRANINFANTRYARMORSLEVEL1) > 0.3 or self.already_pending_upgrade(UpgradeId.TERRANINFANTRYWEAPONSLEVEL1)) > 0.3 and can_build_structure(self, UnitTypeId.ARMORY, 1):
        await self.build(UnitTypeId.ARMORY, near=self.townhalls.ready.first.position.towards(self.game_info.map_center, 8))
    if self.can_afford(UnitTypeId.COMMANDCENTER) and self.townhalls.amount < 12 and self.already_pending(UnitTypeId.COMMANDCENTER) == 0:
        location: Point2 = await self.get_next_expansion()
        if location:
            worker: Unit = self.select_build_worker(location) # select the nearest worker to that location
            worker.build(UnitTypeId.COMMANDCENTER, location)
        else:
            self.expand_now() # in case it won't work

    # build refineries
    refineries = self.structures(UnitTypeId.REFINERY)
    active_refineries = 0
    for r in refineries:
        if r.vespene_contents > 0:
            active_refineries += 1
    if self.townhalls.amount >= 3 and active_refineries < 4 and self.can_afford(UnitTypeId.REFINERY):
        for th in self.townhalls.ready:
            vgs: Units = self.vespene_geyser.closer_than(10, th)
            for vg in vgs:
                if await self.can_place_single(UnitTypeId.REFINERY, vg.position):
                    workers: Units = self.workers.gathering
                    if workers:
                        worker: Unit = workers.closest_to(vg)
                        worker.build_gas(vg)
                        break
    if self.townhalls.amount >= 4 and active_refineries < 6 and self.can_afford(UnitTypeId.REFINERY):
        for th in self.townhalls.ready:
            vgs: Units = self.vespene_geyser.closer_than(10, th)
            for vg in vgs:
                if await self.can_place_single(UnitTypeId.REFINERY, vg.position):
                    workers: Units = self.workers.gathering
                    if workers:
                        worker: Unit = workers.closest_to(vg)
                        worker.build_gas(vg)
                        break
