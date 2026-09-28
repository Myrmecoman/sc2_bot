"""SCVs are not afraid of what cannot hurt them: changelings and Observers (bot/worker_micro.py: flee_worker_threats, bot/macro.py:
resume_building_construction, bot/scouting.py).

  premise    the fixture gives the changelings and the Observer a weapon, as if the game data listed one for them - the workers must not
             go by that (`can_attack_ground`), they go by what the unit is
  mining     the whole bot on the real Ares hub: one of them in the middle of the mineral line moves nobody
  control    a Reaper in the same place still sends every worker near it to the townhall
  building   an unattended structure is resumed with a changeling next to it (and not with a Reaper next to it)
  scout      the scouting SCV does not turn back for a changeling (it does for a Reaper)"""
import _bootstrap  # noqa: F401  (repo root on sys.path - keep this first)
import gamefix
import gamefix_more  # noqa: F401
from gamefix import ANY, GROUND, LIGHT, BIO, MECH
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

# what the game data might list for them: the weapon of what they look like (a changeling) - and, to be sure, one for the Observer too
gamefix.STATS[U.CHANGELINGZEALOT] = (100, 50, 1, 3.15, [(GROUND, 8, 2, 0.1, 0.86, [])], [LIGHT, BIO], 0, 0, 0)
gamefix.STATS[U.CHANGELINGMARINE] = (45, 0, 0, 3.15, [(ANY, 6, 1, 5, 0.61, [])], [LIGHT, BIO], 0, 0, 0)
gamefix.STATS[U.OBSERVER] = (40, 20, 0, 2.63, [(ANY, 5, 1, 5, 1.0, [])], [LIGHT, MECH], 25, 75, 1)

import test_worker_oracle as base                                                # noqa: E402  (after the fixture data above)
from test_worker_oracle import frame, gap, is_move, last_order, start, workers_of  # noqa: E402
import bot.worker_micro as wm                                                    # noqa: E402

RESULTS = []
SPOT = (33.0, 28.5)                                                              # over the workers' side of the base (see test_worker_oracle.py)


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail and not cond else ""))


def near_workers(env, enemy):
    return [w for w in workers_of(env["game"]) if gap(w, enemy) < wm.WORKER_FLEE_RANGE]


def mining():
    for kind in (U.CHANGELINGZEALOT, U.CHANGELINGMARINE, U.OBSERVER):
        env = start()
        enemy = env["game"].add(kind, SPOT, 4)
        near = near_workers(env, enemy)
        acts = frame(env)
        threats = [u for u in env["bot"].visible_enemy_units if u.can_attack_ground]
        check(f"premise: the fixture's {kind.name} is listed with a weapon (so `can_attack_ground` alone would make it a threat)", len(threats) == 1, str(threats))
        check(f"mining: a {kind.name} in the mineral line moves nobody ({len(near)} workers within {wm.WORKER_FLEE_RANGE:g} of it)",
              len(near) >= 6 and not any(is_move(last_order(acts, w)) for w in workers_of(env["game"])), str([last_order(acts, w) for w in near][:2]))
    env = start()
    reaper = env["game"].add(U.REAPER, SPOT, 4)
    near = near_workers(env, reaper)
    acts = frame(env)
    cc = Point2(base.BASES["our_main"])
    check("control: a Reaper in the same place still sends every worker near it to the townhall",
          len(near) >= 6 and all(is_move(last_order(acts, w)) and Point2((last_order(acts, w).target.x, last_order(acts, w).target.y)).distance_to(cc) < 1.0 for w in near),
          str([last_order(acts, w) for w in near][:2]))


def unattended_structure():
    """an unfinished structure with no SCV on it: the closest SCV is sent to resume it - unless something is next to it"""
    def resumed(kind):
        env = start()
        game = env["game"]
        cx, cy = base.BASES["our_main"]
        mineral = next(u for u in game.units_raw if u.unit_type == U.MINERALFIELD.value)
        for w in workers_of(game):                                   # (the resuming SCV is one that is mining)
            order = w.orders.add()
            order.ability_id = AbilityId.HARVEST_GATHER.value
            order.target_unit_tag = mineral.tag
        site = game.add(U.BARRACKS, (cx + 8.0, cy + 8.0), 1)
        site.build_progress = 0.4
        if kind is not None:
            game.add(kind, (cx + 8.0, cy + 12.0), 4)
        frame(env)
        acts = frame(env)                                            # (python-sc2 calls a structure unattended once it did not grow between two steps)
        return any(a.ability == AbilityId.SMART and getattr(a.target, "tag", None) == site.tag for a in acts)
    check("building: (premise) with nothing next to it an unattended structure is resumed", resumed(None))
    check("building: ...also with a changeling next to it", resumed(U.CHANGELINGZEALOT))
    check("building: ...and with an Observer over it", resumed(U.OBSERVER))
    check("building: (control) not with a Reaper next to it", not resumed(U.REAPER))


def scout():
    def turned_back(kind):
        env = start()
        game, bot = env["game"], env["bot"]
        scout_worker = workers_of(game)[0]
        bot.scout_attempted, bot.scout_worker_tag, bot.enemy_base_scouted = True, scout_worker.tag, False
        bot.is_visible = lambda position: False                     # (the synthetic map is fully visible: the scout would be done at once)
        game.add(kind, (scout_worker.pos.x + 5.0, scout_worker.pos.y), 4)
        frame(env)
        return bot.scout_worker_tag is None
    check("scout: the scouting SCV does not turn back for a changeling", not turned_back(U.CHANGELINGZEALOT))
    check("scout: ...nor for an Observer", not turned_back(U.OBSERVER))
    check("scout: (control) it does for a Reaper", turned_back(U.REAPER))


def main():
    mining()
    unattended_structure()
    scout()
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
