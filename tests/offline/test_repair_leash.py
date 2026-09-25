"""SCVs that repair must stay near home (bot/macro.py: REPAIR_HOME_RADIUS / REPAIR_LEASH), the whole bot on the real Ares hub.

The bug: an SCV with a repair order on a unit follows it wherever it goes, so with the army marching across the map every SCV
repairing one of its tanks / medivacs went along and walked all the way back afterwards. Three layouts, each once with the leash
and once with it switched off (the "control" run must show the old behavior - it proves the layout really is one where the bot
sends an SCV, so a quiet run with the leash on is the leash's doing and not an unrelated reason):

  home     a damaged tank next to the base gets an SCV (repairs still work), and the SCV already repairing it is left alone
  far      a damaged tank 32 cells from the only base, with SCVs within reach of it: nobody is sent
  trailing an SCV that is repairing a tank that has since walked far away is sent back to mine"""
import _bootstrap  # noqa: F401  (repo root on sys.path - keep this first)
import asyncio, math
from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U

import bot.macro as macro
from dynamic import BASES, run_frame, start_game
from test_dynamic import build_game
import gamefix_more  # noqa: F401
from bot.bot import SmoothBrainBot

RESULTS = []
DAMAGED = 70            # of a siege tank's 175 hit points: 40%, under the 70% repair threshold


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail and not cond else ""))


def repair_order(worker_proto, target_tag):
    order = worker_proto.orders.add()
    order.ability_id = AbilityId.EFFECT_REPAIR_SCV.value
    order.target_unit_tag = target_tag


def run(layout, leash=True, frames=8):
    """returns (tags of SCVs sent to repair the tank, tags of SCVs sent to mine, the tank's tag, the tracked worker's tag or None)"""
    saved = macro.REPAIR_HOME_RADIUS, macro.REPAIR_LEASH
    if not leash:
        macro.REPAIR_HOME_RADIUS = macro.REPAIR_LEASH = math.inf          # = the bot as it was
    try:
        errors = []
        logger.remove()
        logger.add(lambda m: errors.append(str(m)) if m.record["level"].no >= 40 else None, colorize=False)
        game = build_game()
        bot = SmoothBrainBot()
        loop = asyncio.new_event_loop()
        client, proto_gi = loop.run_until_complete(start_game(game, bot))
        cx, cy = BASES["our_main"]
        tracked = None
        if layout == "home":
            tank = game.add(U.SIEGETANK, (cx + 12, cy + 12), 1, hp=DAMAGED)
            tracked = game.add(U.SCV, (cx + 11, cy + 11), 1)            # already repairing it: must keep doing so
            repair_order(tracked, tank.tag)
        elif layout == "far":
            tank = game.add(U.SIEGETANK, (cx + 22.6, cy + 22.6), 1, hp=DAMAGED)      # 32 from the base, ~25 from the nearest SCVs
        else:
            tank = game.add(U.SIEGETANK, (cx + 40, cy + 40), 1, hp=DAMAGED)          # walked off with the army
            tracked = game.add(U.SCV, (cx + 29, cy + 29), 1)                          # 41 from the base, on its heels
            repair_order(tracked, tank.tag)
        repairs, mining = set(), set()
        for i in range(frames):
            before = len(client.sent_actions)
            loop.run_until_complete(run_frame(game, bot, proto_gi, i))
            for a in client.sent_actions[before:]:
                if a.ability == AbilityId.EFFECT_REPAIR_SCV and getattr(a.target, "tag", None) == tank.tag:
                    repairs.add(a.unit.tag)
                elif a.ability == AbilityId.HARVEST_GATHER and tracked is not None and a.unit.tag == tracked.tag:
                    mining.add(a.unit.tag)
        assert not errors, errors[:1]
        return repairs, mining, tank.tag, tracked.tag if tracked is not None else None
    finally:
        macro.REPAIR_HOME_RADIUS, macro.REPAIR_LEASH = saved


def main():
    repairs, mining, _, tracked = run("home")
    check("home: a damaged tank next to the base gets an SCV", repairs - {tracked}, str(repairs))
    check("home: the SCV already repairing it is not called off", not mining, str(mining))

    repairs, _, _, _ = run("far", leash=False)
    check("far (control, leash off): the old code sends an SCV to a tank 32 cells from the base", repairs, str(repairs))
    repairs, _, _, _ = run("far")
    check("far: nobody is sent to a tank that far from the base", not repairs, str(repairs))

    _, mining, _, tracked = run("trailing", leash=False)
    check("trailing (control, leash off): the old code lets the SCV follow the tank", not mining, str(mining))
    _, mining, _, tracked = run("trailing")
    check("trailing: an SCV repairing a tank that walked away is sent back to mine", tracked in mining, str(mining))

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
