"""Longer dynamic run with scripted events; prints what the army did and how long each step took."""
import _bootstrap  # noqa: F401  (repo root on sys.path - keep this first)
import asyncio, collections, os, sys, time, traceback
from loguru import logger
from sc2.ids.ability_id import AbilityId as A
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.ids.upgrade_id import UpgradeId
from ares.consts import UnitRole

import dynamic
from dynamic import BASES, SyntheticGame, run_frame, start_game
from test_dynamic import build_game


def main():
    logger.remove()
    errors = []
    logger.add(lambda m: errors.append(str(m)) if m.record["level"].no >= 40 else None)
    from bot.bot import SmoothBrainBot
    from s2clientprotocol import common_pb2
    race = {'zerg': common_pb2.Zerg, 'protoss': common_pb2.Protoss, 'terran': common_pb2.Terran}[os.environ.get('RACE', 'zerg')]
    game = build_game(race)
    bot = SmoothBrainBot()
    loop = asyncio.new_event_loop()
    client, proto_gi = loop.run_until_complete(start_game(game, bot))
    cx, cy = BASES["our_main"]
    timings = []
    per_frame_cmds = {}
    supply = 30
    cap = 200
    for i in range(int(os.environ.get("FRAMES", "160"))):
        # ---- scripted events
        if i == 5:
            for k in range(int(os.environ.get('MARINES', '30'))):
                game.add(U.MARINE, (cx + 14 + (k % 10) * 0.7, cy + 10 + (k // 10) * 0.7), 1)
            for k in range(3):
                game.add(U.SIEGETANK, (cx + 12 + k * 3, cy + 14), 1)
            for k in range(2):
                game.add(U.MEDIVAC, (cx + 12 + k, cy + 16), 1)
            game.add(U.BANSHEE, (cx + 10, cy + 5), 1)
            game.add(U.REAPER, (cx + 9, cy + 4), 1)
        if i == 40:      # an enemy attack wave hits the natural region: 6 lings + 4 roaches
            ex, ey = BASES["our_main"][0] + 26, BASES["our_main"][1] + 10
            for k in range(6):
                game.add(U.ZERGLING, (ex + k * 0.5, ey), 4)
            for k in range(4):
                game.add(U.ROACH, (ex + 3 + k * 0.7, ey + 2), 4)
        if i == 60:      # some of our marines die (death events)
            victims = [u for u in game.units_raw if u.alliance == 1 and u.unit_type == U.MARINE.value][:5]
            game.dead = [u.tag for u in victims]
            game.units_raw = [u for u in game.units_raw if u.tag not in game.dead]
        elif i == 61:
            game.dead = []
        if i == 80:      # the wave dies
            game.units_raw = [u for u in game.units_raw if u.alliance != 4]
        if i == 100:     # we max out, and the enemy has a hatchery at its main plus a spine
            supply = 198
            game.add(U.HATCHERY, BASES["enemy_main"], 4)
            game.add(U.SPINECRAWLER, (BASES["enemy_main"][0] - 8, BASES["enemy_main"][1] - 8), 4)
        before = len(client.sent_actions)
        t = time.perf_counter()
        try:
            loop.run_until_complete(run_frame(game, bot, proto_gi, i, supply_used=supply, supply_cap=cap,
                                              upgrades=[UpgradeId.STIMPACK]))
        except Exception:
            traceback.print_exc()
            print("FRAME", i, "FAILED")
            return 1
        timings.append(time.perf_counter() - t)
        acts = client.sent_actions[before:]
        per_frame_cmds[i] = collections.Counter(getattr(a.ability, "name", str(a.ability)) for a in acts)
        if i in (6, 30, 45, 60, 85, 105, 130, 159):
            role_counts = {r.name: len(bot.mediator.get_unit_role_dict[r.name]) for r in UnitRole if len(bot.mediator.get_unit_role_dict[r.name])}
            print(f"frame {i:3d}: attacking={bot.army.attacking} roles={role_counts} cmds={dict(per_frame_cmds[i].most_common(6))} step={timings[-1]*1000:.0f}ms")
    print(f"avg step {sum(timings)/len(timings)*1000:.0f} ms | max {max(timings)*1000:.0f} ms | last-100 avg {sum(timings[-100:])/len(timings[-100:])*1000:.0f} ms")
    print("army error counters:", bot.army._errors, "| ERROR logs:", len(errors))
    for e in errors[:5]:
        print(e[:1200])
    print("sim calls total:", bot.army.fight.total_sim_calls, "fallbacks:", bot.army.fight.total_fallbacks)
    return 0 if not errors and not bot.army._errors else 1


if __name__ == "__main__":
    sys.exit(main())
