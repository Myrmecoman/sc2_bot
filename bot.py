import numpy as np
import random
from collections import namedtuple, deque
import pathlib
import cv2
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


# a few usefull variables
map_names = ["AcropolisLE", "DiscoBloodbathLE", "EphemeronLE", "ThunderbirdLE", "TritonLE", "WintersGateLE", "WorldofSleepersLE"]
current_dir = str(pathlib.Path(__file__).parent.absolute())


# bot code --------------------------------------------------------------------------------------------------------
class BasicBot(BotAI):


    def __init__(self):
        self.unit_command_uses_self_do = False


    def wall_ramp(self):
        depot_placement_positions: FrozenSet[Point2] = self.main_base_ramp.corner_depots
        barracks_placement_position: Point2 = self.main_base_ramp.barracks_correct_placement
        # If you prefer to have the barracks in the middle without room for addons, use the following instead
        # barracks_placement_position = self.main_base_ramp.barracks_in_middle
        depots: Units = self.structures.of_type({UnitTypeId.SUPPLYDEPOT, UnitTypeId.SUPPLYDEPOTLOWERED})
        # Filter locations close to finished supply depots
        if depots:
            depot_placement_positions: Set[Point2] = {d for d in depot_placement_positions if depots.closest_distance_to(d) > 1}
        # Build depots
        if self.can_afford(UnitTypeId.SUPPLYDEPOT) and self.already_pending(UnitTypeId.SUPPLYDEPOT) == 0:
            if len(depot_placement_positions) == 0:
                return
            # Choose any depot location
            target_depot_location: Point2 = depot_placement_positions.pop()
            workers: Units = self.workers.gathering
            if workers:  # if workers were found
                worker: Unit = workers.random
                worker.build(UnitTypeId.SUPPLYDEPOT, target_depot_location)
        # Build barracks
        if depots.ready and self.can_afford(UnitTypeId.BARRACKS) and self.already_pending(UnitTypeId.BARRACKS) == 0:
            if self.structures(UnitTypeId.BARRACKS).amount + self.already_pending(UnitTypeId.BARRACKS) > 0:
                return
            workers = self.workers.gathering
            if workers and barracks_placement_position:  # if workers were found
                worker: Unit = workers.random
                worker.build(UnitTypeId.BARRACKS, barracks_placement_position)


    def handle_depot_status(self):
        # Raise depos when enemies are nearby
        for depo in self.structures(UnitTypeId.SUPPLYDEPOT).ready:
            for unit in self.enemy_units:
                if unit.distance_to(depo) < 15:
                    break
            else:
                depo(AbilityId.MORPH_SUPPLYDEPOT_LOWER)
        # Lower depos when no enemies are nearby
        for depo in self.structures(UnitTypeId.SUPPLYDEPOTLOWERED).ready:
            for unit in self.enemy_units:
                if unit.distance_to(depo) < 10:
                    depo(AbilityId.MORPH_SUPPLYDEPOT_RAISE)
                    break

    async def handle_supply(self, amount=1):
        if self.supply_left > 3 or not self.can_afford(UnitTypeId.SUPPLYDEPOT) or self.supply_cap >= 200:
            return
        
        ccs: Units = self.townhalls
        for i in range(amount):
            await self.build(UnitTypeId.SUPPLYDEPOT, near=ccs.random.position.towards(self.game_info.map_center, 8))


    def build_worker(self):
        if not self.can_afford(UnitTypeId.SCV):
            return

        ccs: Units = self.townhalls
        if ccs.amount <= 0:
            return

        for cc in ccs:
            if cc.is_idle:
                cc.train(UnitTypeId.SCV)
                break


    async def on_step(self, iteration: int):

        time.sleep(0.1)

        await self.distribute_workers()

        self.build_worker()
        #await self.handle_supply()
        self.handle_depot_status()
        self.wall_ramp()

        if self.townhalls.amount <= 0 or self.supply_used == 0:
            await self.client.leave()
            return


def launch_game():
    run_game(maps.get(map_names[random.randint(0, len(map_names) - 1)]),
            [Bot(Race.Terran, BasicBot()), Computer(Race.Random, Difficulty.Easy)], # VeryHard, VeryEasy
            realtime=False)

launch_game()
