"""A worker fleeing a real combat threat (not an Oracle - see test_worker_oracle.py) moves AWAY from it, not blindly
to the nearest townhall - which is wrong exactly when the threat is standing AT that townhall, the most common
reason it is a threat in the first place (bot/worker_micro.py: flee_worker_threats). Reuses the same point_away_from
steering avoid_oracles already relies on, and the same hold/release tracking pattern (threat_fleeing, mirroring
oracle_fleeing) so a worker that reaches its away-point and goes idle is not immediately walked straight back
towards the same danger by micro_worker's "mine somewhere, even a threatened base, beats mining nowhere" fallback.

  away      a Zergling standing right on the townhall -> nearby workers flee farther from it, not towards it
  hold      a worker that fled is not sent back to mining while the threat is still close
  release   once the threat is far enough away, every worker that fled goes back to mining"""
import _bootstrap  # noqa: F401  (repo root on sys.path - keep this first)
import math
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U

import bot.worker_micro as wm
from dynamic import BASES
from test_worker_oracle import frame, gap, is_move, last_order, start, workers_of
import gamefix_more  # noqa: F401

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail and not cond else ""))


def flees_away_not_into_it():
    env = start()
    game = env["game"]
    workers = workers_of(game)
    cx, cy = BASES["our_main"]
    zergling = game.add(U.ZERGLING, (cx, cy), 4)                     # right at the townhall itself
    acts = frame(env)
    near = [w for w in workers if gap(w, zergling) < wm.WORKER_FLEE_RANGE]
    check("away: (premise) workers are actually within flee range of it", len(near) >= 6, str(len(near)))

    def target_gap(w):
        t = last_order(acts, w).target
        return math.hypot(t.x - zergling.pos.x, t.y - zergling.pos.y)

    check("away: every one of them flees FARTHER from the threat, not towards/into it",
          all(is_move(last_order(acts, w)) and target_gap(w) > gap(w, zergling) for w in near),
          str([last_order(acts, w) for w in near][:2]))
    check("away: the destination is not right back at the townhall - the exact spot the threat is standing on",
          all(math.hypot(last_order(acts, w).target.x - cx, last_order(acts, w).target.y - cy) > 2.0 for w in near),
          str([(last_order(acts, w).target.x, last_order(acts, w).target.y) for w in near][:2]))
    check("away: the bot remembers who is fleeing it", {w.tag for w in near} <= env["bot"].threat_fleeing, str(env["bot"].threat_fleeing))
    return env, zergling, near


def hold_and_release():
    env, zergling, near = flees_away_not_into_it()
    game = env["game"]

    # still close: must not be sent back to mining at the still-threatened base
    acts = frame(env)
    mined = [w for w in near if any(a.unit.tag == w.tag and a.ability == AbilityId.HARVEST_GATHER for a in acts)]
    check("hold: a worker that fled is not sent back to mining while the threat is still close", not mined, str(mined))

    # far enough now: released
    zergling.pos.x, zergling.pos.y = zergling.pos.x + 100.0, zergling.pos.y
    frame(env)                                                        # (the step in which the bot notices)
    acts = frame(env)
    gathers = [w for w in near if (o := last_order(acts, w)) is not None and o.ability == AbilityId.HARVEST_GATHER]
    check("release: once the threat is far enough away, every worker that fled goes back to mining",
          len(gathers) == len(near) and not (env["bot"].threat_fleeing & {w.tag for w in near}),
          f"{len(gathers)}/{len(near)}  {env['bot'].threat_fleeing}")


def repairing_a_structure_is_fearless():
    """repair.structure_repairers (worker_micro.py's avoid_oracles/flee_worker_threats exemption): manage_repairs
    runs inside macro(), which runs BEFORE worker_micro() in the same step (bot.py's on_step order) - a worker
    freshly assigned to repair a damaged STRUCTURE this very step has self.repair_jobs set synchronously, but
    is_repairing itself only catches up on the NEXT step's observation. Without the fix, flee_worker_threats saw a
    worker that (by its own stale is_repairing read) was not yet committed to anything, and overrode the brand new
    repair order with a flee move THE SAME STEP - so a structure under attack, the normal reason it needs repairing
    at all, never got a single repair tick in as long as the threat stayed close: the whole point of defending it,
    defeated."""
    env = start()
    game = env["game"]
    workers = workers_of(game)
    cc = next(u for u in game.units_raw if u.unit_type == U.COMMANDCENTER.value)
    cc.health = cc.health_max * 0.5                                   # badly damaged: manage_repairs wants it crewed
    cx, cy = BASES["our_main"]
    game.add(U.ZERGLING, (cx, cy), 4)                                 # a real threat right on top of the base
    near = [w for w in workers if gap(w, cc) < wm.WORKER_FLEE_RANGE]
    check("fearless: (premise) some workers start this step within flee range of the threat", len(near) >= 2, str(len(near)))
    acts = frame(env)
    repaired = [w for w in near if any(a.unit.tag == w.tag and a.ability == AbilityId.EFFECT_REPAIR_SCV for a in acts)]
    check("fearless: (premise) manage_repairs actually assigns one of them to the damaged command center this step",
          bool(repaired), str([last_order(acts, w) for w in near]))
    check("fearless: the SAME step's flee_worker_threats does not override that order with a flee move",
          bool(repaired) and all(last_order(acts, w).ability == AbilityId.EFFECT_REPAIR_SCV for w in repaired),
          str([last_order(acts, w) for w in repaired]))
    others = [w for w in near if w.tag not in {r.tag for r in repaired}]
    check("fearless: ...while a worker not picked for repair still flees the same threat",
          bool(others) and all(is_move(last_order(acts, w)) for w in others), str([last_order(acts, w) for w in others]))


def main():
    hold_and_release()
    repairing_a_structure_is_fearless()
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
