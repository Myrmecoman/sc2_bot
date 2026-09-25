"""Randomised whole-bot run on the real Ares hub: armies of random composition meet random enemy forces, with random facing,
weapon cooldowns, health, energy, buffs, orders and available abilities, at random places on the synthetic map (at our bases, in the
middle, at theirs), against every race, at every supply level.

It checks ONE thing: nothing raises. Every exception the army manager's per-stage guards swallow (they log "[army] <stage> failed")
and every exception that escapes a step is collected and listed by where it was raised. It does not check that the bot decides well.

Why it exists: the crash a real game hit in Ares' reaper grenade needed a Reaper that FACED an enemy within range with its grenade
off cooldown, on a path from Ares' own path finder - a combination the hand-made scenarios never produced. Random states reach the
narrow preconditions of Ares' behaviors (and of the bridge in bot/ares_compat.py) that nobody would think to write down.

    python tests/offline/fuzz_army.py                     # 3 races x 300 frames, seed 1
    FUZZ_FRAMES=2000 FUZZ_SEED=7 python tests/offline/fuzz_army.py
    FUZZ_SCENARIO_FRAMES=150 python tests/offline/fuzz_army.py     # long situations: the time-based logic (staging, give-ups, ...) gets a turn
"""
import _bootstrap  # noqa: F401  (repo root on sys.path - keep this first)
import asyncio, collections, math, os, random, sys, traceback
from loguru import logger
from s2clientprotocol import common_pb2

from sc2.ids.ability_id import AbilityId as A
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.ids.upgrade_id import UpgradeId

import gamefix
import gamefix_more  # noqa: F401  (more unit types for the fixture: banelings, ...)
from dynamic import BASES, H, W, run_frame, start_game
from test_dynamic import build_game

FRAMES = int(os.environ.get("FUZZ_FRAMES", "300"))
SEED = int(os.environ.get("FUZZ_SEED", "1"))
SCENARIO_FRAMES = int(os.environ.get("FUZZ_SCENARIO_FRAMES", "14"))    # frames a random situation lasts before a new one replaces it

OWN_TYPES = [
    U.MARINE, U.MARINE, U.MARINE, U.MARAUDER, U.MARAUDER, U.REAPER, U.GHOST, U.HELLION, U.HELLIONTANK, U.SIEGETANK, U.SIEGETANK,
    U.SIEGETANKSIEGED, U.CYCLONE, U.THOR, U.THORAP, U.WIDOWMINE, U.WIDOWMINEBURROWED, U.VIKINGFIGHTER, U.VIKINGASSAULT, U.MEDIVAC,
    U.MEDIVAC, U.LIBERATOR, U.LIBERATORAG, U.BANSHEE, U.RAVEN, U.BATTLECRUISER,
]
ENEMY_TYPES = {
    "zerg": [U.ZERGLING, U.ZERGLING, U.BANELING, U.BANELING, U.ROACH, U.RAVAGER, U.HYDRALISK, U.LURKERMP, U.LURKERMPBURROWED, U.QUEEN,
             U.MUTALISK, U.CORRUPTOR, U.BROODLORD, U.INFESTOR, U.ULTRALISK, U.SWARMHOSTMP, U.VIPER, U.LOCUSTMP, U.INFESTEDTERRAN,
             U.SPINECRAWLER, U.SPORECRAWLER, U.DRONE, U.OVERSEER, U.BROODLING, U.ROACHBURROWED, U.ZERGLINGBURROWED],
    "protoss": [U.ZEALOT, U.ZEALOT, U.STALKER, U.STALKER, U.SENTRY, U.ADEPT, U.HIGHTEMPLAR, U.DARKTEMPLAR, U.ARCHON, U.IMMORTAL,
                U.COLOSSUS, U.DISRUPTOR, U.VOIDRAY, U.PHOENIX, U.CARRIER, U.TEMPEST, U.ORACLE, U.MOTHERSHIP, U.OBSERVER,
                U.WARPPRISM, U.PHOTONCANNON, U.SHIELDBATTERY, U.PROBE, U.INTERCEPTOR],
    "terran": [U.MARINE, U.MARINE, U.MARAUDER, U.REAPER, U.GHOST, U.HELLION, U.SIEGETANK, U.SIEGETANKSIEGED, U.CYCLONE, U.THOR,
               U.WIDOWMINE, U.WIDOWMINEBURROWED, U.VIKINGFIGHTER, U.MEDIVAC, U.LIBERATOR, U.BANSHEE, U.RAVEN, U.BATTLECRUISER,
               U.BUNKER, U.PLANETARYFORTRESS, U.MISSILETURRET, U.SCV],
}
ENEMY_STRUCTURES = {"zerg": [U.HATCHERY, U.SPINECRAWLER], "protoss": [U.NEXUS, U.PHOTONCANNON], "terran": [U.COMMANDCENTER, U.BUNKER]}
RACES = {"zerg": common_pb2.Zerg, "protoss": common_pb2.Protoss, "terran": common_pb2.Terran}
BURROWED = {U.LURKERMPBURROWED, U.ROACHBURROWED, U.ZERGLINGBURROWED, U.WIDOWMINEBURROWED}
# everything the army code (or an Ares behavior it runs) asks a unit's ability list about - a random subset is offered per unit
ABILITIES = [
    A.KD8CHARGE_KD8CHARGE, A.BEHAVIOR_CLOAKON_BANSHEE, A.BEHAVIOR_CLOAKOFF_BANSHEE, A.EFFECT_MEDIVACIGNITEAFTERBURNERS,
    A.EFFECT_INTERFERENCEMATRIX, A.BUILDAUTOTURRET_AUTOTURRET, A.EFFECT_ANTIARMORMISSILE, A.LOCKON_LOCKON, A.LOCKONAIR_LOCKONAIR,
    A.MORPH_LIBERATORAGMODE, A.MORPH_LIBERATORAAMODE, A.EFFECT_STIM_MARINE, A.EFFECT_STIM_MARAUDER, A.EFFECT_GHOSTSNIPE,
    A.BEHAVIOR_CLOAKON_GHOST, A.BEHAVIOR_CLOAKOFF_GHOST, A.BURROWDOWN_WIDOWMINE, A.BURROWUP_WIDOWMINE, A.SIEGEMODE_SIEGEMODE,
    A.UNSIEGE_UNSIEGE, A.MORPH_VIKINGASSAULTMODE, A.MORPH_VIKINGFIGHTERMODE, A.EMP_EMP,
]
BUFFS = [BuffId.STIMPACK, BuffId.STIMPACKMARAUDER, BuffId.GHOSTCLOAK, BuffId.BANSHEECLOAK, BuffId.LOCKON, BuffId.PARASITICBOMB]
UPGRADES = [UpgradeId.STIMPACK, UpgradeId.SHIELDWALL, UpgradeId.PUNISHERGRENADES, UpgradeId.BANSHEECLOAK, UpgradeId.PERSONALCLOAKING,
            UpgradeId.HIGHCAPACITYBARRELS, UpgradeId.DRILLCLAWS, UpgradeId.SMARTSERVOS]


class Fuzzer:
    def __init__(self, rng, race):
        self.rng = rng
        self.race = race
        self.game = build_game(RACES[race])
        self.pathing = self.game.pathing
        self.fuzz_tags = set()
        self.enemy_tags = set()
        self.description = ""
        self.supply = 60
        self.upgrades = []

    # ---- random state
    @staticmethod
    def _inside(point):
        """units never stand outside the map (the real API never reports one): keep every position well inside it"""
        return min(max(point[0], 12.0), W - 12.0), min(max(point[1], 12.0), H - 12.0)

    def _walkable(self, centre, radius, flying):
        centre = self._inside(centre)
        for _ in range(40):
            ang, dist = self.rng.uniform(0, 2 * math.pi), self.rng.uniform(0, radius)
            x, y = centre[0] + math.cos(ang) * dist, centre[1] + math.sin(ang) * dist
            if 9 < x < W - 9 and 9 < y < H - 9 and (flying or self.pathing[int(y), int(x)] == 1):
                return x, y
        return centre

    def _spawn(self, type_id, pos, alliance):
        rng = self.rng
        stats = gamefix.STATS.get(type_id)
        hp = None if rng.random() < 0.6 or not stats else stats[0] * rng.uniform(0.1, 1.0)
        p = self.game.add(type_id, pos, alliance, hp=hp, cooldown=rng.choice([0.0, 0.0, rng.uniform(0, 40.0)]),
                          energy=rng.uniform(0, 200.0))
        p.facing = rng.uniform(0, 2 * math.pi)
        if type_id in BURROWED:
            p.is_burrowed = True
        if alliance == 4 and rng.random() < 0.1:
            p.cloak = rng.choice([1, 2])                      # cloaked / cloaked and detected
        if alliance == 1 and rng.random() < 0.15:
            p.cloak = 1
        for buff in rng.sample(BUFFS, rng.randint(0, 2)):
            p.buff_ids.append(buff.value)
        return p

    def new_scenario(self):
        rng, game = self.rng, self.game
        # the last scenario goes away: ours with death events, theirs just out of sight (the Ares memory keeps them for a while)
        old = [u for u in game.units_raw if u.tag in self.fuzz_tags]
        game.dead = [u.tag for u in old if u.alliance == 1]
        game.units_raw = [u for u in game.units_raw if u.tag not in self.fuzz_tags]
        self.fuzz_tags, self.enemy_tags = set(), set()
        spots = {
            "our main": BASES["our_main"], "our natural": BASES["our_nat"], "the middle": (64, 64), "their natural": BASES["enemy_nat"],
            "their main": BASES["enemy_main"], "somewhere": self._walkable((64, 64), 45, False),
        }
        place = rng.choice(list(spots))
        centre = spots[place]
        own_kinds = rng.sample(OWN_TYPES, rng.randint(1, 7))
        enemy_pool = ENEMY_TYPES[self.race] + (ENEMY_TYPES["zerg"] if rng.random() < 0.15 else [])
        enemy_kinds = rng.sample(enemy_pool, rng.randint(1, 6))
        gap = rng.uniform(2.0, 26.0)
        heading = rng.uniform(0, 2 * math.pi)
        enemy_centre = self._inside((centre[0] + math.cos(heading) * gap, centre[1] + math.sin(heading) * gap))
        own = []
        for kind in own_kinds:
            for _ in range(rng.randint(1, 8)):
                flying = kind in gamefix.FLYING_TYPES
                own.append(self._spawn(kind, self._walkable(centre, 4.0, flying), 1))
        enemies = []
        for kind in enemy_kinds:
            for _ in range(rng.randint(1, 8)):
                flying = kind in gamefix.FLYING_TYPES
                enemies.append(self._spawn(kind, self._walkable(enemy_centre, 4.0, flying), 4))
        if rng.random() < 0.3:
            enemies.append(self._spawn(rng.choice(ENEMY_STRUCTURES[self.race]), self._walkable(enemy_centre, 6.0, False), 4))
        # aim about half of our units at the enemy group: facing is what many behaviors test first
        for p in own:
            if rng.random() < 0.5:
                target = min(enemies, key=lambda e: (e.pos.x - p.pos.x) ** 2 + (e.pos.y - p.pos.y) ** 2)
                p.facing = math.atan2(target.pos.y - p.pos.y, target.pos.x - p.pos.x) % (2 * math.pi)
            if rng.random() < 0.25:                            # some are already busy with an order
                order = p.orders.add()
                order.ability_id = rng.choice([A.ATTACK_ATTACK, A.ATTACK, A.MOVE_MOVE, A.MOVE, A.STOP]).value
                if rng.random() < 0.5:
                    order.target_unit_tag = rng.choice(enemies).tag
                else:
                    order.target_world_space_pos.x, order.target_world_space_pos.y = enemy_centre
        self.fuzz_tags = {p.tag for p in own + enemies}
        self.enemy_tags = {p.tag for p in enemies}
        self.supply = rng.choice([30, 60, 100, 150, 198])
        self.upgrades = rng.sample(UPGRADES, rng.randint(0, len(UPGRADES)))
        self.description = (f"{place}, gap {gap:.0f}, supply {self.supply}, ours {[k.name for k in own_kinds]} "
                            f"vs {[k.name for k in enemy_kinds]}")

    def jitter(self):
        """small changes every frame: movement, cooldowns, facing"""
        rng = self.rng
        for p in self.game.units_raw:
            if p.tag not in self.fuzz_tags:
                continue
            if p.unit_type in (U.HATCHERY.value, U.SPINECRAWLER.value, U.NEXUS.value, U.PHOTONCANNON.value, U.BUNKER.value,
                               U.COMMANDCENTER.value):
                continue
            x, y = p.pos.x + rng.uniform(-0.3, 0.3), p.pos.y + rng.uniform(-0.3, 0.3)
            if 9 < x < W - 9 and 9 < y < H - 9 and (p.is_flying or self.pathing[int(y), int(x)] == 1):
                p.pos.x, p.pos.y = x, y
            if rng.random() < 0.3:
                p.weapon_cooldown = rng.choice([0.0, 0.0, rng.uniform(0, 40.0)])
            if rng.random() < 0.2:
                p.facing = rng.uniform(0, 2 * math.pi)


def signature(exc_type, exc, tb):
    """what was raised, where, and - when that is inside python-sc2 or Ares - which line of ours (bot/) called into it"""
    frames = traceback.extract_tb(tb) if tb is not None else []
    if not frames:
        return f"{exc_type.__name__}: {str(exc)[:110]}"
    where = f"{os.path.relpath(frames[-1].filename)}:{frames[-1].lineno} in {frames[-1].name}"
    ours = [f for f in frames if os.sep + "bot" + os.sep in f.filename]
    caller = f"  <- {os.path.relpath(ours[-1].filename)}:{ours[-1].lineno} in {ours[-1].name}" if ours and ours[-1] is not frames[-1] else ""
    return f"{exc_type.__name__}: {str(exc)[:110]}  @ {where}{caller}"


def main():
    logger.remove()
    found = collections.OrderedDict()             # signature -> [count, first scenario description]
    current = {"description": ""}

    def sink(message):
        record = message.record
        if record["level"].no < 40:
            return
        exc = record["exception"]
        sig = signature(exc.type, exc.value, exc.traceback) if exc else "logged error: " + record["message"][:150]
        entry = found.setdefault(sig, [0, current["description"]])
        entry[0] += 1

    logger.add(sink, colorize=False)
    from bot.bot import SmoothBrainBot
    frames_done = 0
    for race in ("zerg", "protoss", "terran"):
        rng = random.Random(f"{SEED}-{race}")
        fuzz = Fuzzer(rng, race)
        bot = SmoothBrainBot()
        loop = asyncio.new_event_loop()
        client, proto_gi = loop.run_until_complete(start_game(fuzz.game, bot))

        async def abilities(units, ignore_resource_requirements=False, _rng=rng):
            return [[a for a in ABILITIES if _rng.random() < 0.5] for _ in units]

        client.query_available_abilities = abilities
        for i in range(FRAMES):
            if i % SCENARIO_FRAMES == 0:
                fuzz.new_scenario()
                current["description"] = f"[{race}] {fuzz.description}"
            else:
                fuzz.jitter()
                fuzz.game.dead = []
            try:
                loop.run_until_complete(run_frame(fuzz.game, bot, proto_gi, i, supply_used=fuzz.supply, supply_cap=200,
                                                  upgrades=fuzz.upgrades))
            except Exception as e:  # noqa: BLE001 - what escapes a step is a finding too
                sig = "ESCAPED THE STEP - " + signature(type(e), e, e.__traceback__)
                entry = found.setdefault(sig, [0, current["description"]])
                entry[0] += 1
            frames_done += 1
        print(f"{race}: {FRAMES} frames, army error counters {bot.army._errors}")
    print(f"\n{frames_done} random frames (seed {SEED})")
    if not found:
        print("no errors")
        return 0
    print(f"{len(found)} distinct error(s):")
    for sig, (count, description) in found.items():
        print(f"  x{count}  {sig}\n        first seen: {description}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
