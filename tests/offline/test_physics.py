"""Emergent-behaviour scenarios: the real bot on Ares, with a crude physics/combat sim applying its commands."""
import _bootstrap  # noqa: F401  (repo root on sys.path - keep this first)
import asyncio, collections, os, sys, traceback
from loguru import logger
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.ids.upgrade_id import UpgradeId
from ares.consts import UnitRole

import dynamic
from dynamic import BASES, SyntheticGame, run_frame, start_game
from physics import Physics
import gamefix_more  # noqa: F401  (more unit types for the fixture: banelings, ...)
from test_dynamic import build_game

SCENARIO = os.environ.get("SCENARIO", "defend")
FRAMES = int(os.environ.get("FRAMES", "400"))
PERTURB = int(os.environ.get("PERTURB", "0"))          # seed: move every unit a little at the start, so many different fights can be compared


def populate(game, physics, scenario):
    cx, cy = BASES["our_main"]
    ex, ey = BASES["enemy_main"]
    if scenario == "vanguard":
        # a maxed army on the march, strung out along the road to the enemy: 14 marines in front (just before the gap in the wall across
        # the middle of the map), 26 more in a blob 14-20 cells behind them, and an enemy army waiting on the other side. The simulator
        # counts every unit it is given as fighting from the first second, so a fight judged on "everybody within 20 cells" has all 40
        # marines against the roaches while only the front 14 will be there for the next 4-5 seconds
        for k in range(14):
            physics.add(U.MARINE, (52 + (k % 7) * 0.7, 62 + (k // 7) * 0.7), 1)
        for k in range(26):
            physics.add(U.MARINE, (34 + (k % 9) * 0.7, 60 + (k // 9) * 0.7), 1)
        for k in range(16):
            physics.add(U.ROACH, (71 + (k % 8) * 0.8, 62 + (k // 8) * 0.8), 4)
    if scenario in ("defend", "kite", "big_defend", "air_defend", "baneling"):
        for k in range(30):
            physics.add(U.MARINE, (cx + 8 + (k % 10) * 0.7, cy + 10 + (k // 10) * 0.7), 1)
        for k in range(3):
            physics.add(U.SIEGETANK, (cx + 6 + k * 3, cy + 12), 1)
        for k in range(2):
            physics.add(U.MEDIVAC, (cx + 7 + k, cy + 14), 1)
    if scenario == "defend":
        for k in range(10):
            physics.add(U.ZERGLING, (cx + 45 + (k % 5) * 0.5, cy + 10 + (k // 5) * 0.5), 4)
        for k in range(3):
            physics.add(U.ROACH, (cx + 50 + k, cy + 12), 4)
    if scenario == "baneling":
        # a baneling-heavy Zerg force the simulator likes our chances against (so the "kite in when winning" rule is live)
        for k in range(14):
            physics.add(U.BANELING, (cx + 45 + (k % 7) * 0.7, cy + 10 + (k // 7) * 0.7), 4)
        for k in range(10):
            physics.add(U.ZERGLING, (cx + 50 + (k % 5) * 0.5, cy + 10 + (k // 5) * 0.5), 4)
        for k in range(3):
            physics.add(U.ROACH, (cx + 52 + k, cy + 12), 4)
        for k in range(2):
            physics.add(U.HYDRALISK, (cx + 53 + k, cy + 9), 4)
    if scenario == "kite":
        for k in range(8):
            physics.add(U.ROACH, (cx + 45 + (k % 4) * 0.8, cy + 10 + (k // 4) * 0.8), 4)
    if scenario == "big_defend":
        for k in range(30):
            physics.add(U.ROACH, (cx + 45 + (k % 6) * 0.8, cy + 10 + (k // 6) * 0.8), 4)
        for k in range(20):
            physics.add(U.ZERGLING, (cx + 52 + (k % 6) * 0.5, cy + 8 + (k // 6) * 0.5), 4)
    if scenario == "air_defend":
        for k in range(6):
            physics.add(U.MUTALISK, (cx + 40 + k * 0.8, cy + 6), 4)
    if scenario == "zoo":
        # one of everything the army controllers know, first against a mixed Zerg force at home (banelings, air, casters, ...),
        # later - once supply is maxed, see main() - marching on a fortified enemy main. Meant for crashes, not for balance
        ours = [(U.MARINE, 16), (U.MARAUDER, 6), (U.REAPER, 2), (U.GHOST, 2), (U.HELLION, 3), (U.HELLIONTANK, 2), (U.SIEGETANK, 3),
                (U.CYCLONE, 3), (U.THOR, 1), (U.WIDOWMINE, 2), (U.VIKINGFIGHTER, 2), (U.MEDIVAC, 2), (U.LIBERATOR, 2),
                (U.BANSHEE, 2), (U.RAVEN, 1), (U.BATTLECRUISER, 1)]
        i = 0
        for type_id, count in ours:
            for _ in range(count):
                physics.add(type_id, (cx + 6 + (i % 12) * 0.9, cy + 10 + (i // 12) * 0.9), 1)
                i += 1
        wave = [(U.ZERGLING, 10), (U.BANELING, 8), (U.ROACH, 6), (U.RAVAGER, 2), (U.HYDRALISK, 4), (U.QUEEN, 2), (U.MUTALISK, 4),
                (U.CORRUPTOR, 2), (U.ULTRALISK, 1), (U.LURKERMP, 1), (U.INFESTOR, 1)]
        i = 0
        for type_id, count in wave:
            for _ in range(count):
                physics.add(type_id, (cx + 42 + (i % 8) * 0.8, cy + 6 + (i // 8) * 0.8), 4)
                i += 1
        physics.add(U.HATCHERY, (ex, ey), 4)
        for k in range(3):
            physics.add(U.SPINECRAWLER, (ex - 10 - k * 3, ey - 10), 4)
    if scenario == "attack":
        # maxed army marches on a fortified enemy main
        for k in range(50):
            physics.add(U.MARINE, (cx + 8 + (k % 10) * 0.7, cy + 10 + (k // 10) * 0.7), 1)
        for k in range(4):
            physics.add(U.SIEGETANK, (cx + 6 + k * 3, cy + 12), 1)
        physics.add(U.MEDIVAC, (cx + 7, cy + 14), 1)
        physics.add(U.HATCHERY, (ex, ey), 4)
        for k in range(3):
            physics.add(U.SPINECRAWLER, (ex - 10 - k * 3, ey - 10), 4)
        for k in range(10):
            physics.add(U.ROACH, (ex - 14 + (k % 5) * 0.8, ey - 14 + (k // 5) * 0.8), 4)


def main():
    logger.remove()
    errors = []
    logger.add(lambda m: errors.append(str(m)) if m.record["level"].no >= 40 else None)
    from bot.bot import SmoothBrainBot
    game = build_game()
    bot = SmoothBrainBot()
    loop = asyncio.new_event_loop()
    client, proto_gi = loop.run_until_complete(start_game(game, bot))
    physics = Physics(game)
    if PERTURB:
        import random
        rng = random.Random(PERTURB)
        add = physics.add
        physics.add = lambda type_id, pos, alliance, **kw: add(type_id, (pos[0] + rng.uniform(-1.5, 1.5), pos[1] + rng.uniform(-1.5, 1.5)), alliance, **kw)
    populate(game, physics, SCENARIO)
    # workers stay static protos
    physics.adopt_existing()
    physics._regenerate()
    supply = 198 if SCENARIO in ("attack", "vanguard") else 60
    role_of = lambda r: len(bot.mediator.get_unit_role_dict[r.name])
    t_last = 0
    for i in range(FRAMES):
        if SCENARIO == "zoo" and i == 200:
            supply = 198                                   # the home defence is over: max out and go and kill the enemy main
        before = len(client.sent_actions)
        loop.run_until_complete(run_frame(game, bot, proto_gi, i, supply_used=supply, supply_cap=200,
                                          upgrades=[UpgradeId.STIMPACK]))
        physics.apply(client.sent_actions[before:])
        physics.step(2)
        ours = [u for u in physics.units.values() if u.alliance == 1]
        theirs = [u for u in physics.units.values() if u.alliance == 4 and not u.is_structure]
        if i % (60 if SCENARIO in ('attack', 'zoo') else 20) == 0:
            marines = [u for u in ours if u.type_id == U.MARINE]
            print(f"t={bot.time:6.1f}s f={i:3d} marines={len(marines):2d} tanks={sum(1 for u in ours if u.type_id in (U.SIEGETANK, U.SIEGETANKSIEGED))} "
                  f"enemy_units={len(theirs):2d} attacking={bot.army.attacking} ATK={role_of(UnitRole.ATTACKING)} DEF={role_of(UnitRole.BASE_DEFENDER)} "
                  f"DIV={role_of(UnitRole.CONTROL_GROUP_ONE)} kills={physics.kills.get(1, 0)} losses={physics.losses.get(1, 0)} "
                  f"flips={physics.order_flips} anchor={None if bot.army.anchor is None else (round(bot.army.anchor.x), round(bot.army.anchor.y))} "
                  f"staging={None if bot.army.staging_since is None else round(bot.time - bot.army.staging_since, 1)} "
                  f"sieged={sum(1 for u in ours if u.type_id == U.SIEGETANKSIEGED)} structs={sum(1 for u in physics.units.values() if u.alliance == 4 and u.is_structure)}")
        if not theirs and SCENARIO not in ("attack", "zoo"):
            t_last += 1
            if t_last > 60:
                break
    print("RESULT", SCENARIO, "| our kills", physics.kills.get(1, 0), "our losses", physics.losses.get(1, 0),
          "| order flips per unit per game-minute:", round(physics.order_flips / max(1, len(ours) + physics.losses.get(1, 0)) / max(0.1, bot.time / 60.0), 1))
    print("army errors:", bot.army._errors, "| ERROR logs:", len(errors))
    for e in errors[:3]:
        print(e[:1500])
    if SCENARIO == "baneling":
        # banelings are always backed away from, even when the simulator loves the fight: the old "kite in when very
        # confident" behaviour lost 14 of these 30 marines to splash
        lost = physics.splash_deaths.get(1, 0)
        print(f"marines killed by baneling splash: {lost}")
        if lost > 5:
            print("FAIL: the army walked into the banelings")
            return 1
    return 0 if not errors and not bot.army._errors else 1


if __name__ == "__main__":
    sys.exit(main())
