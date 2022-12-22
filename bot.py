import time

from custom_utils import land_structures_for_addons
from custom_utils import build_worker
from custom_utils import handle_add_ons
from custom_utils import handle_depot_status
from custom_utils import handle_upgrades
from custom_utils import handle_supply
from custom_utils import handle_orbitals
from custom_utils import handle_constructions
from build_order import early_build_order
from micro import micro
from micro import split_workers
from macro import macro
from production import produce
from speedmining import get_speedmining_positions
from speedmining import micro_structure
from speedmining import micro_worker
from speedmining import handle_refineries

from typing import Dict, Iterable, List, Optional, Set
from itertools import chain

from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit


# bot code --------------------------------------------------------------------------------------------------------
class SmoothBrainBot(BotAI):
    def __init__(self):
        self.unit_command_uses_self_do = False
        self.distance_calculation_method = 3
        self.worker_rushed = False
        self.game_step: int = 2
        self.tags: Set[str] = set()
        self.first_barracks = None
        self.build_order = [UnitTypeId.SUPPLYDEPOT, UnitTypeId.BARRACKS, UnitTypeId.REFINERY, UnitTypeId.ORBITALCOMMAND, UnitTypeId.COMMANDCENTER, UnitTypeId.SUPPLYDEPOT, UnitTypeId.FACTORY, UnitTypeId.REFINERY,
        UnitTypeId.BARRACKSREACTOR]
        super().__init__()


    async def on_before_start(self) -> None:
        self.client.game_step = self.game_step


    async def on_start(self) -> None:
        self.speedmining_positions = get_speedmining_positions(self)
        split_workers(self)


    async def on_step(self, iteration: int):

        if self.townhalls.amount == 0 or self.supply_used == 0:
            await self.client.leave()
            return

        self.client.game_step = self.game_step

        self.transfer_from: List[Unit] = list()
        self.transfer_to: List[Unit] = list()
        self.transfer_from_gas: List[Unit] = list()
        self.transfer_to_gas: List[Unit] = list()
        self.resource_by_tag = {unit.tag: unit for unit in chain(self.mineral_field, self.gas_buildings)}

        '''
        for structure in self.structures:
            micro_structure(self, structure)
        for worker in self.workers:
            micro_worker(self, worker)
        '''
        await self.distribute_workers(0)
        handle_refineries(self)

        handle_depot_status(self)
        handle_orbitals(self)
        await handle_supply(self)

        if not self.worker_rushed:
            await early_build_order(self)
        elif len(self.build_order) != 0:
            self.build_order = []

        await macro(self)
        build_worker(self)
        land_structures_for_addons(self)
        handle_add_ons(self)
        produce(self)
        handle_constructions(self)
        handle_upgrades(self)
        await micro(self)
