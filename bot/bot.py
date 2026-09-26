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
from bot.worker_micro import worker_micro
from bot.ares_compat import Sc2Bridge
from bot.army.manager import ArmyManager
from bot.macro import macro
from bot.production import produce
from bot.speedmining import split_workers
from bot.speedmining import get_speedmining_positions
from bot.speedmining import mine
from bot.army_composition_advisor import ArmyCompositionAdvisor
from bot.worker_rush_defense import worker_rush_defense
from bot.scouting import scout

from itertools import chain

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
from sc2.data import Race
from sc2.unit import Unit
from sc2.units import Units

# Ares (roles, squads, influence grids, pathing, combat simulator, behaviors) drives the whole army and is required: if it
# cannot be imported (wrong Python, missing compiled extension) the bot does not start.
from ares import AresBot
from ares.consts import UNIT_TYPES_WITH_NO_ROLE


# bot code --------------------------------------------------------------------------------------------------------
class SmoothBrainBot(Sc2Bridge, AresBot):

    army: ArmyManager

    def __init__(self):
        self.unit_command_uses_self_do = False
        self.distance_calculation_method = 2
        self.game_step: int = 2                      # 2 usually, 6 vs human
        self.build_starport_techlab_first = True    # always make techlab first on starport, good against dts, skytoss, burrowed roaches, and siege tanks
        self.worker_rushed = False                   # tells if we are worker rushed, if the enemies were repelled we should close the wall quick before they come back
        self.worker_rush_clear_since = None           # timestamp since the worker rush threat has been gone, used to eventually stand down
        self.scouting_units = []                     # lists units assigned to scout so that we do not cancel their orders
        self.repair_jobs = {}                        # SCV tag -> the repair job it was sent on (see repair.py)
        self.repair_walks = {}                       # (SCV tag, target tag) -> (when measured, length of the ground walk there)
        self.repair_backoff = {}                     # target tag -> until when nobody is looked for to repair it
        self.turret_backoff = {}                     # townhall tag -> until when no turret is tried for its mineral line again (see macro.build_turrets)
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
        self.factory_prioritized = False              # tracks whether we've already moved the factory earlier in the build order this game
        self.rally_point = None                        # last Point2 our production rally points were set to (see update_rally_points)
        self.base_build_order = []                     # tags of Command Centers built from scratch, in completion order - used to find our newest base for rally-point defense (see get_defend_point)
        self.scout_worker_tag = None                  # tag of the worker currently on the early scouting run, if any
        self.enemy_base_scouted = False                # whether we've gotten vision of the enemy's main at least once
        self.scout_attempted = False                   # only ever send one scouting worker per game
        self.build_order_critical_worker = None        # tag of the worker currently committed to the scripted build order, if any - kept safe from flee_worker_threats so the two don't fight over it
        self.gas_bank_high = False                      # sticky: are we currently sitting on so much banked vespene that building more refineries is pointless (see macro.py)

        self.build_order = [UnitTypeId.SUPPLYDEPOT, UnitTypeId.BARRACKS, UnitTypeId.REFINERY, UnitTypeId.ORBITALCOMMAND, UnitTypeId.COMMANDCENTER, UnitTypeId.SUPPLYDEPOT, UnitTypeId.FACTORY]

        self.army = None
        self._visible_enemies_loop = -1
        self._visible_enemies = None

        # our own worker code manages every SCV - keep Ares from also assigning them roles and tracking their mining
        UNIT_TYPES_WITH_NO_ROLE.add(UnitTypeId.SCV)

        super().__init__()


    @property
    def visible_enemy_units(self) -> Units:
        """Enemy units observed THIS frame. Ares merges its 30-second memory of enemy units that have since left
        vision into `enemy_units`; macro-side code (worker rush detection, wall depots, expansion safety, ...) means
        "what can I see right now" and must not react to those remembered ghosts."""
        loop = self.state.game_loop
        if self._visible_enemies_loop != loop or self._visible_enemies is None:
            self._visible_enemies = self.enemy_units.filter(lambda u: not u.is_memory)
            self._visible_enemies_loop = loop
        return self._visible_enemies


    def is_unit_position_safe(self, unit: Unit) -> bool:
        """Is this unit standing outside every known enemy threat range? (Ares influence grids)"""
        grid = self.mediator.get_air_grid if unit.is_flying else self.mediator.get_ground_grid
        return self.mediator.is_position_safe(grid=grid, position=unit.position)


    async def on_before_start(self) -> None:
        await super().on_before_start()         # Ares: race-specific types, expansion fixes

        self.client.game_step = self.game_step
        self.client.raw_affects_selection = True
        top_right = Point2((self.game_info.playable_area.right, self.game_info.playable_area.top))
        bottom_right = Point2((self.game_info.playable_area.right, self.game_info.playable_area.y))
        bottom_left = Point2((self.game_info.playable_area.x, self.game_info.playable_area.y))
        top_left = Point2((self.game_info.playable_area.x, self.game_info.playable_area.top))
        self.map_corners = [top_right, bottom_right, bottom_left, top_left]


    # set rally point at start location, therefore our units will spawn on the right side of the wall
    async def on_building_construction_started(self, unit: Unit):
        await super().on_building_construction_started(unit)
        if unit.type_id == UnitTypeId.BARRACKS or unit.type_id == UnitTypeId.FACTORY or unit.type_id == UnitTypeId.STARPORT:
            unit(AbilityId.SMART, get_rally_point(self))


    async def on_building_construction_complete(self, unit: Unit):
        await super().on_building_construction_complete(unit)
        # only from-scratch Command Centers append here - the starting base was never "built" (no
        # construction event for it) and an Orbital Command upgrade is a morph of the same tag, not
        # a new structure, so neither shows up here. That's exactly what we want: this tracks
        # expansions specifically, oldest to newest
        if unit.type_id == UnitTypeId.COMMANDCENTER:
            self.base_build_order.append(unit.tag)


    async def on_start(self) -> None:
        await super().on_start()                # Ares: game step, managers (grids, terrain, memory, squads, ...)
        # Ares can run an opening build order from a config file; there is none here (our own build order code
        # handles the opening), so mark it finished so it never touches our workers
        self.build_order_runner.set_build_completed()

        await self.client.chat_send("glhf!", team_only=False)

        self.client.game_step = self.game_step
        self.army_advisor = ArmyCompositionAdvisor(self) # provides advices for army composition and building add ons
        self.army_advisor.provide_advices_startup()
        self.speedmining_positions = get_speedmining_positions(self)
        split_workers(self)

        self.army = ArmyManager(self)


    async def on_unit_destroyed(self, unit_tag: int):
        await super().on_unit_destroyed(unit_tag)
        self.army_advisor.remove_unit(unit_tag)
        self.army_advisor.track_resource_losses(unit_tag)
        self.army.on_unit_destroyed(unit_tag)


    async def on_step(self, iteration: int):
        if self.townhalls.amount == 0 or self.supply_used == 0:
            await self.client.chat_send("gg", team_only=False)
            await self.client.leave()
            return

        await super().on_step(iteration)        # Ares: update managers - must come first, everything below reads their data

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

        worker_micro(self)
        await self.army.update(iteration)
