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
        self.building_starport = 0
        self.building_factory = 0
        self.building_barrack = 0
        self.building_engi = 0


    def can_build_structure(self, type, amount):
        return self.structures(type).ready.amount + self.already_pending(type) < amount and self.can_afford(type) and self.tech_requirement_progress(type) == 1


    # Return all points that need to be checked when trying to build an addon. Returns 4 points.
    def starport_points_to_build_addon(self, sp_position: Point2) -> List[Point2]:
        addon_offset: Point2 = Point2((2.5, -0.5))
        addon_position: Point2 = sp_position + addon_offset
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
            workers: Units = self.workers.gathering
            if workers:  # if workers were found
                worker: Unit = workers.random
                worker.build(UnitTypeId.SUPPLYDEPOT, target_depot_location)
                self.build_order.pop(0)
        # Build barrack
        if depots.ready and self.can_afford(UnitTypeId.BARRACKS) and self.build_order[0] == UnitTypeId.BARRACKS:
            workers = self.workers.gathering
            if workers and barracks_placement_position:  # if workers were found
                worker: Unit = workers.random
                worker.build(UnitTypeId.BARRACKS, barracks_placement_position)
                self.building_barrack += 1
                self.build_order.pop(0)
        # Build factory
        if self.can_afford(UnitTypeId.FACTORY) and self.build_order[0] == UnitTypeId.FACTORY and self.tech_requirement_progress(UnitTypeId.FACTORY) == 1:
            await self.build(UnitTypeId.FACTORY, near=ccs.ready.first.position.towards(self.game_info.map_center, 8))
            self.building_factory += 1
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
                    addon_points = self.starport_points_to_build_addon(bar.position)
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
        # Manage orbital energy and drop mules
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
        if not self.can_afford(UnitTypeId.SCV) or self.townhalls.amount <= 0 or self.workers.amount > 70:
            return
        ccs: Units = self.townhalls
        for cc in ccs:
            if cc.is_idle:
                cc.train(UnitTypeId.SCV)
                break
    

    def produce(self):
        for bar in self.structures(UnitTypeId.BARRACKS).ready.idle:
            if bar.has_add_on and self.can_afford(UnitTypeId.HELLION): # suppose reactor for now
                bar.build(UnitTypeId.MARINE)
                bar.build(UnitTypeId.MARINE)
            elif self.can_afford(UnitTypeId.MARINE):
                bar.build(UnitTypeId.MARINE)
        for fac in self.structures(UnitTypeId.FACTORY).ready.idle:
            if self.can_afford(UnitTypeId.HELLION):
                fac.build(UnitTypeId.HELLION)
        for st in self.structures(UnitTypeId.STARPORT).ready.idle:
            if self.can_afford(UnitTypeId.MEDIVAC) and self.units(UnitTypeId.MEDIVAC).amount < 8:
                st.build(UnitTypeId.MEDIVAC)
    

    async def handle_add_ons():
        return
    

    async def macro(self):
        if len(self.build_order) != 0:
            return
        if self.townhalls.amount >= 2 and self.can_build_structure(UnitTypeId.STARPORT, 1):
            self.building_starport += 1
            await self.build(UnitTypeId.STARPORT, near=self.townhalls.ready.first.position.towards(self.game_info.map_center, 8))
        if self.townhalls.amount >= 2 and self.can_build_structure(UnitTypeId.FACTORY, 1):
            self.building_factory += 1
            await self.build(UnitTypeId.FACTORY, near=self.townhalls.ready.first.position.towards(self.game_info.map_center, 8))
        if self.townhalls.amount >= 2 and self.can_build_structure(UnitTypeId.BARRACKS, 2):
            self.building_barrack += 1
            await self.build(UnitTypeId.BARRACKS, near=self.townhalls.ready.first.position.towards(self.game_info.map_center, 8))
        if self.townhalls.amount >= 3 and self.can_build_structure(UnitTypeId.BARRACKS, 5):
            self.building_barrack += 1
            await self.build(UnitTypeId.BARRACKS, near=self.townhalls.ready.first.position.towards(self.game_info.map_center, 8))
        if self.townhalls.amount >= 4 and self.can_build_structure(UnitTypeId.BARRACKS, 8):
            self.building_barrack += 1
            await self.build(UnitTypeId.BARRACKS, near=self.townhalls.ready.first.position.towards(self.game_info.map_center, 8))
        if self.townhalls.amount >= 3 and self.can_build_structure(UnitTypeId.ENGINEERINGBAY, 2):
            self.building_engi += 1
            await self.build(UnitTypeId.ENGINEERINGBAY, near=self.townhalls.ready.first.position.towards(self.game_info.map_center, 8))
        if self.minerals > 500 and self.townhalls.amount < 15:
            await self.expand_now()


    async def micro(self):
        units = []
        units.append(self.units(UnitTypeId.MARINE))
        units.append(self.units(UnitTypeId.HELLION))
        units.append(self.units(UnitTypeId.MEDIVAC))

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
    

    async def on_building_construction_complete(self, Structure: Unit):
        if Structure.type_id == UnitTypeId.BARRACKS:
            self.building_barrack -= 1
        if Structure.type_id == UnitTypeId.FACTORY:
            self.building_factory -= 1
        if Structure.type_id == UnitTypeId.STARPORT:
            self.building_starport -= 1
        if Structure.type_id == UnitTypeId.ENGINEERINGBAY:
            self.building_engi -= 1


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

        if self.townhalls.amount == 0 or self.supply_used == 0:
            await self.client.leave()
            return


def launch_game():
    run_game(maps.get(map_names[random.randint(0, len(map_names) - 1)]),
            [Bot(Race.Terran, BasicBot()), Computer(Race.Random, Difficulty.Hard)], # VeryHard, VeryEasy, Medium
            realtime=False)


launch_game()
