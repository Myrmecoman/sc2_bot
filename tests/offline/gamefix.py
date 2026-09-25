"""Offline test fixture: real sc2.unit.Unit objects backed by a hand-built GameData (no SC2 client).

Stats are approximate LotV values - good enough to exercise logic + the Rust combat sim, NOT for balance work.
"""
import itertools
from types import SimpleNamespace

from s2clientprotocol import data_pb2, raw_pb2, common_pb2

from sc2.bot_ai import BotAI
from sc2.game_data import GameData
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

GROUND, AIR, ANY = 1, 2, 3
LIGHT, ARMORED, BIO, MECH, ROBOTIC, PSI, MASSIVE, STRUCT = 1, 2, 3, 4, 5, 6, 7, 8

# type: (hp, shield, armor, speed, [weapons (kind, dmg, attacks, range, cooldown, bonus[(attr, val)])], attrs, mineral, gas, supply)
STATS = {
    U.MARINE: (45, 0, 0, 3.15, [(ANY, 6, 1, 5, 0.61, [])], [LIGHT, BIO], 50, 0, 1),
    U.MARAUDER: (125, 0, 1, 3.15, [(GROUND, 10, 1, 6, 1.07, [(ARMORED, 10)])], [ARMORED, BIO], 100, 25, 2),
    U.REAPER: (60, 0, 0, 5.25, [(GROUND, 4, 2, 5, 0.79, [])], [LIGHT, BIO], 50, 50, 1),
    U.HELLION: (90, 0, 0, 5.95, [(GROUND, 8, 1, 5, 1.79, [(LIGHT, 6)])], [LIGHT, MECH], 100, 0, 2),
    U.SIEGETANK: (175, 0, 1, 3.15, [(GROUND, 15, 1, 7, 0.74, [(ARMORED, 10)])], [ARMORED, MECH], 150, 125, 3),
    U.SIEGETANKSIEGED: (175, 0, 1, 0.0, [(GROUND, 40, 1, 13, 2.14, [(ARMORED, 30)])], [ARMORED, MECH], 150, 125, 3),
    U.CYCLONE: (180, 0, 1, 4.13, [(ANY, 18, 1, 5, 0.71, [])], [ARMORED, MECH], 150, 100, 3),
    U.MEDIVAC: (150, 0, 1, 3.5, [], [ARMORED, MECH], 100, 100, 2),
    U.VIKINGFIGHTER: (135, 0, 0, 3.85, [(AIR, 10, 2, 9, 1.43, [(ARMORED, 4)])], [ARMORED, MECH], 150, 75, 2),
    U.LIBERATOR: (180, 0, 0, 4.72, [(AIR, 5, 2, 5, 1.29, [])], [ARMORED, MECH], 150, 125, 3),
    U.LIBERATORAG: (180, 0, 0, 0.0, [(GROUND, 75, 1, 10, 1.14, [])], [ARMORED, MECH], 150, 125, 3),
    U.BANSHEE: (140, 0, 0, 3.85, [(GROUND, 12, 2, 6, 0.89, [])], [LIGHT, MECH], 150, 100, 3),
    U.RAVEN: (140, 0, 1, 3.85, [], [LIGHT, MECH], 100, 150, 2),
    U.BATTLECRUISER: (550, 0, 3, 2.62, [(GROUND, 8, 1, 6, 0.16, []), (AIR, 5, 1, 6, 0.16, [])], [ARMORED, MECH, MASSIVE], 400, 300, 6),
    U.SCV: (45, 0, 0, 3.94, [(GROUND, 5, 1, 0.1, 1.07, [])], [LIGHT, BIO, MECH], 50, 0, 1),
    U.ZERGLING: (35, 0, 0, 4.13, [(GROUND, 5, 1, 0.1, 0.497, [])], [LIGHT, BIO], 25, 0, 0.5),
    U.ROACH: (145, 0, 1, 3.15, [(GROUND, 16, 1, 4, 1.43, [])], [ARMORED, BIO], 75, 25, 2),
    U.HYDRALISK: (90, 0, 0, 3.15, [(ANY, 12, 1, 5, 0.59, [])], [LIGHT, BIO], 100, 50, 2),
    U.MUTALISK: (120, 0, 0, 5.6, [(ANY, 9, 1, 3, 1.09, [])], [LIGHT, BIO], 100, 100, 2),
    U.ULTRALISK: (500, 0, 2, 4.13, [(GROUND, 35, 1, 0.1, 0.61, [])], [ARMORED, BIO, MASSIVE], 275, 200, 6),
    U.ZEALOT: (100, 50, 1, 3.15, [(GROUND, 8, 2, 0.1, 0.86, [])], [LIGHT, BIO], 100, 0, 2),
    U.STALKER: (80, 80, 1, 4.13, [(ANY, 13, 1, 6, 1.34, [(ARMORED, 5)])], [ARMORED, MECH], 125, 50, 2),
    U.IMMORTAL: (200, 100, 1, 3.15, [(GROUND, 20, 1, 6, 1.04, [(ARMORED, 30)])], [ARMORED, MECH, ROBOTIC], 275, 100, 4),
    U.VOIDRAY: (150, 100, 0, 3.85, [(ANY, 6, 1, 6, 0.36, [(ARMORED, 4)])], [ARMORED, MECH], 250, 150, 4),
    U.PHOTONCANNON: (150, 150, 1, 0.0, [(ANY, 20, 1, 7, 0.89, [])], [ARMORED, STRUCT], 150, 0, 0),
    U.SPINECRAWLER: (300, 0, 2, 0.0, [(GROUND, 25, 1, 7, 1.32, [(ARMORED, 5)])], [ARMORED, BIO, STRUCT], 100, 0, 0),
    U.BUNKER: (400, 0, 1, 0.0, [], [ARMORED, MECH, STRUCT], 100, 0, 0),
    U.MISSILETURRET: (250, 0, 0, 0.0, [(AIR, 12, 2, 7, 0.61, [])], [ARMORED, MECH, STRUCT], 100, 0, 0),
    U.PLANETARYFORTRESS: (1500, 0, 3, 0.0, [(GROUND, 40, 1, 6, 1.43, [])], [ARMORED, MECH, STRUCT], 550, 150, 0),
    U.COMMANDCENTER: (1500, 0, 1, 0.0, [], [ARMORED, MECH, STRUCT], 400, 0, 0),
    U.BARRACKS: (1000, 0, 1, 0.0, [], [ARMORED, MECH, STRUCT], 150, 0, 0),
    U.NEXUS: (1000, 1000, 1, 0.0, [], [ARMORED, MECH, STRUCT], 400, 0, 0),
    U.HATCHERY: (1500, 0, 1, 0.0, [], [ARMORED, BIO, STRUCT], 300, 0, 0),
    U.DRONE: (40, 0, 0, 3.94, [(GROUND, 5, 1, 0.1, 1.07, [])], [LIGHT, BIO], 50, 0, 1),
    U.PROBE: (20, 20, 0, 3.94, [(GROUND, 5, 1, 0.1, 1.07, [])], [LIGHT, MECH], 50, 0, 1),
    U.OVERLORD: (200, 0, 0, 0.9, [], [ARMORED, BIO], 100, 0, 0),
}
FLYING_TYPES = {U.MEDIVAC, U.VIKINGFIGHTER, U.LIBERATOR, U.LIBERATORAG, U.BANSHEE, U.RAVEN, U.BATTLECRUISER,
                U.MUTALISK, U.VOIDRAY, U.OVERLORD}
RADIUS = {U.SIEGETANK: 0.875, U.SIEGETANKSIEGED: 0.875, U.MARAUDER: 0.5625, U.ULTRALISK: 1.0,
          U.COMMANDCENTER: 2.75, U.BARRACKS: 1.75, U.NEXUS: 2.75, U.HATCHERY: 2.5, U.BATTLECRUISER: 1.25}

ABILITY_DEFS = {
    AbilityId.SMART: (1, 4), AbilityId.MOVE: (16, 5), AbilityId.ATTACK: (23, 4), AbilityId.ATTACK_ATTACK: (3674, 4),
    AbilityId.STOP: (4, 1), AbilityId.MOVE_MOVE: (16, 5), AbilityId.SCAN_MOVE: (19, 4), AbilityId.BEHAVIOR_CLOAKOFF_BANSHEE: (393, 1), AbilityId.EFFECT_STIM_MARINE: (380, 1), AbilityId.EFFECT_STIM_MARAUDER: (253, 1),
    AbilityId.SIEGEMODE_SIEGEMODE: (388, 1), AbilityId.UNSIEGE_UNSIEGE: (390, 1),
    AbilityId.MORPH_LIBERATORAGMODE: (2560, 2), AbilityId.MORPH_LIBERATORAAMODE: (2560, 1),
    AbilityId.LOCKON_LOCKON: (2350, 3), AbilityId.EFFECT_INTERFERENCEMATRIX: (3751, 3),
    AbilityId.BUILDAUTOTURRET_AUTOTURRET: (3687, 2), AbilityId.KD8CHARGE_KD8CHARGE: (2588, 4),
    AbilityId.BEHAVIOR_CLOAKON_BANSHEE: (392, 1), AbilityId.EFFECT_MEDIVACIGNITEAFTERBURNERS: (2116, 1),
    AbilityId.MEDIVACHEAL_HEAL: (386, 3), AbilityId.LOCKONAIR_LOCKONAIR: (2350, 3),
}
CAST_RANGE = {AbilityId.LOCKON_LOCKON: 7, AbilityId.MORPH_LIBERATORAGMODE: 10, AbilityId.EFFECT_INTERFERENCEMATRIX: 9,
              AbilityId.BUILDAUTOTURRET_AUTOTURRET: 2, AbilityId.KD8CHARGE_KD8CHARGE: 5}


def make_response_data():
    data = SimpleNamespace(abilities=[], units=[], upgrades=[], buffs=[], effects=[])
    for ability_id in AbilityId:
        if ability_id.value == 0:
            continue
        a = data_pb2.AbilityData()
        a.ability_id = ability_id.value
        a.link_name = ability_id.name
        a.button_name = ability_id.name
        a.available = True
        a.target = ABILITY_DEFS[ability_id][1] if ability_id in ABILITY_DEFS else 4     # default: point-or-unit
        a.cast_range = CAST_RANGE.get(ability_id, 0)
        data.abilities.append(a)
    for type_id, (hp, sh, armor, speed, weapons, attrs, mins, gas, supply) in STATS.items():
        u = data_pb2.UnitTypeData()
        u.unit_id = type_id.value
        u.name = type_id.name
        u.available = True
        u.mineral_cost = mins
        u.vespene_cost = gas
        u.food_required = supply
        u.movement_speed = speed
        u.armor = armor
        u.build_time = 500
        for a in attrs:
            u.attributes.append(a)
        for kind, dmg, attacks, rng, cd, bonus in weapons:
            w = u.weapons.add()
            w.type = kind
            w.damage = dmg
            w.attacks = attacks
            w.range = rng
            w.speed = cd
            for attr, val in bonus:
                b = w.damage_bonus.add()
                b.attribute = attr
                b.bonus = val
        data.units.append(u)
    return data


class World:
    """A BotAI (never started) + a hand-built GameData; creates real Unit objects."""

    def __init__(self, bot=None):
        self.bot = bot if bot is not None else BotAI()
        self.bot.state = SimpleNamespace(game_loop=100, upgrades=set(), effects=set(), dead_units=set())
        self.bot.game_data = GameData(make_response_data())
        self.bot._distances_override_functions(0)
        self._tags = itertools.count(1000)
        self.all_units = []

    def unit(self, type_id, pos, alliance=1, tag=None, hp=None, shield=None, energy=0.0, cooldown=0.0,
             flying=None, orders=(), buffs=(), build_progress=1.0, cloaked=False, visible=True, display=1):
        hp0, sh0 = STATS[type_id][0], STATS[type_id][1]
        p = raw_pb2.Unit()
        p.display_type = display if visible else 2  # 1 visible, 2 snapshot
        p.alliance = alliance
        p.tag = tag if tag is not None else next(self._tags)
        p.unit_type = type_id.value
        p.owner = 1 if alliance == 1 else 2
        p.pos.x, p.pos.y, p.pos.z = pos[0], pos[1], 10.0
        p.facing = 0.0
        p.radius = RADIUS.get(type_id, 0.375)
        p.build_progress = build_progress
        p.cloak = 1 if cloaked else 3
        p.health = hp0 if hp is None else hp
        p.health_max = hp0
        p.shield = sh0 if shield is None else shield
        p.shield_max = sh0
        p.energy = energy
        p.energy_max = 200
        p.is_flying = (type_id in FLYING_TYPES) if flying is None else flying
        p.weapon_cooldown = cooldown
        p.is_powered = True
        for b in buffs:
            p.buff_ids.append(b.value)
        for ability, target in orders:
            o = p.orders.add()
            o.ability_id = ability.value
            if isinstance(target, Point2) or isinstance(target, tuple):
                o.target_world_space_pos.x, o.target_world_space_pos.y = target[0], target[1]
            elif target is not None:
                o.target_unit_tag = target
        u = Unit(p, self.bot, distance_calculation_index=len(self.all_units), base_build=90000)
        self.all_units.append(u)
        return u

    def units(self, items):
        return Units(list(items), self.bot)
