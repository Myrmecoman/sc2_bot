"""Workers keep out from under an Oracle (bot/worker_micro.py: avoid_oracles).

  geometry   point_away_from: straight away from the threats (nearer ones count for more), the nearest free turn when that way is blocked,
             across when pulled both ways alike, nothing when everything is blocked
  dodge      the whole bot on the real Ares hub: an Oracle over the workers -> every worker within 7.5 moves straight away, to a spot more
             than 5 from it (and not to the townhall, which is what the generic flee does - and which is right under the Oracle when it
             floats over the base)
  hold       a worker that has fled stays out - no order sends it back to mining - while the Oracle is within 10 of it, and goes back
             once the Oracle is gone
  left alone an Oracle that is far away, or a hallucination, moves nobody; a repairing SCV is not pulled off its job
  generic    (control) any other threat still sends the workers to the townhall as before"""
import _bootstrap  # noqa: F401  (repo root on sys.path - keep this first)
import asyncio, math
from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

import bot.worker_micro as wm
from dynamic import BASES, run_frame, start_game
from test_dynamic import build_game
import gamefix_more  # noqa: F401
from bot.bot import SmoothBrainBot

RESULTS = []
ALERT = wm.ORACLE_AVOID_RANGE + wm.ORACLE_ALERT_MARGIN
RELEASE = wm.ORACLE_AVOID_RANGE + wm.ORACLE_RELEASE_MARGIN


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail and not cond else ""))


# ---------------------------------------------------------------------------------------------------------------------------- geometry
def geometry():
    everywhere = lambda p: True
    p = wm.point_away_from(Point2((10, 10)), [Point2((7, 10))], 6.0, everywhere)
    check("geometry: straight away from a threat", p is not None and abs(p.x - 16) < 1e-6 and abs(p.y - 10) < 1e-6, str(p))
    p = wm.point_away_from(Point2((10, 10)), [Point2((7, 10))], 6.0, lambda q: q.x <= 12)
    check("geometry: the way blocked, the nearest free turn (90 degrees, along the wall)", p is not None and abs(p.x - 10) < 1e-6 and abs(abs(p.y - 10) - 6) < 1e-6, str(p))
    check("geometry: everything blocked: None", wm.point_away_from(Point2((10, 10)), [Point2((7, 10))], 6.0, lambda q: False) is None)
    check("geometry: never a way back towards the threat (a wall on all the far side: None)",
          wm.point_away_from(Point2((10, 10)), [Point2((7, 10))], 6.0, lambda q: q.x <= 10.001) is not None
          and wm.point_away_from(Point2((10, 10)), [Point2((7, 10))], 6.0, lambda q: q.x < 9.9) is None)
    p = wm.point_away_from(Point2((10, 10)), [Point2((9, 10)), Point2((10, 20))], 6.0, everywhere)
    check("geometry: a nearer threat counts for more (1 away to the west, 10 to the north: east, a little south)", p is not None and p.x > 15 and 8.5 < p.y < 10, str(p))
    p = wm.point_away_from(Point2((10, 10)), [Point2((7, 10)), Point2((13, 10))], 6.0, everywhere)
    check("geometry: one threat on each side: across, not towards either", p is not None and abs(p.x - 10) < 1e-6 and abs(abs(p.y - 10) - 6) < 1e-6, str(p))
    p = wm.point_away_from(Point2((10, 10)), [Point2((10, 10))], 6.0, everywhere)
    check("geometry: right underneath it any way will do", p is not None and abs(p.distance_to(Point2((10, 10))) - 6) < 1e-6, str(p))
    p = wm.point_away_from(Point2((10, 10)), [Point2((10, 10))], 6.0, lambda q: q.x < 5)
    check("geometry: ...and when only the far side is free, that one", p is not None and p.x < 5, str(p))


# ------------------------------------------------------------------------------------------------------------------- the whole bot
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


def workers_of(game):
    return [u for u in game.units_raw if u.unit_type == U.SCV.value]


def gap(worker, other):
    return math.hypot(worker.pos.x - other.pos.x, worker.pos.y - other.pos.y)


def last_order(acts, worker):
    mine = [a for a in acts if a.unit.tag == worker.tag]
    return mine[-1] if mine else None


def is_move(order):
    return order is not None and order.ability in (AbilityId.MOVE_MOVE, AbilityId.MOVE) and isinstance(order.target, Point2)


def is_away(order, worker, oracle):
    """a move to a spot that is on the far side of the worker from the oracle, and outside the range to keep"""
    t = order.target
    towards = (t.x - worker.pos.x) * (worker.pos.x - oracle.pos.x) + (t.y - worker.pos.y) * (worker.pos.y - oracle.pos.y)
    return towards > 0 and math.hypot(t.x - oracle.pos.x, t.y - oracle.pos.y) > wm.ORACLE_AVOID_RANGE


def dodge_and_hold():
    env = start()
    game = env["game"]
    workers = workers_of(game)
    oracle = game.add(U.ORACLE, (33.0, 28.5), 4)                     # right over the workers' side of the base
    threatened = [w for w in workers if gap(w, oracle) < ALERT]
    acts = frame(env)
    orders = {w.tag: last_order(acts, w) for w in threatened}
    check("dodge: there are workers under the Oracle to look at", len(threatened) >= 6, str(len(threatened)))
    check("dodge: every worker within 7.5 of it is ordered to move straight away, to a spot more than 5 from it",
          all(is_move(o) and is_away(o, w, oracle) for w, o in ((w, orders[w.tag]) for w in threatened)), str([(w.tag, orders[w.tag]) for w in threatened][:2]))
    cc = (BASES["our_main"][0], BASES["our_main"][1])
    check("dodge: ...and not to the townhall (the generic flee's spot)",
          not any(is_move(o) and Point2((o.target.x, o.target.y)).distance_to(Point2(cc)) < 1.0 for o in orders.values()), str(cc))
    check("dodge: the bot remembers who is keeping out of its way", {w.tag for w in threatened} <= env["bot"].oracle_fleeing, str(env["bot"].oracle_fleeing))

    # the Oracle is farther now: some workers are out of the alert range but still inside the release range, some outside it
    oracle.pos.x, oracle.pos.y = 39.5, 28.3
    acts = frame(env)
    held = [w for w in threatened if ALERT <= gap(w, oracle) < RELEASE]
    released = [w for w in threatened if gap(w, oracle) >= RELEASE]
    check("hold: the layout has workers in the hold band and beyond it", len(held) >= 2 and len(released) >= 1, f"{len(held)} {len(released)}")
    mined = [w for w in held if any(a.unit.tag == w.tag and a.ability == AbilityId.HARVEST_GATHER for a in acts)]
    moved = [w for w in held if any(a.unit.tag == w.tag and is_move(a) for a in acts)]
    check("hold: a worker that fled and is still within 10 of the Oracle is not sent back to mining under it, nor sent running again",
          not mined and not moved, f"{len(mined)} mine, {len(moved)} move")
    check("hold: one that is farther than 10 is let go", not any(w.tag in env["bot"].oracle_fleeing for w in released), str(env["bot"].oracle_fleeing))
    check("hold: (the held ones are still kept out)", all(w.tag in env["bot"].oracle_fleeing for w in held), str(env["bot"].oracle_fleeing))

    game.units_raw.remove(oracle)                                     # it left (or died)
    frame(env)                                                        # (the step in which the bot notices)
    acts = frame(env)
    gathers = [w for w in workers if (o := last_order(acts, w)) is not None and o.ability == AbilityId.HARVEST_GATHER]
    check("hold: once it is gone every worker is sent back to mining", len(gathers) == len(workers) and not env["bot"].oracle_fleeing, f"{len(gathers)}/{len(workers)}")


def over_the_townhall():
    # the Oracle floats over the townhall - the generic flee's destination, and where the Oracle follows the workers to
    env = start()
    game = env["game"]
    workers = workers_of(game)
    oracle = game.add(U.ORACLE, (25.5, 25.5), 4)
    threatened = [w for w in workers if gap(w, oracle) < ALERT]
    acts = frame(env)
    check("over the townhall: every worker within 7.5 runs away from the Oracle, to a spot more than 5 from it (not to the townhall under it)",
          len(threatened) >= 6 and all(is_move(o) and is_away(o, w, oracle) for w, o in ((w, last_order(acts, w)) for w in threatened)),
          str([last_order(acts, w) for w in threatened][:2]))


def left_alone():
    env = start()
    game = env["game"]
    workers = workers_of(game)
    game.add(U.ORACLE, (60.0, 28.5), 4)                               # 30 away
    acts = frame(env)
    check("left alone: an Oracle far away moves nobody (they mine as usual)",
          not any(is_move(last_order(acts, w)) for w in workers) and all(last_order(acts, w) is not None for w in workers), "")

    env = start()
    game = env["game"]
    workers = workers_of(game)
    fake = game.add(U.ORACLE, (33.0, 28.5), 4)
    fake.is_hallucination = True
    acts = frame(env)
    check("left alone: a hallucinated Oracle moves nobody (it shoots nothing)", not any(is_move(last_order(acts, w)) for w in workers), str([last_order(acts, w) for w in workers][:2]))

    env = start()
    game = env["game"]
    workers = workers_of(game)
    cc_tag = next(u.tag for u in game.units_raw if u.unit_type == U.COMMANDCENTER.value)
    busy = workers[0]
    order = busy.orders.add()
    order.ability_id = AbilityId.EFFECT_REPAIR_SCV.value
    order.target_unit_tag = cc_tag
    game.add(U.ORACLE, (busy.pos.x + 2.0, busy.pos.y), 4)
    acts = frame(env)
    check("left alone: an SCV that is repairing is not pulled off its job", not is_move(last_order(acts, busy)), str(last_order(acts, busy)))
    others = [w for w in workers[1:]]
    check("left alone: ...while the others dodge", sum(1 for w in others if is_move(last_order(acts, w))) >= 6, "")


def generic_flee_control():
    env = start()
    game = env["game"]
    workers = workers_of(game)
    reaper = game.add(U.REAPER, (33.0, 28.5), 4)
    acts = frame(env)
    near = [w for w in workers if gap(w, reaper) < wm.WORKER_FLEE_RANGE]
    cc = Point2(BASES["our_main"])
    check("generic (control): any other threat still sends the workers to the townhall",
          len(near) >= 6 and all(is_move(last_order(acts, w)) and Point2((last_order(acts, w).target.x, last_order(acts, w).target.y)).distance_to(cc) < 1.0 for w in near),
          str([last_order(acts, w) for w in near][:2]))
    check("generic (control): ...and none of them is counted as dodging an Oracle", not env["bot"].oracle_fleeing, str(env["bot"].oracle_fleeing))


def main():
    geometry()
    dodge_and_hold()
    over_the_townhall()
    left_alone()
    generic_flee_control()
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
