"""Dynamic integration harness: drive the REAL SmoothBrainBot (real Ares hub + managers + MapData, the vendored sc2
lifecycle) through start-up and a number of frames using a synthetic map and synthetic observations. No SC2 client."""
import asyncio
import math
from types import SimpleNamespace

import numpy as np
from s2clientprotocol import common_pb2, data_pb2, raw_pb2, sc2api_pb2 as sc_pb

from sc2.game_data import GameData
from sc2.game_info import GameInfo
from sc2.game_state import GameState
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

import gamefix

W = H = 128


# ------------------------------------------------------------------------------------------------------------------
# game data: every unit type / ability / upgrade the enums know, with real stats where gamefix has them
# ------------------------------------------------------------------------------------------------------------------
def make_game_data():
    from sc2.ids.upgrade_id import UpgradeId
    data = gamefix.make_response_data()          # abilities for all AbilityId + STATS units
    have = {u.unit_id for u in data.units}
    for type_id in U:
        if type_id.value == 0 or type_id.value in have:
            continue
        u = data_pb2.UnitTypeData()
        u.unit_id = type_id.value
        u.name = type_id.name
        u.available = True
        u.food_required = 0
        u.movement_speed = 3.15
        u.build_time = 400
        data.units.append(u)
    # resource / structure special cases the bot code checks
    for u in data.units:
        if u.unit_id in (U.MINERALFIELD.value, U.MINERALFIELD750.value, U.RICHMINERALFIELD.value):
            u.has_minerals = True
        if u.unit_id in (U.VESPENEGEYSER.value, U.RICHVESPENEGEYSER.value, U.REFINERY.value):
            u.has_vespene = True
        if u.unit_id in (U.COMMANDCENTER.value, U.ORBITALCOMMAND.value, U.SUPPLYDEPOT.value, U.SUPPLYDEPOTLOWERED.value,
                         U.BARRACKS.value, U.FACTORY.value, U.STARPORT.value, U.REFINERY.value, U.ENGINEERINGBAY.value,
                         U.ARMORY.value, U.BARRACKSREACTOR.value, U.BARRACKSTECHLAB.value, U.BUNKER.value,
                         U.MISSILETURRET.value, U.SENSORTOWER.value, U.PLANETARYFORTRESS.value):
            if gamefix.STRUCT not in list(u.attributes):
                u.attributes.append(gamefix.STRUCT)
    # creation abilities (python-sc2 needs them to place / train anything) + building footprints
    from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
    abilities = {a.ability_id: a for a in data.abilities}
    units_by_id = {u.unit_id: u for u in data.units}
    footprint = {U.COMMANDCENTER: 2.5, U.SUPPLYDEPOT: 1.0, U.BARRACKS: 1.5, U.FACTORY: 1.5, U.STARPORT: 1.5,
                 U.REFINERY: 1.5, U.ENGINEERINGBAY: 1.5, U.ARMORY: 1.5, U.BUNKER: 1.5, U.MISSILETURRET: 1.0,
                 U.SENSORTOWER: 0.5, U.PLANETARYFORTRESS: 2.5, U.ORBITALCOMMAND: 2.5}
    for producer, table in TRAIN_INFO.items():
        for unit_type, info in table.items():
            ability = info.get("ability")
            unit = units_by_id.get(unit_type.value)
            if ability is None or unit is None or ability.value not in abilities:
                continue
            unit.ability_id = ability.value
            if unit_type in footprint:
                abilities[ability.value].footprint_radius = footprint[unit_type]
                abilities[ability.value].is_building = True
    # add-ons are built by an ability of their own, which TRAIN_INFO does not list (the real game data has it)
    for unit_type, ability in ((U.BARRACKSREACTOR, AbilityId.BUILD_REACTOR_BARRACKS), (U.BARRACKSTECHLAB, AbilityId.BUILD_TECHLAB_BARRACKS),
                               (U.FACTORYREACTOR, AbilityId.BUILD_REACTOR_FACTORY), (U.FACTORYTECHLAB, AbilityId.BUILD_TECHLAB_FACTORY),
                               (U.STARPORTREACTOR, AbilityId.BUILD_REACTOR_STARPORT), (U.STARPORTTECHLAB, AbilityId.BUILD_TECHLAB_STARPORT)):
        if unit_type.value in units_by_id and ability.value in abilities:
            units_by_id[unit_type.value].ability_id = ability.value
    from sc2.dicts.unit_research_abilities import RESEARCH_INFO
    research = {}
    for producer, table in RESEARCH_INFO.items():
        for upgrade, info in table.items():
            if info.get("ability") is not None:
                research[upgrade] = info["ability"]
    data.upgrades = []
    for up in UpgradeId:
        if up.value == 0:
            continue
        p = data_pb2.UpgradeData()
        p.upgrade_id = up.value
        p.name = up.name
        if up in research and research[up].value in abilities:
            p.ability_id = research[up].value
        p.mineral_cost, p.vespene_cost, p.research_time = 100, 100, 100
        data.upgrades.append(p)
    return data


# ------------------------------------------------------------------------------------------------------------------
# synthetic map
# ------------------------------------------------------------------------------------------------------------------
def _image(arr, bits):
    img = common_pb2.ImageData()
    img.bits_per_pixel = bits
    img.size.x, img.size.y = arr.shape[1], arr.shape[0]
    img.data = np.packbits(arr.astype(np.uint8).ravel()).tobytes() if bits == 1 else arr.astype(np.uint8).tobytes()
    return img


RAMP_TILES = {   # (x, y) offsets from the ramp origin -> height: a standard diagonal ramp with exactly two upper points
    130: [(0, 1), (1, 0)],
    125: [(1, 1), (0, 2), (2, 0)],
    120: [(2, 1), (1, 2), (3, 0), (0, 3)],
    115: [(2, 2), (3, 1), (1, 3), (4, 0), (0, 4)],
    110: [(3, 2), (2, 3), (4, 1), (1, 4)],
    105: [(3, 3), (4, 2), (2, 4)],
}


def make_map():
    pathing = np.zeros((H, W), dtype=np.uint8)
    pathing[8:H - 8, 8:W - 8] = 1
    # a vertical wall with a wide gap splits the map into two halves joined by a choke
    pathing[8:H - 8, 62:66] = 0
    pathing[54:74, 62:66] = 1
    placement = pathing.copy()
    placement[:, 60:68] = 0
    height = np.full((H, W), 100, dtype=np.uint8)
    height[8:H - 8, 62:66] = 110
    # main-base plateaus (our lower-left, theirs upper-right) with a ramp each, going down towards the map centre
    height[8:32, 8:32] = 130
    height[H - 32:H - 8, W - 32:W - 8] = 130
    for (ox, oy, sign) in ((30, 30, 1), (W - 1 - 30 - 4, H - 1 - 30 - 4, -1)):
        for h, offs in RAMP_TILES.items():
            for (dx, dy) in offs:
                x, y = (ox + dx, oy + dy) if sign == 1 else (ox + 4 - dx, oy + 4 - dy)
                height[y, x] = h
                placement[y, x] = 0
                pathing[y, x] = 1
    return pathing, placement, height


BASES = {
    "our_main": (24.5, 24.5), "our_nat": (44.5, 36.5), "our_third": (24.5, 60.5),
    "enemy_main": (103.5, 103.5), "enemy_nat": (83.5, 91.5), "enemy_third": (103.5, 67.5),
}


def resource_ring(cx, cy, count=8, radius=7.0):
    pts = []
    for i in range(count):
        ang = math.pi * (0.55 + 0.9 * i / max(1, count - 1))       # an arc on the far side of the base
        pts.append((cx + radius * math.cos(ang) + 0.5, cy + radius * math.sin(ang) + 0.5))
    return pts


class SyntheticGame:
    def __init__(self, enemy_race=None):
        self.enemy_race = enemy_race if enemy_race is not None else common_pb2.Zerg
        self.pathing, self.placement, self.height = make_map()
        self.units_raw = []          # raw proto units for the current frame
        self.next_tag = 100
        self.game_loop = 8
        self.minerals = 400
        self.vespene = 0
        self.dead = []

    # -- proto construction --------------------------------------------------------------------------------------
    def game_info_proto(self):
        gi = sc_pb.ResponseGameInfo()
        gi.map_name = "Synthetic Test Map"
        gi.local_map_path = "synthetic.SC2Map"
        for pid, race in ((1, common_pb2.Terran), (2, self.enemy_race)):
            p = gi.player_info.add()
            p.player_id = pid
            p.type = sc_pb.Participant
            p.race_requested = race
            p.race_actual = race
        sr = gi.start_raw
        sr.map_size.x, sr.map_size.y = W, H
        sr.pathing_grid.CopyFrom(_image(self.pathing, 1))
        sr.terrain_height.CopyFrom(_image(self.height, 8))
        sr.placement_grid.CopyFrom(_image(self.placement, 1))
        sr.playable_area.p0.x, sr.playable_area.p0.y = 8, 8
        sr.playable_area.p1.x, sr.playable_area.p1.y = W - 8, H - 8
        # like the real API, start_raw.start_locations lists only the OPPONENT's possible start locations
        for name in ("enemy_main",):
            loc = sr.start_locations.add()
            loc.x, loc.y = BASES[name]
        return SimpleNamespace(game_info=gi)     # what _prepare_step reads: proto_game_info.game_info.start_raw...

    def unit_proto(self, type_id, pos, alliance, hp=None, tag=None, **kw):
        stats = gamefix.STATS.get(type_id)
        hp0 = stats[0] if stats else 100
        sh0 = stats[1] if stats else 0
        p = raw_pb2.Unit()
        p.display_type = 1
        p.alliance = alliance
        p.tag = tag if tag is not None else self._tag()
        p.unit_type = type_id.value
        p.owner = {1: 1, 4: 2, 3: 16}[alliance]
        p.pos.x, p.pos.y, p.pos.z = pos[0], pos[1], 10.0
        p.radius = gamefix.RADIUS.get(type_id, 0.5 if type_id in (U.COMMANDCENTER,) else 0.375)
        p.build_progress = kw.get("build_progress", 1.0)
        p.health = hp0 if hp is None else hp
        p.health_max = hp0
        p.shield = sh0
        p.shield_max = sh0
        p.energy = kw.get("energy", 0.0)
        p.energy_max = 200
        p.cloak = 3
        p.is_flying = (type_id in gamefix.FLYING_TYPES)
        p.weapon_cooldown = kw.get("cooldown", 0.0)
        p.is_powered = True
        if "mineral_contents" in kw:
            p.mineral_contents = kw["mineral_contents"]
        if "vespene_contents" in kw:
            p.vespene_contents = kw["vespene_contents"]
        return p

    def _tag(self):
        self.next_tag += 1
        return self.next_tag

    def add(self, type_id, pos, alliance=1, **kw):
        p = self.unit_proto(type_id, pos, alliance, **kw)
        self.units_raw.append(p)
        return p

    def add_base_resources(self, base_name):
        cx, cy = BASES[base_name]
        for (x, y) in resource_ring(cx, cy, 8):
            self.add(U.MINERALFIELD, (x, y), 3, mineral_contents=1800)
        for k, (x, y) in enumerate(((cx - 7.5, cy + 0.5), (cx + 1.5, cy + 7.5))):
            self.add(U.VESPENEGEYSER, (x, y), 3, vespene_contents=2250)

    def state(self, supply_used=20, supply_cap=23, upgrades=()):
        obs = sc_pb.ResponseObservation()
        o = obs.observation
        o.game_loop = self.game_loop
        pc = o.player_common
        pc.player_id = 1
        pc.minerals = self.minerals
        pc.vespene = self.vespene
        pc.food_cap = supply_cap
        pc.food_used = supply_used
        pc.food_army = max(0, supply_used - 12)
        pc.food_workers = 12
        pc.army_count = 5
        rd = o.raw_data
        for up in upgrades:
            rd.player.upgrade_ids.append(up.value)
        vis = np.full((H, W), 2, dtype=np.uint8)
        rd.map_state.visibility.CopyFrom(_image(vis, 8))
        rd.map_state.creep.CopyFrom(_image(np.zeros((H, W), dtype=np.uint8), 1))
        for u in self.units_raw:
            rd.units.add().CopyFrom(u)
        for tag in self.dead:
            rd.event.dead_units.append(tag)
        return GameState(obs)


# ------------------------------------------------------------------------------------------------------------------
# client fake
# ------------------------------------------------------------------------------------------------------------------
GRANTED_ABILITIES = {
    U.REAPER: [AbilityId.KD8CHARGE_KD8CHARGE],
    U.BANSHEE: [AbilityId.BEHAVIOR_CLOAKON_BANSHEE, AbilityId.BEHAVIOR_CLOAKOFF_BANSHEE],
    U.MEDIVAC: [AbilityId.EFFECT_MEDIVACIGNITEAFTERBURNERS],
    U.RAVEN: [AbilityId.EFFECT_INTERFERENCEMATRIX, AbilityId.BUILDAUTOTURRET_AUTOTURRET],
    U.CYCLONE: [AbilityId.LOCKON_LOCKON, AbilityId.LOCKONAIR_LOCKONAIR],
    U.LIBERATOR: [AbilityId.MORPH_LIBERATORAGMODE],
    U.LIBERATORAG: [AbilityId.MORPH_LIBERATORAAMODE],
}


class FakeClient:
    def __init__(self):
        self.game_step = 2
        self.raw_affects_selection = False
        self.sent_actions = []
        self.raw_actions = []
        self.chat = []
        self._game_result = {}

    async def chat_send(self, message, team_only=False):
        self.chat.append(message)

    async def leave(self):
        self.chat.append("<leave>")

    async def actions(self, actions):
        acts = actions if isinstance(actions, list) else [actions]
        self.sent_actions.extend(acts)
        return [0] * len(acts)

    async def _send_debug(self):
        return None

    async def _execute(self, **kwargs):
        self.raw_actions.append(kwargs)
        return SimpleNamespace(action=SimpleNamespace(result=[]))

    async def query_available_abilities(self, units, ignore_resource_requirements=False):
        # what the game says each unit can use right now (the real API only lists what is off cooldown / researched; here every
        # ability the army code touches is always available, so the ability-dependent Ares behaviors actually run)
        return [list(GRANTED_ABILITIES.get(u.type_id, ())) for u in units]

    async def query_building_placement(self, *a, **k):
        return [0]

    async def _query_building_placement_fast(self, building, positions, *a, **k):
        return [True] * len(positions)

    async def query_pathing(self, *a, **k):
        return 10.0

    async def query_pathings(self, zipped_list):
        return [10.0 for _ in zipped_list]

    def debug_text_world(self, *a, **k):
        pass

    def __getattr__(self, name):
        if name.startswith("debug"):
            return lambda *a, **k: None
        raise AttributeError(name)


def _patch_bot_class(bot_cls):
    """Nothing to patch any more: the synthetic map now contains real ramps."""
    return None


async def start_game(game: SyntheticGame, bot):
    """Run the same start-up sequence sc2.main._play_game_ai does."""
    client = FakeClient()
    bot._initialize_variables()          # sc2.main._play_game_ai does this first
    game_data = GameData(make_game_data())
    proto_gi = game.game_info_proto()
    game_info = GameInfo(proto_gi.game_info)
    bot._prepare_start(client, 1, game_info, game_data, realtime=False, base_build=90000)
    bot._distances_override_functions(bot.distance_calculation_method)
    gs = game.state()
    bot._prepare_step(gs, proto_gi)
    await bot.on_before_start()
    bot._prepare_first_step()
    await bot.on_start()
    return client, proto_gi


async def run_frame(game: SyntheticGame, bot, proto_gi, iteration, frames=2, **state_kw):
    game.game_loop += frames
    gs = game.state(**state_kw)
    bot._prepare_step(gs, proto_gi)
    await bot.issue_events()
    await bot.on_step(iteration)
    await bot._after_step()
