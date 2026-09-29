"""Workers are not sent to mine at a base a ground threat is standing next to (bot/worker_micro.py: base_is_threatened, used by
bot/speedmining.py's micro_worker and dispatch_workers).

  idle       an idle worker picks the nearest SAFE base, not simply the nearest one
  dispatch   an oversaturated base does not unload extra workers onto an undersaturated base that is under threat
  control    without a threat, both behave exactly as before (the closest/nearest-undersaturated base is used)"""
import _bootstrap  # noqa: F401  (repo root on sys.path - keep this first)
import asyncio
from loguru import logger
from sc2.ids.ability_id import AbilityId as A
from sc2.ids.unit_typeid import UnitTypeId as U

import dynamic
from dynamic import BASES, run_frame, start_game
from test_dynamic import build_game

dynamic._patch_bot_class(None)
from bot.bot import SmoothBrainBot

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail and not cond else ""))


def start(mutate=None):
    errors = []
    logger.remove()
    logger.add(lambda m: errors.append(str(m)) if m.record["level"].no >= 40 else None, colorize=False)
    game = build_game()
    if mutate is not None:
        mutate(game)
    bot = SmoothBrainBot()
    loop = asyncio.new_event_loop()
    client, proto_gi = loop.run_until_complete(start_game(game, bot))
    return {"game": game, "bot": bot, "client": client, "proto_gi": proto_gi, "loop": loop, "errors": errors, "i": 0}


def frame(env):
    before = len(env["client"].sent_actions)
    env["loop"].run_until_complete(run_frame(env["game"], env["bot"], env["proto_gi"], env["i"]))
    env["i"] += 1
    assert not env["errors"], env["errors"][:1]
    return env["client"].sent_actions[before:]


def with_second_base(threatened):
    def mutate(game):
        game.add(U.COMMANDCENTER, BASES["our_nat"], 1)     # build_game() already seeded minerals/geysers for every BASES entry
        if threatened:
            game.add(U.ZERGLING, (BASES["our_nat"][0] + 3, BASES["our_nat"][1]), 4)
    return mutate


# ---------------------------------------------------------------------------------------------------------------------------- idle worker
def idle_worker():
    def last_gather_target(threatened):
        """An idle worker, standing right next to the second base: the LAST HARVEST_GATHER order this frame is what actually takes
        effect (run_frame's frames=2 default runs micro_worker twice; an earlier, since-superseded order in the same frame is not a
        real disagreement - both saw the exact same state, this is just the harness batching two engine sub-steps into one call)."""
        env = start(with_second_base(threatened))
        scv = next(u for u in env["game"].units_raw if u.unit_type == U.SCV.value)
        scv.pos.x, scv.pos.y = BASES["our_nat"][0] + 2, BASES["our_nat"][1] + 2
        del scv.orders[:]
        acts = frame(env)
        gathers = [a for a in acts if a.unit.tag == scv.tag and a.ability == A.HARVEST_GATHER]
        return gathers[-1].target.position if gathers else None

    main_pos = BASES["our_main"]
    nat_pos = BASES["our_nat"]
    target = last_gather_target(threatened=True)
    check("idle worker: standing next to a THREATENED second base, it is sent to mine at the (safe) main instead",
          target is not None and target.distance_to(nat_pos) > 10 and target.distance_to(main_pos) < 10, str(target))
    target = last_gather_target(threatened=False)
    check("idle worker: (control) with no threat, it mines at the nearest base as usual - the second one, right next to it",
          target is not None and target.distance_to(nat_pos) < 10, str(target))


# ------------------------------------------------------------------------------------------------------------------------- rebalancing
def dispatch_rebalancing():
    """dispatch_workers moves workers off an oversaturated base once its own saturation history (up to 40 samples) shows it consistently
    over ideal_harvesters - both are bare proto fields the synthetic harness never sets on its own (real SC2 computes them; unlike most
    other fields here, they need to be given a value by hand), so this seeds them directly rather than playing out 40 real frames."""
    def workers_moved_to_nat(threatened):
        env = start(with_second_base(threatened))
        game, bot = env["game"], env["bot"]
        for u in game.units_raw:
            if u.unit_type == U.COMMANDCENTER.value:
                u.ideal_harvesters = 16                                    # real SC2 sets this from the actual mineral count; the fake harness does not
        cx, cy = BASES["our_main"]
        near_main_minerals = [
            u for u in game.units_raw
            if u.unit_type == U.MINERALFIELD.value and (u.pos.x - cx) ** 2 + (u.pos.y - cy) ** 2 <= 100
        ]
        scvs = [u for u in game.units_raw if u.unit_type == U.SCV.value][:6]
        for i, w in enumerate(scvs):                                       # 6 workers actively gathering at the main, for real (not just idle)
            mf = near_main_minerals[i % len(near_main_minerals)]
            del w.orders[:]
            order = w.orders.add()
            order.ability_id = A.HARVEST_GATHER.value
            order.target_unit_tag = mf.tag
        moved_tags = {w.tag for w in scvs}
        frame(env)                                                         # let the bot register the seeded state once
        cc1 = bot.townhalls.closest_to(BASES["our_main"])
        cc2 = bot.townhalls.closest_to(BASES["our_nat"])
        bot.townhall_saturations[cc1.tag] = [20] * 5                       # oversaturated (way above ideal_harvesters)
        bot.townhall_saturations[cc2.tag] = [0] * 5                        # empty (well under ideal_harvesters)
        acts = frame(env)
        return [a for a in acts if a.unit.tag in moved_tags and a.ability == A.HARVEST_GATHER and a.target.position.distance_to(cc2.position) < 10]

    check("dispatch: an oversaturated main does NOT unload workers onto a THREATENED, undersaturated second base",
          workers_moved_to_nat(threatened=True) == [], str(workers_moved_to_nat(threatened=True)))
    moved = workers_moved_to_nat(threatened=False)
    check("dispatch: (control) with no threat, it does rebalance workers onto the undersaturated second base as usual",
          len(moved) >= 1, str(moved))


def main():
    idle_worker()
    dispatch_rebalancing()
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
