import time

from custom_utils import land_structures_for_addons
from custom_utils import build_worker
from custom_utils import handle_add_ons
from custom_utils import handle_depot_status
from custom_utils import handle_upgrades
from custom_utils import handle_workers
from custom_utils import handle_supply
from custom_utils import handle_orbitals
from custom_utils import handle_constructions
from build_order import early_build_order
from micro import micro
from macro import macro
from production import produce

from sc2 import maps
from sc2.player import Bot, Computer
from sc2.main import run_game
from sc2.data import Race, Difficulty
from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId

# usefull later : https://github.com/DrInfy/sharpy-sc2/blob/develop/sharpy/plans/tactics/speed_mining.py
# a few usefull variables
map_names = ["AcropolisLE", "DiscoBloodbathLE", "EphemeronLE", "ThunderbirdLE", "TritonLE", "WintersGateLE", "WorldofSleepersLE"]


# bot code --------------------------------------------------------------------------------------------------------
class SmoothBrainBot(BotAI):
    def __init__(self):
        self.unit_command_uses_self_do = False
        self.distance_calculation_method = 3
        self.build_order = [UnitTypeId.SUPPLYDEPOT, UnitTypeId.BARRACKS, UnitTypeId.REFINERY, UnitTypeId.ORBITALCOMMAND, UnitTypeId.COMMANDCENTER, UnitTypeId.SUPPLYDEPOT, UnitTypeId.FACTORY, UnitTypeId.REFINERY,
        UnitTypeId.BARRACKSREACTOR]


    async def on_step(self, iteration: int):
        time.sleep(0.02)
        await self.distribute_workers()
        handle_workers(self)
        handle_depot_status(self)
        handle_orbitals(self)
        await handle_supply(self)
        await early_build_order(self)
        await macro(self)
        build_worker(self)
        land_structures_for_addons(self)
        handle_add_ons(self)
        produce(self)
        handle_constructions(self)
        handle_upgrades(self)
        await micro(self)

        if self.townhalls.amount == 0 or self.supply_used == 0:
            await self.client.leave()
            return


def launch_game():
    run_game(maps.get("AcropolisLE"), # maps.get(map_names[random.randint(0, len(map_names) - 1)]),
            [Bot(Race.Terran, SmoothBrainBot()), Computer(Race.Random, Difficulty.VeryHard)], # VeryHard, VeryEasy, Medium
            realtime=False)


launch_game()
