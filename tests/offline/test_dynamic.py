"""Dynamic integration test: the real SmoothBrainBot on Ares, start-up + frames, synthetic map/observations."""
import _bootstrap  # noqa: F401  (repo root on sys.path - keep this first)
import asyncio, os, sys, traceback

from loguru import logger
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.ids.upgrade_id import UpgradeId

import dynamic
from dynamic import BASES, SyntheticGame, run_frame, start_game

FRAMES = int(os.environ.get("FRAMES", "40"))


def build_game(enemy_race=None):
    g = SyntheticGame(enemy_race)
    for name in BASES:
        g.add_base_resources(name)
    cx, cy = BASES["our_main"]
    g.add(U.COMMANDCENTER, (cx, cy), 1)
    for i in range(12):
        g.add(U.SCV, (cx + 4 + (i % 4) * 0.8, cy + 3 + (i // 4) * 0.8), 1)
    g.add(U.BARRACKS, (cx + 10, cy - 6), 1)
    g.add(U.SUPPLYDEPOT, (cx + 8, cy + 8), 1)
    return g


def main():
    logger.remove()
    errors = []
    logger.add(lambda m: errors.append(str(m)) if m.record["level"].no >= 40 else None)   # ERROR and above
    dynamic._patch_bot_class(None)
    from bot.bot import SmoothBrainBot
    game = build_game()
    bot = SmoothBrainBot()
    loop = asyncio.new_event_loop()
    try:
        client, proto_gi = loop.run_until_complete(start_game(game, bot))
    except Exception:
        traceback.print_exc()
        print("START-UP FAILED")
        return 1
    print("start-up OK | Ares managers:", len(bot.manager_hub.managers))
    ok = True
    for i in range(FRAMES):
        if i == 10:      # an army appears at the rally point, an enemy scout shows up
            cx, cy = BASES["our_main"]
            for k in range(16):
                game.add(U.MARINE, (cx + 12 + (k % 8) * 0.7, cy + 8 + (k // 8) * 0.7), 1)
            for k in range(2):
                game.add(U.SIEGETANK, (cx + 14 + k * 3, cy + 12), 1)
            game.add(U.MEDIVAC, (cx + 12, cy + 12), 1)
        if i == 20:
            game.add(U.ZERGLING, (BASES["our_main"][0] + 20, BASES["our_main"][1] + 15), 4)
            game.add(U.ROACH, (BASES["our_main"][0] + 22, BASES["our_main"][1] + 15), 4)
        try:
            loop.run_until_complete(run_frame(game, bot, proto_gi, i, upgrades=[UpgradeId.STIMPACK] if i > 5 else []))
        except Exception:
            traceback.print_exc()
            print(f"FRAME {i} FAILED")
            ok = False
            break
    print(f"ran frames: {i + 1 if ok else i}; actions sent: {len(client.sent_actions)}; raw actions: {len(client.raw_actions)}")
    print("army manager error counters:", bot.army._errors if bot.army else None)
    print("logged ERROR-level messages:", len(errors))
    for e in errors[:6]:
        print(e[:1500])
    return 0 if ok and not errors else 1


if __name__ == "__main__":
    sys.exit(main())
