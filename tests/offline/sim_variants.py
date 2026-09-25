"""Rust combat simulator with units in unusual states (buffs, cloak, burrow, hallucination, wounded, upgrades, orders, ...).
A Rust panic aborts the process, so a clean finish is the assertion."""
import _bootstrap  # noqa: F401  (repo root on sys.path - keep this first)
import os
import tempfile
from loguru import logger
logger.remove()
import gamefix
import gamefix_more  # noqa: F401
from gamefix import GROUND, AIR, ANY, LIGHT, ARMORED, BIO, MECH, ROBOTIC, PSI, MASSIVE, STRUCT
from fakes import Scene
from sc2.data import Race
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.units import Units

log = open(os.environ.get("SIMLOG", os.path.join(tempfile.gettempdir(), "sim_variants.log")), "w", buffering=1)
sc = Scene(enemy_race=Race.Zerg, real_managers=True)
ai = sc.ai
ALL_UPGRADES = [u for u in UpgradeId if any(k in u.name for k in ("WEAPONS", "ARMOR", "PLATING", "SHIELDS", "STIMPACK", "COMBATSHIELD", "CONCUSSIVE", "MELEE", "MISSILE", "CARAPACE", "FLYERATTACK", "FLYERCARAPACE", "CHARGE", "BLINK", "ADRENAL", "GROOVEDSPINES", "MUSCULARAUGMENTS", "NEURALPARASITE", "DRILLCLAWS", "SMARTSERVOS", "HISECAUTOTRACKING", "BANSHEECLOAK", "PERSONALCLOAKING", "HIGHCAPACITYBARRELS", "TUNNELINGCLAWS"))]
ai.state.upgrades = set(ALL_UPGRADES)
print("upgrades loaded into state:", len(ai.state.upgrades))

def call(tag, own, enemy, **kw):
    log.write(tag + "\n")
    for gp in (False, True):
        r = ai.mediator.can_win_fight(own_units=Units(own, ai), enemy_units=Units(enemy, ai), timing_adjust=gp, good_positioning=gp, workers_do_no_damage=False)
    return r

n = 0
# 1. stimmed / buffed units
own = [sc.own(U.MARINE, (60 + i, 60), buffs=(BuffId.STIMPACK,)) for i in range(4)] + [sc.own(U.MARAUDER, (60, 62), buffs=(BuffId.STIMPACKMARAUDER,))]
enemy = [sc.enemy(U.ZEALOT, (70 + i, 60), buffs=(BuffId.CHARGING,)) for i in range(3)] + [sc.enemy(U.ROACH, (70, 62), buffs=(BuffId.GRAVITONBEAM,))]
call("buffs", own, enemy); n += 1
# 2. cloaked / burrowed / hallucinated / wounded / low energy
enemy2 = [sc.enemy(U.BANSHEE, (70, 64), cloaked=True), sc.enemy(U.ROACHBURROWED, (71, 64)), sc.enemy(U.STALKER, (72, 64), hp=5, shield=0), sc.enemy(U.HIGHTEMPLAR, (73, 64), energy=75)]
call("cloak/burrow/wounded/energy", own, enemy2); n += 1
# 3. units with orders (attacking, moving, casting), snapshot-displayed (memory ghosts)
own3 = [sc.own(U.MARINE, (60 + i, 66), orders=[(AbilityId.ATTACK_ATTACK, Point2((70, 66)))]) for i in range(3)]
ghost = sc.enemy(U.ZERGLING, (72, 66), visible=False)
ghost._ghost = True
call("orders + ghost", own3, [ghost, sc.enemy(U.HYDRALISK, (73, 66), orders=[(AbilityId.MOVE_MOVE, Point2((60, 66)))])]); n += 1
# 4. big mixed armies, both directions
big_own = [sc.own(t, (50 + (i % 10), 40 + i // 10)) for i, t in enumerate([U.MARINE] * 20 + [U.MARAUDER] * 6 + [U.SIEGETANKSIEGED] * 3 + [U.MEDIVAC] * 3 + [U.VIKINGFIGHTER] * 2 + [U.LIBERATORAG] * 2 + [U.CYCLONE] * 2)]
big_enemy = [sc.enemy(t, (90 + (i % 10), 40 + i // 10)) for i, t in enumerate([U.ZEALOT] * 12 + [U.STALKER] * 8 + [U.IMMORTAL] * 3 + [U.COLOSSUS] * 2 + [U.ARCHON] * 2 + [U.VOIDRAY] * 4 + [U.PHOTONCANNON] * 2)]
r1 = call("big own vs big enemy", big_own, big_enemy); n += 1
r2 = call("big enemy vs big own", big_enemy, big_own); n += 1
# 5. degenerate inputs the wrapper must survive without the interpreter dying
call("single vs single", big_own[:1], big_enemy[:1]); n += 1
call("structures as enemies", big_own[:10], [sc.enemy(U.SPINECRAWLER, (80, 40)), sc.enemy(U.PLANETARYFORTRESS, (82, 40)), sc.enemy(U.BUNKER, (84, 40))]); n += 1
print(f"{n} unusual-state simulations completed without aborting | big own vs enemy: {r1.name} | enemy vs own: {r2.name}")
