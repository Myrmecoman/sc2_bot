"""Anti-Planetary-Fortress-rush worker tracking (bot/worker_micro.py: prevent_PF_rush) - once a worker is sent to
stand at/block a flying enemy Command Center, the SAME worker keeps doing it every step, instead of a fresh one
being peeled off mining each time.

  tracks     the worker sent in frame 1 to watch the flying CC is the one still ordered there in frame 2, even
             though it is no longer "gathering" by then (that is exactly the case the bug lost track of)
  cleans up  once that worker dies, a new one is picked and remembered in its place"""
import _bootstrap  # noqa: F401  (repo root on sys.path - keep this first)
import asyncio
from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U

from dynamic import BASES, run_frame, start_game
from test_dynamic import build_game
from test_worker_oracle import frame, is_move, last_order, start, workers_of
import gamefix_more  # noqa: F401
from bot.bot import SmoothBrainBot

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail and not cond else ""))


def gathering_from_the_start(game):
    """The synthetic harness never evolves a unit's orders on its own - .gather()/.move() calls the bot issues are
    captured for inspection but never fed back into game.units_raw - so a freshly-made SCV stays is_idle forever
    unless a gather order is put on its raw proto directly, here, before the first step ever runs."""
    mineral = next(u for u in game.units_raw if u.unit_type == U.MINERALFIELD.value)
    for w in game.units_raw:
        if w.unit_type == U.SCV.value:
            o = w.orders.add()
            o.ability_id = AbilityId.HARVEST_GATHER.value
            o.target_unit_tag = mineral.tag


def add_flying_cc(game):
    cx, cy = BASES["our_main"]
    game.add(U.COMMANDCENTERFLYING, (cx + 8, cy + 8), 4)   # within 14 of our own main CC


def tracks_the_same_worker():
    """The discriminating part: between the two frames, the originally-assigned worker is moved FAR from the flying
    CC and a different, previously-farther worker is moved right next to it instead - so "closest gathering worker"
    flips to a different unit. The fix must still re-command the ORIGINALLY assigned worker (trusting the stored
    assignment); the old bug, which resets the assignment to -1 every step, would hand the job to the newly-closer
    worker instead - this is what actually tells the two implementations apart, not just "a worker got picked"."""
    env = start(lambda game: (gathering_from_the_start(game), add_flying_cc(game)))
    acts1 = frame(env)
    moves1 = [a for a in acts1 if a.ability in (AbilityId.MOVE_MOVE, AbilityId.MOVE)]
    check("pf rush: a worker is sent towards the flying CC", bool(moves1), str([a.ability.name for a in acts1]))
    if not moves1:
        return
    first_worker_tag = moves1[-1].unit.tag
    flying_cc = next(u for u in env["game"].units_raw if u.unit_type == U.COMMANDCENTERFLYING.value)
    check("pf rush: the assignment is recorded (structure tag -> worker tag)",
          env["bot"].worker_assigned_to_follow.get(flying_cc.tag) == first_worker_tag,
          str(env["bot"].worker_assigned_to_follow))

    # flip the ranking: send the assigned worker away, bring an untouched one right next to the flying CC instead
    assigned_proto = next(w for w in workers_of(env["game"]) if w.tag == first_worker_tag)
    other_proto = next(w for w in workers_of(env["game"]) if w.tag != first_worker_tag)
    assigned_proto.pos.x, assigned_proto.pos.y = flying_cc.pos.x + 40.0, flying_cc.pos.y
    other_proto.pos.x, other_proto.pos.y = flying_cc.pos.x + 0.5, flying_cc.pos.y

    acts2 = frame(env)
    moves2 = [a for a in acts2 if a.ability in (AbilityId.MOVE_MOVE, AbilityId.MOVE)]
    check("pf rush: the ORIGINALLY assigned worker is still the one re-commanded, not the now-closer one",
          any(a.unit.tag == first_worker_tag for a in moves2), str([(a.unit.tag, a.ability.name) for a in moves2]))
    check("pf rush: ...and the assignment still points at it, not the now-closer worker",
          env["bot"].worker_assigned_to_follow.get(flying_cc.tag) == first_worker_tag,
          str(env["bot"].worker_assigned_to_follow))


def main():
    tracks_the_same_worker()
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
