import time

from bot.custom_utils import land_structures_for_addons
from bot.custom_utils import build_worker
from bot.custom_utils import handle_add_ons
from bot.custom_utils import handle_depot_status
from bot.custom_utils import handle_upgrades
from bot.custom_utils import handle_supply
from bot.custom_utils import handle_command_centers
from bot.custom_utils import get_rally_point
from bot.custom_utils import update_rally_points
from bot.build_order import early_build_order
from bot.micro import micro
from bot.macro import macro
from bot.production import produce
from bot.speedmining import split_workers
from bot.speedmining import get_speedmining_positions
from bot.speedmining import mine
from bot.army_composition_advisor import ArmyCompositionAdvisor
from bot.worker_rush_defense import worker_rush_defense
from bot.scouting import scout

from itertools import chain

from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
from sc2.data import Race
from sc2.unit import Unit
from bot.pathing.pathing import Pathing
from bot.pathing.pathing_fallback import Pathing as PathingFallback
from bot.pathing.reapers import Reapers
from bot.pathing.bio import Bio
from bot.pathing.medivacs import Medivacs
from bot.pathing.ravens import Ravens
from bot.pathing.flying_vikings import FlyingVikings
from bot.pathing.banshees import Banshees
from bot.pathing.tanks import Tanks
from bot.pathing.cyclones import Cyclones
from bot.pathing.liberators import Liberators


# bot code --------------------------------------------------------------------------------------------------------
class SmoothBrainBot(BotAI):

    pathing: Pathing
    # use a separate class for all units control
    reapers: Reapers
    bio: Bio
    medivacs: Medivacs
    ravens: Ravens
    flying_vikings: FlyingVikings
    banshees: Banshees
    tanks: Tanks
    cyclones: Cyclones

    def __init__(self):
        self.unit_command_uses_self_do = False
        self.distance_calculation_method = 2
        self.game_step: int = 2                      # 2 usually, 6 vs human
        self.build_starport_techlab_first = True     # always make techlab first on starport, good against dts, skytoss, burrowed roaches, and siege tanks
        self.worker_rushed = False                   # tells if we are worker rushed, if the enemies were repelled we should close the wall quick before they come back
        self.worker_rush_clear_since = None           # timestamp since the worker rush threat has been gone, used to eventually stand down
        self.scouting_units = []                     # lists units assigned to scout so that we do not cancel their orders
        self.worker_assigned_to_repair = {}          # lists workers assigned to repair
        self.worker_assigned_to_repair_mech = {}     # lists workers assigned to repair damaged mechanical army units
        self.worker_assigned_to_follow = {}          # lists workers assigned to follow objects (used to prevent Planetary Fortress rushes)
        self.worker_assigned_to_defend = {}          # lists workers assigned to defend other workers during construction
        self.worker_assigned_to_resume_building = {} # lists workers assigned to resume the construction of a building
        self.worker_assigned_to_expand = {}          # lists workers assigned to expand /!\ not used yet
        self.townhall_saturations = {}               # lists the mineral saturation of townhalls in queues of 40 frames, we consider the townhall saturated if max_number + 1 >= ideal_number
        self.refineries_age = {}                     # this is here to tackle an issue with refineries having 0 workers on them when finished, although the building worker is assigned to it
        self.lifted_cc_pos = {}                      # remember where lifted ccs were
        self.produce_from_starports = True
        self.produce_from_factories = True
        self.produce_from_barracks = True
        self.scouted_at_time = -1000                 # save moment at which we scouted, so that we don't re-send units every frame
        self.scouting_bases_until = 0.0               # while self.time is under this, tags in scouting_unit_tags are excluded from the normal army handle_attackers/retreat_to dispatch so a just-launched go_scout_bases sweep isn't immediately called back in
        self.scouting_unit_tags = set()               # tags go_scout_bases last dispatched - see scouting_bases_until
        self.factory_prioritized = False              # tracks whether we've already moved the factory earlier in the build order this game
        self.rally_point = None                        # last Point2 our production rally points were set to (see update_rally_points)
        self.base_build_order = []                     # tags of Command Centers built from scratch, in completion order - used to find our newest base for rally-point defense (see get_defend_point)
        self.scout_worker_tag = None                  # tag of the worker currently on the early scouting run, if any
        self.enemy_base_scouted = False                # whether we've gotten vision of the enemy's main at least once
        self.scout_attempted = False                   # only ever send one scouting worker per game
        self.army_attacking = False                    # sticky: are we currently committed to attacking (see micro.py)
        self.build_order_critical_worker = None        # tag of the worker currently committed to the scripted build order, if any - kept safe from flee_worker_threats so the two don't fight over it
        self.gas_bank_high = False                      # sticky: are we currently sitting on so much banked vespene that building more refineries is pointless (see macro.py)

        self.build_order = [UnitTypeId.SUPPLYDEPOT, UnitTypeId.BARRACKS, UnitTypeId.REFINERY, UnitTypeId.ORBITALCOMMAND, UnitTypeId.COMMANDCENTER, UnitTypeId.SUPPLYDEPOT, UnitTypeId.FACTORY]

        super().__init__()


    async def on_before_start(self) -> None:

        self.client.game_step = self.game_step
        self.client.raw_affects_selection = True
        top_right = Point2((self.game_info.playable_area.right, self.game_info.playable_area.top))
        bottom_right = Point2((self.game_info.playable_area.right, self.game_info.playable_area.y))
        bottom_left = Point2((self.game_info.playable_area.x, self.game_info.playable_area.y))
        top_left = Point2((self.game_info.playable_area.x, self.game_info.playable_area.top))
        self.map_corners = [top_right, bottom_right, bottom_left, top_left]


    # set rally point at start location, therefore our units will spawn on the right side of the wall
    async def on_building_construction_started(self, unit: Unit):
        if unit.type_id == UnitTypeId.BARRACKS or unit.type_id == UnitTypeId.FACTORY or unit.type_id == UnitTypeId.STARPORT:
            unit(AbilityId.SMART, get_rally_point(self))


    async def on_building_construction_complete(self, unit: Unit):
        # only from-scratch Command Centers append here - the starting base was never "built" (no
        # construction event for it) and an Orbital Command upgrade is a morph of the same tag, not
        # a new structure, so neither shows up here. That's exactly what we want: this tracks
        # expansions specifically, oldest to newest
        if unit.type_id == UnitTypeId.COMMANDCENTER:
            self.base_build_order.append(unit.tag)


    async def on_start(self) -> None:

        await self._client.chat_send("glhf!", team_only=False)

        self.client.game_step = self.game_step
        self.army_advisor = ArmyCompositionAdvisor(self) # provides advices for army composition and building add ons
        self.army_advisor.provide_advices_startup()
        self.speedmining_positions = get_speedmining_positions(self)
        split_workers(self)

        try:
            self.pathing = Pathing(self, False)
        except Exception as e:
            # map_analyzer's compiled C extension isn't usable on this machine (missing/wrong
            # platform/ABI-mismatched .so are all failures that have happened before on AI Arena's
            # servers) - fall back to the pure-Python implementation rather than forfeit the game
            print(f"[PATHING] map_analyzer unavailable ({e!r}), using pure-Python pathing fallback")
            self.pathing = PathingFallback(self, False)
        self.reapers = Reapers(self, self.pathing)
        self.bio = Bio(self, self.pathing)
        self.medivacs = Medivacs(self, self.pathing)
        self.ravens = Ravens(self, self.pathing)
        self.flying_vikings = FlyingVikings(self, self.pathing)
        self.banshees = Banshees(self, self.pathing)
        self.tanks = Tanks(self, self.pathing)
        self.cyclones = Cyclones(self, self.pathing)
        self.liberators = Liberators(self, self.pathing)
    

    async def on_unit_destroyed(self, unit_tag: int):
        self.army_advisor.remove_unit(unit_tag)
        self.army_advisor.track_resource_losses(unit_tag)
    

    async def on_step(self, iteration: int):
        if self.townhalls.amount == 0 or self.supply_used == 0:
            await self._client.chat_send("gg", team_only=False)
            await self.client.leave()
            return

        self.pathing.update()
        self.army_advisor.provide_advices()
        self.resource_by_tag = {unit.tag: unit for unit in chain(self.mineral_field, self.gas_buildings)}

        worker_rush_defense(self)
        await scout(self)
        mine(self, iteration)

        handle_depot_status(self)
        await handle_command_centers(self)
        await handle_supply(self)

        if not self.worker_rushed:
            await early_build_order(self)

        await macro(self)
        build_worker(self)
        land_structures_for_addons(self)
        handle_add_ons(self)
        produce(self)
        handle_upgrades(self)
        await micro(self)
