"""SCV repairs keep their rules (bot/repair.py), the whole bot on the real Ares hub:

  * never more than 4 SCVs on one unit or building
  * never a walk longer than 70 to get to a repair - the ground path, not the straight line - and an SCV that has walked that far
    on one job goes back to mining
  * only near home: what is repaired stands within 25 of a landed townhall, and SCVs more than 35 from one are called back
  * a flying unit only where an SCV can stand under it - not over the middle of a townhall

Every layout runs once with the rules and once with the limits switched off (the "control" run must show the old behavior - it proves
the layout really is one where the bot sends an SCV / leaves one alone, so a quiet run with the rules on is the rules' doing and not an
unrelated reason).

  home       a damaged tank next to the base gets an SCV; one that is already on it is left alone and no second one is sent
  far        a damaged tank 32 cells from the only base, with SCVs within reach of it: nobody is sent
  trailing   an SCV that is repairing a tank that has since walked far away is sent back to mine
  crew       a badly damaged building gets exactly 4 SCVs, not more - and 6 already on it are cut to 4
  wall       a tank 12 cells from an SCV but on the other side of a wall (a 90-cell walk round it) gets nobody; on this side it does
  budget     an SCV that has walked 70 on one repair job is sent back to mine
  flyer      a hurt banshee hovering over the middle of the townhall gets nobody; one over open ground beside the base does"""
import _bootstrap  # noqa: F401  (repo root on sys.path - keep this first)
import asyncio, math
from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U

import bot.repair as repair
from dynamic import BASES, run_frame, start_game
from test_dynamic import build_game
import gamefix_more  # noqa: F401
from bot.bot import SmoothBrainBot

RESULTS = []
DAMAGED = 70            # of a siege tank's 175 hit points: 40%, under the 70% repair threshold
DAMAGED_BANSHEE = 50    # of a banshee's 140: 36%


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail and not cond else ""))


def repair_order(worker_proto, target_tag):
    order = worker_proto.orders.add()
    order.ability_id = AbilityId.EFFECT_REPAIR_SCV.value
    order.target_unit_tag = target_tag


def run(layout, rules=True, frames=8):
    """returns (SCVs sent to repair the target, SCVs sent to mine that were on a job, the target's tag, the job's SCVs)"""
    saved = repair.HOME_RADIUS, repair.LEASH, repair.MAX_TRAVEL, repair.MAX_REPAIRERS, repair.reachable_from_ground
    if not rules:
        repair.HOME_RADIUS = repair.LEASH = repair.MAX_TRAVEL = math.inf          # = the bot as it was
        repair.MAX_REPAIRERS = 999
        repair.reachable_from_ground = lambda *args, **kwargs: True
    try:
        errors = []
        logger.remove()
        logger.add(lambda m: errors.append(str(m)) if m.record["level"].no >= 40 else None, colorize=False)
        game = build_game()
        bot = SmoothBrainBot()
        loop = asyncio.new_event_loop()
        client, proto_gi = loop.run_until_complete(start_game(game, bot))
        cx, cy = BASES["our_main"]
        job_workers = []
        if layout in ("home", "home_crewed"):
            tank = game.add(U.SIEGETANK, (cx + 12, cy + 12), 1, hp=DAMAGED)
            if layout == "home_crewed":
                worker = game.add(U.SCV, (cx + 11, cy + 11), 1)            # already repairing it: must keep doing so
                repair_order(worker, tank.tag)
                job_workers.append(worker)
        elif layout == "far":
            tank = game.add(U.SIEGETANK, (cx + 22.6, cy + 22.6), 1, hp=DAMAGED)      # 32 from the base, ~25 from the nearest SCVs
        elif layout == "trailing":
            tank = game.add(U.SIEGETANK, (cx + 40, cy + 40), 1, hp=DAMAGED)          # walked off with the army
            worker = game.add(U.SCV, (cx + 29, cy + 29), 1)                          # 41 from the base, on its heels
            repair_order(worker, tank.tag)
            job_workers.append(worker)
        elif layout in ("crew", "overcrowded"):
            tank = next(u for u in game.units_raw if u.unit_type == U.BARRACKS.value)
            tank.health = 200                                                        # 20% of 1000: four SCVs' worth of damage
            if layout == "overcrowded":
                for k in range(6):                                                   # six SCVs on it, whoever put them there
                    worker = game.add(U.SCV, (cx + 9 + k * 0.5, cy - 4), 1)
                    repair_order(worker, tank.tag)
                    job_workers.append(worker)
        elif layout in ("flyer_over_base", "flyer_beside_base"):
            tank = game.add(U.BANSHEE, (cx, cy) if layout == "flyer_over_base" else (cx + 5.5, cy), 1, hp=DAMAGED_BANSHEE)   # over the townhall / beside it
        elif layout in ("wall", "wall_same_side"):
            game.add(U.COMMANDCENTER, (54.5, 12.5), 1)                               # a base right by the wall (x 62-65), ...
            tank = game.add(U.SIEGETANK, (70 if layout == "wall" else 50, 12), 1, hp=DAMAGED)   # ...the tank over it (or on this side)
        else:  # "budget"
            tank = game.add(U.SIEGETANK, (cx + 12, cy + 12), 1, hp=DAMAGED)
            worker = game.add(U.SCV, (cx + 11, cy + 11), 1)
            repair_order(worker, tank.tag)
            job_workers.append(worker)
            bot.repair_jobs[worker.tag] = repair.RepairJob(target=tank.tag, since=0.0, last=(worker.pos.x, worker.pos.y), walked=66.0)
        repairs, called_off, distinct = set(), set(), set()
        job_tags = {w.tag for w in job_workers}
        for i in range(frames):
            if layout == "budget" and i == 1:
                job_workers[0].pos.x += 8                                            # 8 more on the road: 74 walked
            before = len(client.sent_actions)
            loop.run_until_complete(run_frame(game, bot, proto_gi, i))
            for a in client.sent_actions[before:]:
                if a.ability == AbilityId.EFFECT_REPAIR_SCV and getattr(a.target, "tag", None) == tank.tag:
                    repairs.add(a.unit.tag)
                elif a.ability == AbilityId.HARVEST_GATHER and a.unit.tag in job_tags:
                    called_off.add(a.unit.tag)
        assert not errors, errors[:1]
        return repairs, called_off, tank.tag, job_tags
    finally:
        repair.HOME_RADIUS, repair.LEASH, repair.MAX_TRAVEL, repair.MAX_REPAIRERS, repair.reachable_from_ground = saved


def main():
    repairs, called_off, _, _ = run("home")
    check("home: a damaged tank next to the base gets an SCV", len(repairs) == 1, str(repairs))
    repairs, called_off, _, jobs = run("home_crewed")
    check("home: an SCV already on it is not called off, and no second one is sent", not called_off and not repairs, f"{called_off} {repairs}")

    repairs, _, _, _ = run("far", rules=False)
    check("far (control, rules off): the old code sends an SCV to a tank 32 cells from the base", repairs, str(repairs))
    repairs, _, _, _ = run("far")
    check("far: nobody is sent to a tank that far from the base", not repairs, str(repairs))

    _, called_off, _, _ = run("trailing", rules=False)
    check("trailing (control, rules off): the old code lets the SCV follow the tank", not called_off, str(called_off))
    _, called_off, _, jobs = run("trailing")
    check("trailing: an SCV repairing a tank that walked away is sent back to mine", called_off == jobs, str(called_off))

    repairs, _, _, _ = run("crew")
    check("crew: a badly damaged building gets four SCVs, no more", len(repairs) == 4, str(len(repairs)))
    _, called_off, _, _ = run("overcrowded")
    check("crew: six SCVs on one building are cut to four (two go back to mine)", len(called_off) == 2, str(called_off))
    _, called_off, _, _ = run("overcrowded", rules=False)
    check("crew (control, rules off): ...and nothing cuts them without the cap", not called_off, str(called_off))

    repairs, _, _, _ = run("wall", rules=False)
    check("wall (control, rules off): the old code sends an SCV over a wall to a tank 12 cells away as the crow flies", repairs, str(repairs))
    repairs, _, _, _ = run("wall")
    check("wall: a tank behind a wall is 90 cells away on foot: nobody is sent", not repairs, str(repairs))
    repairs, _, _, _ = run("wall_same_side")
    check("wall: a tank on this side of it, a short walk away, gets an SCV", len(repairs) == 1, str(repairs))

    repairs, _, _, _ = run("flyer_over_base", rules=False)
    check("flyer (control, guard off): the old code sends an SCV to a banshee over the middle of the townhall", len(repairs) == 1, str(repairs))
    repairs, _, _, _ = run("flyer_over_base")
    check("flyer: nobody is sent to a banshee hovering over the middle of the townhall (the SCV would stop at its edge, out of repair range)", not repairs, str(repairs))
    repairs, _, _, _ = run("flyer_beside_base")
    check("flyer: a banshee over open ground beside the base gets an SCV", len(repairs) == 1, str(repairs))

    _, called_off, _, jobs = run("budget")
    check("budget: an SCV that has walked more than 70 on one repair job is sent back to mine", called_off == jobs, str(called_off))
    _, called_off, _, _ = run("budget", rules=False)
    check("budget (control): ...and stays on it without that rule", not called_off, str(called_off))

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
