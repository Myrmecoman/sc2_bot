import time

from bot.custom_utils import land_structures_for_addons
from bot.custom_utils import build_worker
from bot.custom_utils import handle_add_ons
from bot.custom_utils import handle_depot_status
from bot.custom_utils import handle_upgrades
from bot.custom_utils import handle_supply
from bot.custom_utils import handle_command_centers
from bot.build_order import early_build_order
from bot.micro import micro
from bot.macro import macro
from bot.production import produce
from bot.speedmining import split_workers
from bot.speedmining import get_speedmining_positions
from bot.speedmining import micro_worker
from bot.speedmining import handle_refineries
from bot.speedmining import dispatch_workers
from bot.army_composition_advisor import ArmyCompositionAdvisor

from itertools import chain

from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.data import Race
from sc2.unit import Unit
from bot.pathing.pathing import Pathing
from bot.pathing.reapers import Reapers
from bot.pathing.consts import ATTACK_TARGET_IGNORE


# bot code --------------------------------------------------------------------------------------------------------
class SmoothBrainBot(BotAI):

    pathing: Pathing
    # use a separate class for all reaper control
    reapers: Reapers

    def __init__(self):
        self.unit_command_uses_self_do = False
        self.distance_calculation_method = 2
        self.game_step: int = 2
        self.build_starport_techlab_first = False # against zerg, we better make a quick raven to counter burrowed roach all-ins
        self.worker_rushed = False                # tells if we are worker rushed
        self.attack_with_all_worker = False       # in case of worker rushes
        self.scouting_units = []                  # lists units assigned to scout so that we do not cancel their orders
        self.worker_assigned_to_repair = {}       # lists workers assigned to repair
        self.worker_assigned_to_follow = {}       # lists workers assigned to follow objects (used to prevent Planetary Fortress rushes)
        self.worker_assigned_to_defend = {}       # lists workers assigned to defend other workers during construction
        self.worker_assigned_to_expand = {}       # lists workers assigned to expand /!\ not used yet
        self.townhall_saturations = {}            # lists the mineral saturation of townhalls in queues of 40 frames, we consider the townhall saturated if max_number + 1 >= ideal_number
        self.produce_from_starports = True
        self.produce_from_factories = True
        self.produce_from_barracks = True
        self.scouted_at_time = -1000              # save moment at which we scouted, so that we don't re-send units every frame
        
        self.build_order = [UnitTypeId.SUPPLYDEPOT, UnitTypeId.BARRACKS, UnitTypeId.REFINERY, UnitTypeId.ORBITALCOMMAND, UnitTypeId.COMMANDCENTER, UnitTypeId.SUPPLYDEPOT, UnitTypeId.FACTORY]

        super().__init__()


    async def on_before_start(self) -> None:
        
        #if self.enemy_race == Race.Terran:
        #    self.build_order = [UnitTypeId.SUPPLYDEPOT, UnitTypeId.REFINERY, UnitTypeId.BARRACKS, UnitTypeId.REFINERY, UnitTypeId.ORBITALCOMMAND, UnitTypeId.FACTORY, UnitTypeId.SUPPLYDEPOT, UnitTypeId.COMMANDCENTER]

        self.client.game_step = self.game_step
        self.client.raw_affects_selection = True
        top_right = Point2((self.game_info.playable_area.right, self.game_info.playable_area.top))
        bottom_right = Point2((self.game_info.playable_area.right, 0))
        bottom_left = Point2((0, 0))
        top_left = Point2((0, self.game_info.playable_area.top))
        self.map_corners = [top_right, bottom_right, bottom_left, top_left]


    async def on_start(self) -> None:
        if self.enemy_race == Race.Zerg:
            self.build_starport_techlab_first = True
        self.client.game_step = self.game_step
        self.army_advisor = ArmyCompositionAdvisor(self)         # provides advices for army composition and building add ons
        self.army_advisor.provide_advices_startup()
        self.speedmining_positions = get_speedmining_positions(self)
        split_workers(self)
        self.pathing = Pathing(self, False)
        self.reapers = Reapers(self, self.pathing)
    

    async def on_unit_destroyed(self, unit_tag: int):
        self.army_advisor.remove_unit(unit_tag)
        self.army_advisor.track_resource_losses(unit_tag)
    

    async def on_step(self, iteration: int):

        if self.townhalls.amount == 0 or self.supply_used == 0:
            await self.client.leave()
            return

        self.pathing.update()
        self.army_advisor.provide_advices()
        self.resource_by_tag = {unit.tag: unit for unit in chain(self.mineral_field, self.gas_buildings)}

        dispatch_workers(self)
        micro_worker(self)
        handle_refineries(self)
        #await self.distribute_workers(0)

        handle_depot_status(self)
        handle_command_centers(self)
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
        handle_upgrades(self)
        await micro(self)