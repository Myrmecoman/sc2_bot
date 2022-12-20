import numpy as np
import random
from collections import namedtuple, deque
import pathlib
import time
from threading import Thread
from sc2 import maps
from sc2.player import Bot, Computer
from sc2.main import run_game
from sc2.data import Race, Difficulty
from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit
from sc2.units import Units
from sc2.ids.ability_id import AbilityId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2, Point3
from typing import FrozenSet, Set
from typing import List, Tuple


# a few usefull variables
map_names = ["AcropolisLE", "DiscoBloodbathLE", "EphemeronLE", "ThunderbirdLE", "TritonLE", "WintersGateLE", "WorldofSleepersLE"]


# bot code --------------------------------------------------------------------------------------------------------
class BasicBot(BotAI):
    def __init__(self):
        self.unit_command_uses_self_do = False
        # build order
        self.build_order = [UnitTypeId.SUPPLYDEPOT, UnitTypeId.BARRACKS, UnitTypeId.REFINERY, UnitTypeId.ORBITALCOMMAND, UnitTypeId.COMMANDCENTER, UnitTypeId.SUPPLYDEPOT, UnitTypeId.FACTORY, UnitTypeId.REFINERY,
        UnitTypeId.BARRACKSREACTOR]


    def can_build_structure(self, type, amount):
        return self.structures(type).ready.amount + self.already_pending(type) < amount and self.can_afford(type) and self.tech_requirement_progress(type) == 1


    # Return all points that need to be checked when trying to build an addon. Returns 4 points.
    def points_to_build_addon(self, u_position: Point2) -> List[Point2]:
        addon_offset: Point2 = Point2((2.5, -0.5))
        addon_position: Point2 = u_position + addon_offset
        addon_points = [(addon_position + Point2((x - 0.5, y - 0.5))).rounded for x in range(0, 2) for y in range(0, 2)]
        return addon_points


    async def early_build_order(self):

        if len(self.build_order) == 0:
            return

        # getting ramp wall positions
        depot_placement_positions: FrozenSet[Point2] = self.main_base_ramp.corner_depots
        barracks_placement_position: Point2 = self.main_base_ramp.barracks_correct_placement
        # barracks_placement_position = self.main_base_ramp.barracks_in_middle # If you prefer to have the barracks in the middle without room for addons, use the following instead
        depots: Units = self.structures.of_type({UnitTypeId.SUPPLYDEPOT, UnitTypeId.SUPPLYDEPOTLOWERED})
        # Filter locations close to finished supply depots
        if depots:
            depot_placement_positions: Set[Point2] = {d for d in depot_placement_positions if depots.closest_distance_to(d) > 1}
        ccs: Units = self.townhalls

        # Build depots
        depots: Units = self.structures.of_type({UnitTypeId.SUPPLYDEPOT, UnitTypeId.SUPPLYDEPOTLOWERED})
        if self.can_afford(UnitTypeId.SUPPLYDEPOT) and self.build_order[0] == UnitTypeId.SUPPLYDEPOT:
            target_depot_location: Point2 = depot_placement_positions.pop()
            await self.build(UnitTypeId.SUPPLYDEPOT, near=target_depot_location)
            self.build_order.pop(0)
        # Build barracks
        if self.can_afford(UnitTypeId.BARRACKS) and self.build_order[0] == UnitTypeId.BARRACKS and self.tech_requirement_progress(UnitTypeId.BARRACKS) == 1 and barracks_placement_position:
            await self.build(UnitTypeId.BARRACKS, near=barracks_placement_position)
            self.build_order.pop(0)
        # Build factory
        if self.can_afford(UnitTypeId.FACTORY) and self.build_order[0] == UnitTypeId.FACTORY and self.tech_requirement_progress(UnitTypeId.FACTORY) == 1:
            await self.build(UnitTypeId.FACTORY, near=ccs.ready.first.position.towards(self.game_info.map_center, 8))
            self.build_order.pop(0)
        # Build refinery
        if self.can_afford(UnitTypeId.REFINERY) and self.build_order[0] == UnitTypeId.REFINERY:
            vgs: Units = self.vespene_geyser.closer_than(20, self.townhalls.ready.first)
            for vg in vgs:
                if self.gas_buildings.filter(lambda unit: unit.distance_to(vg) < 1):
                    break
                worker: Unit = self.select_build_worker(vg.position)
                if worker is None:
                    break
                worker.build_gas(vg)
                self.build_order.pop(0)
                break
        # Build command center
        if self.can_afford(UnitTypeId.COMMANDCENTER) and self.build_order[0] == UnitTypeId.COMMANDCENTER:
            await self.expand_now()
            self.build_order.pop(0)
        # Build orbital
        orbital_tech_requirement: float = self.tech_requirement_progress(UnitTypeId.ORBITALCOMMAND)
        if orbital_tech_requirement == 1 and self.can_afford(UnitTypeId.ORBITALCOMMAND) and self.build_order[0] == UnitTypeId.ORBITALCOMMAND:
            cc: Unit
            for cc in self.townhalls(UnitTypeId.COMMANDCENTER).idle:
                cc(AbilityId.UPGRADETOORBITAL_ORBITALCOMMAND)
                self.build_order.pop(0)
                break
        # Build barracks reactor
        if self.can_afford(UnitTypeId.BARRACKSREACTOR) and self.build_order[0] == UnitTypeId.BARRACKSREACTOR:
            bar: Unit
            for bar in self.structures(UnitTypeId.BARRACKS).ready.idle:
                if not bar.has_add_on:
                    addon_points = self.points_to_build_addon(bar.position)
                    if all(self.in_map_bounds(addon_point) and self.in_placement_grid(addon_point) and self.in_pathing_grid(addon_point) for addon_point in addon_points):
                        bar.build(UnitTypeId.BARRACKSREACTOR)
                        self.build_order.pop(0)


    def handle_depot_status(self):
        if self.enemy_units.amount == 0:
            for depo in self.structures(UnitTypeId.SUPPLYDEPOT).ready:
                depo(AbilityId.MORPH_SUPPLYDEPOT_LOWER)
        else:
            for depo in self.structures(UnitTypeId.SUPPLYDEPOT).ready:
                for unit in self.enemy_units.not_flying:
                    if unit.distance_to(depo) < 15:
                        break
                    else:
                        depo(AbilityId.MORPH_SUPPLYDEPOT_LOWER)
            for depo in self.structures(UnitTypeId.SUPPLYDEPOTLOWERED).ready:
                for unit in self.enemy_units:
                    if unit.distance_to(depo) < 10:
                        depo(AbilityId.MORPH_SUPPLYDEPOT_RAISE)
                        break

    
    def handle_workers(self):
        # Saturate refineries
        for refinery in self.gas_buildings:
            if refinery.assigned_harvesters < refinery.ideal_harvesters:
                worker: Units = self.workers.closer_than(10, refinery)
                if worker:
                    worker.random.gather(refinery)


    async def handle_supply(self):
        if self.supply_left < 5 and self.supply_used >= 14 and self.can_afford(UnitTypeId.SUPPLYDEPOT) and self.already_pending(UnitTypeId.SUPPLYDEPOT) < 1 and len(self.build_order) == 0:
            workers: Units = self.workers.gathering
            if workers:
                worker: Unit = workers.furthest_to(workers.center)
                location: Point2 = await self.find_placement(UnitTypeId.SUPPLYDEPOT, worker.position, placement_step=3)
                if location:
                    worker.build(UnitTypeId.SUPPLYDEPOT, location)
                if len(self.build_order) == 0:
                    ccs: Units = self.townhalls
                    await self.build(UnitTypeId.SUPPLYDEPOT, near=ccs.random.position.towards(self.game_info.map_center, 8))


    def handle_orbitals(self):
        # Manage orbital energy and drop mules if we need minerals, else keep for scanning
        if self.minerals < 800:
            for oc in self.townhalls(UnitTypeId.ORBITALCOMMAND).filter(lambda x: x.energy >= 50):
                mfs: Units = self.mineral_field.closer_than(10, oc)
                if mfs:
                    mf: Unit = max(mfs, key=lambda x: x.mineral_contents)
                    oc(AbilityId.CALLDOWNMULE_CALLDOWNMULE, mf)
        # Build orbital
        if self.can_afford(UnitTypeId.ORBITALCOMMAND) and len(self.build_order) == 0:
            cc: Unit
            for cc in self.townhalls(UnitTypeId.COMMANDCENTER).idle:
                cc(AbilityId.UPGRADETOORBITAL_ORBITALCOMMAND)
                break


    def build_worker(self):
        if not self.can_afford(UnitTypeId.SCV) or self.townhalls.amount == 0 or self.workers.amount > 70 or self.workers.amount >= self.townhalls.amount * 22:
            return
        ccs: Units = self.townhalls
        for cc in ccs:
            if cc.is_idle:
                cc.train(UnitTypeId.SCV)
                break
    

    def produce(self):
        for bar in self.structures(UnitTypeId.BARRACKS).ready.idle:
            if bar.has_add_on:
                add_on = self.structures.find_by_tag(bar.add_on_tag)
                if add_on is None:
                    continue
                if add_on.type_id == UnitTypeId.BARRACKSTECHLAB and self.can_afford(UnitTypeId.MARAUDER):
                    bar.build(UnitTypeId.MARAUDER)
                elif add_on.type_id == UnitTypeId.BARRACKSREACTOR and self.can_afford(UnitTypeId.MARINE):
                    bar.build(UnitTypeId.MARINE)
                    if self.can_afford(UnitTypeId.MARINE):
                        bar.build(UnitTypeId.MARINE)
            elif self.can_afford(UnitTypeId.MARINE):
                bar.build(UnitTypeId.MARINE)

        for fac in self.structures(UnitTypeId.FACTORY).ready.idle:
            if fac.has_add_on:
                add_on = self.structures.find_by_tag(fac.add_on_tag)
                if add_on is None:
                    continue
                if add_on.type_id == UnitTypeId.FACTORYTECHLAB and self.can_afford(UnitTypeId.SIEGETANK):
                    fac.build(UnitTypeId.SIEGETANK)
                elif add_on.type_id == UnitTypeId.FACTORYREACTOR and self.can_afford(UnitTypeId.HELLION):
                    fac.build(UnitTypeId.HELLION)
                    if self.can_afford(UnitTypeId.HELLION):
                        fac.build(UnitTypeId.HELLION)
            elif self.can_afford(UnitTypeId.HELLION):
                fac.build(UnitTypeId.HELLION)

        for st in self.structures(UnitTypeId.STARPORT).ready.idle:
            if st.has_add_on:
                add_on = self.structures.find_by_tag(st.add_on_tag)
                if add_on is None:
                    continue
                if add_on.type_id == UnitTypeId.STARPORTTECHLAB and self.can_afford(UnitTypeId.RAVEN) and self.units(UnitTypeId.RAVEN).amount < 4:
                    st.build(UnitTypeId.RAVEN)
                elif add_on.type_id == UnitTypeId.STARPORTREACTOR and self.can_afford(UnitTypeId.MEDIVAC) and self.units(UnitTypeId.MEDIVAC).amount < 8:
                    st.build(UnitTypeId.MEDIVAC)
                    if self.can_afford(UnitTypeId.MEDIVAC):
                        st.build(UnitTypeId.MEDIVAC)
            elif self.can_afford(UnitTypeId.MEDIVAC) and self.units(UnitTypeId.MEDIVAC).amount < 8:
                st.build(UnitTypeId.MEDIVAC)
    

    def build_add_on(self, type, add_on_type):
        # Build addon or lift if no room to build addon
        u: Unit
        for u in self.structures(type).ready.idle:
            if not u.has_add_on and self.can_afford(add_on_type):
                addon_points = self.points_to_build_addon(u.position)
                if all(self.in_map_bounds(addon_point) and self.in_placement_grid(addon_point) and self.in_pathing_grid(addon_point) for addon_point in addon_points):
                    u.build(add_on_type)
                else:
                    u(AbilityId.LIFT)
                break
    

    def land_structures_for_addons(self):
        # Return all points that need to be checked when trying to land at a location where there is enough space to build an addon. Returns 13 points.
        def land_positions(u_position: Point2) -> List[Point2]:
            land_positions = [(u_position + Point2((x, y))).rounded for x in range(-1, 2) for y in range(-1, 2)]
            return land_positions + self.points_to_build_addon(u_position)

        # Find a position to land for a flying structure so that it can build an addon
        for u in self.structures.of_type({UnitTypeId.BARRACKSFLYING, UnitTypeId.FACTORYFLYING, UnitTypeId.STARPORTFLYING}).idle:
            possible_land_positions_offset = sorted((Point2((x, y)) for x in range(-10, 10) for y in range(-10, 10)), key=lambda point: point.x**2 + point.y**2,)
            offset_point: Point2 = Point2((-0.5, -0.5))
            possible_land_positions = (u.position.rounded + offset_point + p for p in possible_land_positions_offset)
            for target_land_position in possible_land_positions:
                land_and_addon_points: List[Point2] = land_positions(target_land_position)
                if all(self.in_map_bounds(land_pos) and self.in_placement_grid(land_pos) and self.in_pathing_grid(land_pos) for land_pos in land_and_addon_points):
                    u(AbilityId.LAND, target_land_position)
                    break
    

    def handle_add_ons(self):
        if len(self.build_order) != 0:
            return

        bars: Units = self.structures(UnitTypeId.BARRACKS)
        for b in bars.ready.idle:
            if self.structures(UnitTypeId.BARRACKSREACTOR).amount + self.already_pending(UnitTypeId.BARRACKSREACTOR) < bars.amount/2:
                if self.can_afford(UnitTypeId.REACTOR):
                    self.build_add_on(UnitTypeId.BARRACKS, UnitTypeId.BARRACKSREACTOR)
            elif self.can_afford(UnitTypeId.TECHLAB):
                self.build_add_on(UnitTypeId.BARRACKS, UnitTypeId.BARRACKSTECHLAB)

        fac: Units = self.structures(UnitTypeId.FACTORY)
        for f in fac.ready.idle:
            if self.structures(UnitTypeId.FACTORYTECHLAB).amount + self.already_pending(UnitTypeId.FACTORYTECHLAB) < fac.amount/2:
                if self.can_afford(UnitTypeId.TECHLAB):
                    self.build_add_on(UnitTypeId.FACTORY, UnitTypeId.FACTORYTECHLAB)
            elif self.can_afford(UnitTypeId.REACTOR):
                self.build_add_on(UnitTypeId.FACTORY, UnitTypeId.FACTORYREACTOR)

        sp: Units = self.structures(UnitTypeId.STARPORT)
        for s in sp.ready.idle:
            if self.structures(UnitTypeId.STARPORTREACTOR).amount + self.already_pending(UnitTypeId.STARPORTREACTOR) < sp.amount/2:
                if self.can_afford(UnitTypeId.REACTOR):
                    self.build_add_on(UnitTypeId.STARPORT, UnitTypeId.STARPORTREACTOR)
            elif self.can_afford(UnitTypeId.TECHLAB):
                self.build_add_on(UnitTypeId.STARPORT, UnitTypeId.STARPORTTECHLAB)
    

    def handle_constructions(self):
        for b in self.structures_without_construction_SCVs:
            return
    

    def handle_upgrades(self):
        engis = self.structures(UnitTypeId.ENGINEERINGBAY).ready.idle
        for engi in engis:
            if self.can_afford(UpgradeId.TERRANINFANTRYARMORSLEVEL1) and self.already_pending_upgrade(UpgradeId.TERRANINFANTRYARMORSLEVEL1) == 0:
                engi.research(UpgradeId.TERRANINFANTRYARMORSLEVEL1)
            elif self.can_afford(UpgradeId.TERRANINFANTRYWEAPONSLEVEL1) and self.already_pending_upgrade(UpgradeId.TERRANINFANTRYWEAPONSLEVEL1) == 0:
                engi.research(UpgradeId.TERRANINFANTRYWEAPONSLEVEL1)
            
            if self.can_afford(UpgradeId.TERRANINFANTRYARMORSLEVEL2) and self.already_pending_upgrade(UpgradeId.TERRANINFANTRYARMORSLEVEL2) == 0:
                engi.research(UpgradeId.TERRANINFANTRYARMORSLEVEL2)
            elif self.can_afford(UpgradeId.TERRANINFANTRYWEAPONSLEVEL2) and self.already_pending_upgrade(UpgradeId.TERRANINFANTRYWEAPONSLEVEL2) == 0:
                engi.research(UpgradeId.TERRANINFANTRYWEAPONSLEVEL2)
            
            if self.can_afford(UpgradeId.TERRANINFANTRYARMORSLEVEL3) and self.already_pending_upgrade(UpgradeId.TERRANINFANTRYARMORSLEVEL3) == 0:
                engi.research(UpgradeId.TERRANINFANTRYARMORSLEVEL3)
            elif self.can_afford(UpgradeId.TERRANINFANTRYWEAPONSLEVEL3) and self.already_pending_upgrade(UpgradeId.TERRANINFANTRYWEAPONSLEVEL3) == 0:
                engi.research(UpgradeId.TERRANINFANTRYWEAPONSLEVEL3)


    async def macro(self):
        if len(self.build_order) != 0:
            return

        if self.townhalls.amount >= 2 and self.can_build_structure(UnitTypeId.STARPORT, 1):
            await self.build(UnitTypeId.STARPORT, near=self.townhalls.ready.first.position.towards(self.game_info.map_center, 8))
        if self.townhalls.amount >= 2 and self.can_build_structure(UnitTypeId.FACTORY, 1):
            await self.build(UnitTypeId.FACTORY, near=self.townhalls.ready.first.position.towards(self.game_info.map_center, 8))
        if self.townhalls.amount >= 2 and self.can_build_structure(UnitTypeId.BARRACKS, 2):
            await self.build(UnitTypeId.BARRACKS, near=self.townhalls.ready.first.position.towards(self.game_info.map_center, 8))
        if self.townhalls.amount >= 3 and self.can_build_structure(UnitTypeId.BARRACKS, 5):
            await self.build(UnitTypeId.BARRACKS, near=self.townhalls.ready.first.position.towards(self.game_info.map_center, 8))
        if self.townhalls.amount >= 4 and self.can_build_structure(UnitTypeId.BARRACKS, 8):
            await self.build(UnitTypeId.BARRACKS, near=self.townhalls.ready.first.position.towards(self.game_info.map_center, 8))
        if self.townhalls.amount >= 3 and self.can_build_structure(UnitTypeId.ENGINEERINGBAY, 2):
            await self.build(UnitTypeId.ENGINEERINGBAY, near=self.townhalls.ready.first.position.towards(self.game_info.map_center, 8))
        if (self.already_pending_upgrade(UpgradeId.TERRANINFANTRYARMORSLEVEL1) or self.already_pending_upgrade(UpgradeId.TERRANINFANTRYWEAPONSLEVEL1)) and self.can_afford(UnitTypeId.ARMORY):
            await self.build(UnitTypeId.ARMORY, near=self.townhalls.ready.first.position.towards(self.game_info.map_center, 8))
        if self.can_afford(UnitTypeId.COMMANDCENTER) and self.townhalls.amount < 12:
            await self.expand_now()

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


    async def micro(self):
        units = []
        units.append(self.units(UnitTypeId.MARINE))
        units.append(self.units(UnitTypeId.MARAUDER))
        units.append(self.units(UnitTypeId.HELLION))
        units.append(self.units(UnitTypeId.SIEGETANK))
        units.append(self.units(UnitTypeId.MEDIVAC))
        units.append(self.units(UnitTypeId.RAVEN))

        if len(units) == 0:
            return

        attack = True
        pos = self.townhalls.closest_to(self.game_info.map_center).position.towards(self.game_info.map_center, 10)
        if self.supply_army > 30:
            enemies: Units = self.enemy_units | self.enemy_structures
            enemy_closest: Units = enemies.sorted(lambda x: x.distance_to(self.start_location))
            if enemy_closest.amount > 0:
                pos = enemy_closest[0]
            else:
                pos = self.enemy_start_locations[0]
        if self.supply_army < 20:
            pos = self.townhalls.closest_to(self.game_info.map_center).position.towards(self.game_info.map_center, 10)
            attack = False

        for i in units:
            for j in i:
                if attack:
                    j.attack(pos)
                else:
                    j.move(pos)


    async def on_step(self, iteration: int):

        time.sleep(0.03)
        await self.distribute_workers()
        self.handle_workers()
        self.handle_depot_status()
        self.handle_orbitals()
        await self.early_build_order()
        await self.handle_supply()
        await self.macro()
        await self.micro()
        self.build_worker()
        self.produce()
        self.land_structures_for_addons()
        self.handle_add_ons()
        self.handle_constructions()
        self.handle_upgrades()

        if self.townhalls.amount == 0 or self.supply_used == 0:
            await self.client.leave()
            return


def launch_game():
    run_game(maps.get("AcropolisLE"), # maps.get(map_names[random.randint(0, len(map_names) - 1)]),
            [Bot(Race.Terran, BasicBot()), Computer(Race.Random, Difficulty.VeryHard)], # VeryHard, VeryEasy, Medium
            realtime=False)


launch_game()
