"""Run the real Rust combat simulator on every pair of army unit types (own x enemy). A Rust panic ABORTS the process, so
each pair is logged (flushed) BEFORE the call: if the run dies, the last line names the offending pair."""
import _bootstrap  # noqa: F401  (repo root on sys.path - keep this first)
import itertools, os, sys, tempfile
from loguru import logger
logger.remove()
from fakes import Scene
from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.units import Units


import gamefix_more  # noqa: F401  (extends gamefix.STATS)

TYPES = [
    U.MARINE, U.MARAUDER, U.REAPER, U.GHOST, U.HELLION, U.HELLIONTANK, U.SIEGETANK, U.SIEGETANKSIEGED, U.CYCLONE, U.THOR,
    U.THORAP, U.WIDOWMINE, U.WIDOWMINEBURROWED, U.MEDIVAC, U.LIBERATOR, U.LIBERATORAG, U.VIKINGFIGHTER, U.VIKINGASSAULT,
    U.BANSHEE, U.RAVEN, U.BATTLECRUISER, U.SCV, U.BUNKER, U.PLANETARYFORTRESS, U.MISSILETURRET,
    U.ZEALOT, U.STALKER, U.SENTRY, U.ADEPT, U.HIGHTEMPLAR, U.DARKTEMPLAR, U.ARCHON, U.IMMORTAL, U.COLOSSUS, U.DISRUPTOR,
    U.VOIDRAY, U.PHOENIX, U.CARRIER, U.TEMPEST, U.ORACLE, U.MOTHERSHIP, U.OBSERVER, U.WARPPRISM, U.PHOTONCANNON,
    U.SHIELDBATTERY, U.PROBE, U.INTERCEPTOR,
    U.ZERGLING, U.BANELING, U.ROACH, U.RAVAGER, U.HYDRALISK, U.LURKERMP, U.LURKERMPBURROWED, U.QUEEN, U.MUTALISK,
    U.CORRUPTOR, U.BROODLORD, U.INFESTOR, U.ULTRALISK, U.SWARMHOSTMP, U.VIPER, U.LOCUSTMP, U.INFESTEDTERRAN, U.SPINECRAWLER,
    U.SPORECRAWLER, U.DRONE, U.OVERSEER, U.BROODLING, U.ROACHBURROWED, U.ZERGLINGBURROWED,
]
log = open(os.environ.get("SIMLOG", os.path.join(tempfile.gettempdir(), "sim_matrix.log")), "w", buffering=1)
sc = Scene(enemy_race=Race.Zerg, real_managers=True)
ai = sc.ai
results = {}
count = 0
for own_t in TYPES:
    own = [sc.own(own_t, (60 + i, 60)) for i in range(3)]
    for enemy_t in TYPES:
        enemy = [sc.enemy(enemy_t, (70 + i, 60)) for i in range(3)]
        for gp, ta in ((False, False), (True, True)):
            log.write(f"{own_t.name} vs {enemy_t.name} gp={gp} ta={ta}\n")
            r = ai.mediator.can_win_fight(own_units=Units(own, ai), enemy_units=Units(enemy, ai), timing_adjust=ta,
                                          good_positioning=gp, workers_do_no_damage=False)
            results[(own_t, enemy_t, gp)] = r
            count += 1
        ai._enemies[:] = [e for e in ai._enemies if e not in enemy]
    ai._own[:] = [u for u in ai._own if u not in own]
print("simulator calls without a crash:", count)
# a few sanity anchors
def res(a, b): return results[(a, b, True)].name
for a, b in ((U.MARINE, U.ZERGLING), (U.ZERGLING, U.MARINE), (U.SIEGETANKSIEGED, U.ZEALOT), (U.BATTLECRUISER, U.MARINE), (U.MARINE, U.BATTLECRUISER), (U.MARINE, U.MARINE)):
    print(f"  3x{a.name} vs 3x{b.name}: {res(a, b)}")
