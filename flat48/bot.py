import time

from custom_utils import build_worker
from custom_utils import handle_depot_status
from custom_utils import handle_supply
from micro import micro
from macro import macro
from production import produce
from speedmining import split_workers
from speedmining import get_speedmining_positions
from speedmining import micro_structure
from speedmining import micro_worker
from speedmining import handle_refineries

from typing import Dict, Iterable, List, Optional, Set
from itertools import chain

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.position import Point2


# bot code --------------------------------------------------------------------------------------------------------
class SmoothBrainFlat48(BotAI):
    def __init__(self):
        self.unit_command_uses_self_do = False
        self.distance_calculation_method = 2
        self.worker_rushed = False
        self.game_step: int = 2
        self.tags: Set[str] = set()
        self.attack_with_all_worker = False
        self.scouting_units = []
        self.worker_assigned_to_repair = {}
        self.worker_assigned_to_follow = {}
        self.worker_assigned_to_defend = {}
        self.scouted_at_time = -1000
        super().__init__()


    async def on_before_start(self) -> None:
        self.client.game_step = self.game_step
        self.client.raw_affects_selection = True
        top_right = Point2((self.game_info.playable_area.right, self.game_info.playable_area.top))
        bottom_right = Point2((self.game_info.playable_area.right, 0))
        bottom_left = Point2((0, 0))
        top_left = Point2((0, self.game_info.playable_area.top))
        self.map_corners = [top_right, bottom_right, bottom_left, top_left]


    async def on_start(self) -> None:
        self.client.game_step = self.game_step
        self.speedmining_positions = get_speedmining_positions(self)
        split_workers(self)


    async def on_step(self, iteration: int):

        if self.townhalls.amount == 0 or self.supply_used == 0:
            await self.client.leave()
            return

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
        await handle_supply(self)
        produce(self)
        await macro(self)
        build_worker(self)
        await micro(self)
