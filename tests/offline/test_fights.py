"""The fight logic: who is in a fight (bot/army/local_fight.py), how the simulator is set up for it (bot/army/fight.py), and what the
army does with the answer (bot/army/manager.py, the bio controller).

Several checks here pin down what the REAL simulator does (it ignores distance; a side that walks in without a side that holds
never gets there; ...): the fight logic is built on those facts, and if a new simulator build changes one of them, the check that
fails is the place to start."""
import _bootstrap  # noqa: F401  (repo root on sys.path - keep this first)
import sys, traceback
from loguru import logger
logger.remove()
from ares.consts import EngagementResult as ER, UnitRole
from sc2.ids.ability_id import AbilityId as A
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

import gamefix_more  # noqa: F401  (more unit types for the fixture: banelings, ...)
from fakes import Scene
from bot.army.consts import KITE_IN_RESULT
from bot.army.context import ArmyContext
from bot.army.fight import BASELINE, FightEvaluator, SimSetup, Stance, engagement_result
from bot.army.local_fight import find_fights
from bot.army.orders import GroupOrders, Mode

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail and not cond else ""))


def scene():
    sc = Scene(real_managers=True)
    sc.own(U.COMMANDCENTER, (20, 20))
    return sc


def begin(sc):
    """refresh per-frame state like a real step would, and return a fresh context"""
    sc.ai._fake_time += 0.5
    sc.ai.state.game_loop += 11
    for u in sc.world.all_units:
        if not getattr(u, "_ghost", False):
            u.game_loop = sc.ai.state.game_loop
    sc.ai.actions.clear()
    sc.ai.mediator.refresh()
    sc.manager.fight.begin_step()             # every step has its own simulator budget (see FightEvaluator.begin_step)
    return ArmyContext(sc.ai, sc.manager.positioning)


def tags(units):
    return {u.tag for u in units}


# ------------------------------------------------------------------------------------------------------------ who is in a fight
def test_units_too_far_to_take_part_are_left_out():
    sc = scene()
    front = sc.own_many(U.MARINE, 8, (60, 60))
    behind = sc.own_many(U.MARINE, 20, (20, 60))               # 40 cells back: 10 seconds from the fight
    near = sc.enemy_many(U.ZERGLING, 6, (68, 60))
    far = sc.enemy_many(U.ROACH, 20, (140, 60))                # on their way, 70 cells off
    fights = find_fights(front + behind, near + far)
    fight = fights.fights[0] if len(fights) else None
    check("one fight", len(fights) == 1, str(len(fights)))
    check("our marines up front are in it, the ones 40 cells behind are not", fight is not None and tags(fight.own) == tags(front))
    check("the zerglings next to them are in it, the roaches 70 cells off are not", fight is not None and tags(fight.enemy) == tags(near))
    check("a marine that is in no fight has none", fights.fight_of(behind[0]) is None and fights.fight_of(front[0]) is fight)


def test_a_unit_joins_when_it_can_get_there_in_time():
    # a marine walks 3.15 cells a second and shoots 5 far, a roach walks as fast and shoots 4 far: within 4 seconds means about 17 cells
    for gap, expected in ((12, True), (16, True), (25, False), (40, False)):
        sc = scene()
        marine, roach = sc.own(U.MARINE, (40, 60)), sc.enemy(U.ROACH, (40 + gap, 60))
        check(f"marine and roach {gap} cells apart: {'a fight' if expected else 'no fight yet'}", bool(len(find_fights([marine], [roach]))) == expected)


def test_units_that_cannot_walk_are_in_a_fight_by_range_or_by_being_walked_to():
    sc = scene()
    tank = sc.own(U.SIEGETANKSIEGED, (40, 60))                  # range 13, never moves
    check("a sieged tank shoots the roach 10 cells away", bool(len(find_fights([tank], [sc.enemy(U.ROACH, (50, 60))]))))
    check("...and the roach 16 away, which is out of range but can walk to the tank in time", bool(len(find_fights([tank], [sc.enemy(U.ROACH, (56, 60))]))))
    check("...but not one 24 away: it cannot reach the tank in time and the tank cannot reach it",
          not len(find_fights([tank], [sc.enemy(U.ROACH, (64, 60))])))
    spine = sc.enemy(U.SPINECRAWLER, (52, 60))                  # 12 away: the tank reaches it, it cannot move
    check("a sieged tank in range of a spine crawler is in a fight with it", bool(len(find_fights([tank], [spine]))))
    check("...two immobile units out of each other's range are not", not len(find_fights([tank], [sc.enemy(U.SPINECRAWLER, (58, 60))])))


def test_units_that_cannot_hurt_each_other_are_not_in_a_fight():
    sc = scene()
    medivac = sc.own(U.MEDIVAC, (60, 60))
    check("a medivac and a zergling: nobody can hit anybody", not len(find_fights([medivac], [sc.enemy(U.ZERGLING, (62, 60))])))
    hydra = sc.enemy(U.HYDRALISK, (66, 60))
    fights = find_fights([medivac, sc.own(U.MARINE, (58, 60))], [hydra])
    check("a hydralisk can hit the medivac: it is in that fight", len(fights) == 1 and fights.fight_of(medivac) is not None)


def test_two_skirmishes_are_two_fights():
    sc = scene()
    left_own, left_enemy = sc.own_many(U.MARINE, 6, (30, 30)), sc.enemy_many(U.ZERGLING, 4, (36, 30))
    right_own, right_enemy = sc.own_many(U.MARINE, 10, (150, 150)), sc.enemy_many(U.ROACH, 5, (156, 150))
    fights = find_fights(left_own + right_own, left_enemy + right_enemy)
    check("two fights, the bigger one first", len(fights) == 2 and tags(fights.fights[0].own) == tags(right_own), str(len(fights)))
    check("each marine is in the one it stands in", fights.fight_of(left_own[0]) is fights.fights[1] and fights.fight_of(right_own[0]) is fights.fights[0])
    check("...and each fight has its own enemies only", tags(fights.fights[1].enemy) == tags(left_enemy) and tags(fights.fights[0].enemy) == tags(right_enemy))
    both = fights.fights_of(left_own + right_own)
    check("the fights of a set of units, biggest first, each once", [f.rank for f in both] == [0, 1])


def test_a_fight_is_engaged_once_each_side_has_a_weapon_on_the_other():
    sc = scene()
    marines = sc.own_many(U.MARINE, 4, (60, 60))
    check("roaches 3 cells off: engaged", find_fights(marines, sc.enemy_many(U.ROACH, 3, (63.5, 60))).fights[0].engaged)
    check("roaches 12 cells off: a fight is coming, not on yet", not find_fights(marines, sc.enemy_many(U.ROACH, 3, (72, 60))).fights[0].engaged)
    # the marines are in range of the roach at 4.5 (range 5), the roach is not in range of them (range 4): the marines have the volley
    marine = sc.own(U.MARINE, (80, 60))
    check("one side outranging the other is not 'engaged' yet", not find_fights([marine], [sc.enemy(U.ROACH, (85.2, 60))]).fights[0].engaged)
    tank = sc.enemy(U.SIEGETANKSIEGED, (95, 60))
    check("marines walking into sieged tanks that already reach them: not engaged", not find_fights(sc.own_many(U.MARINE, 3, (85, 60)), [tank]).fights[0].engaged)


def test_recently_seen_enemies_still_count():
    sc = scene()
    seen = sc.enemy(U.ROACH, (70, 60))
    fresh = sc.enemy(U.ROACH, (71, 60), visible=False)
    fresh._ghost = True
    fresh.game_loop = sc.ai.state.game_loop - int(5 * 22.4)               # dropped out of sight 5 seconds ago
    stale = sc.enemy(U.ROACH, (72, 60), visible=False)
    stale._ghost = True
    stale.game_loop = sc.ai.state.game_loop - int(30 * 22.4)              # 30 seconds ago
    found = tags(sc.manager._fight_enemies())
    check("what is in sight and what dropped out of it seconds ago is in the fight", seen.tag in found and fresh.tag in found)
    check("...what was last seen half a minute ago is not", stale.tag not in found)


# -------------------------------------------------------------------------------------------- how the simulator is set up
def test_the_runs_a_fight_is_judged_by():
    sc = scene()
    marines, tank_sieged = sc.own_many(U.MARINE, 3, (40, 60)), sc.own(U.SIEGETANKSIEGED, (42, 64))
    lings, spine = sc.enemy_many(U.ZERGLING, 3, (55, 60)), sc.enemy(U.SPINECRAWLER, (56, 64))
    own = marines + [tank_sieged]
    plan = FightEvaluator.plan
    check("a meeting, and a fight under way, are judged with everything in contact from the start",
          plan(Stance.MEETING, False, False, own, lings) == [(BASELINE, own)] and plan(Stance.ATTACKING, True, False, own, lings) == [(BASELINE, own)]
          and plan(Stance.DEFENDING, True, False, own, lings) == [(BASELINE, own)])
    runs = plan(Stance.ATTACKING, False, False, own, lings)
    check("walking into a position they hold: the enemy holds, and what cannot walk (the sieged tank) is not part of that run",
          len(runs) == 1 and runs[0][0] == SimSetup(True, 2, False) and tags(runs[0][1]) == tags(marines))
    runs = plan(Stance.ATTACKING, False, True, own, lings)
    check("...a cautious judgement also has to agree with the baseline", [r[0] for r in runs] == [BASELINE, SimSetup(True, 2, False)])
    check("...with nothing that can walk, only the baseline is left", plan(Stance.ATTACKING, False, False, [tank_sieged], lings) == [(BASELINE, [tank_sieged])])
    runs = plan(Stance.DEFENDING, False, False, own, lings)
    check("holding a position they walk into: we hold, positioning is reasonable", len(runs) == 1 and runs[0][0] == SimSetup(True, 1, True) and runs[0][1] == own)
    check("...unless what they bring cannot walk (a spine crawler would never arrive): baseline", plan(Stance.DEFENDING, False, False, own, lings + [spine]) == [(BASELINE, own)])


def test_the_simulator_ignores_distance_so_the_caller_must_choose_the_fight():
    sc = scene()
    ev = FightEvaluator(sc.ai)
    own = sc.own_many(U.MARINE, 16, (40, 60))
    near = sc.enemy_many(U.ROACH, 8, (52, 60))
    behind_them = sc.enemy_many(U.ROACH, 14, (64, 60))
    on_their_way = sc.enemy_many(U.ROACH, 14, (160, 60))
    a = ev.evaluate(own, near + behind_them, cache_seconds=0)
    b = ev.evaluate(own, near + on_their_way, cache_seconds=0)
    check("14 roaches right behind them and 14 roaches 100 cells away weigh the same", a == b, f"{a.name} / {b.name}")
    check("...and either group makes the fight much worse than the 8 near roaches alone", a < ev.evaluate(own, near, cache_seconds=0), f"{a.name}")


def test_walking_into_sieged_tanks_is_not_a_stomp():
    sc = scene()
    ev = FightEvaluator(sc.ai)
    marines = sc.own_many(U.MARINE, 20, (40, 60))
    tanks = sc.enemy_many(U.SIEGETANKSIEGED, 4, (52, 60))
    baseline = ev.evaluate(marines, tanks, stance=Stance.MEETING, cache_seconds=0)
    check("with everything in contact from the start 20 marines beat 4 sieged tanks handily", baseline >= KITE_IN_RESULT, baseline.name)
    attack = ev.evaluate(marines, tanks, stance=Stance.ATTACKING, cautious=True, cache_seconds=0)
    check("walking into them the tanks get their volleys first: that is no kite-in", attack < KITE_IN_RESULT, attack.name)
    # the simulator's own approach model with nobody holding lets the immobile tanks stand idle: this is why plan() does not use it
    sim = sc.ai.manager_hub.combat_sim_manager.combat_sim
    sim.enable_timing_adjustment(True)
    sim.assume_reasonable_positioning(False)
    sim.workers_do_no_damage(True)
    from sc2.units import Units
    won, left = sim.predict_engage(Units(marines, sc.ai), Units(tanks, sc.ai), optimistic=False, defender_player=0)
    raw = engagement_result(won, left, marines, tanks)
    check("(simulator quirk, why plan() avoids it: its approach model with nobody holding calls that fight a spotless win - if this fails "
          "the simulator changed and FightEvaluator.plan should be looked at again)", raw >= ER.VICTORY_EMPHATIC, raw.name)
    tanks6, lings = sc.own_many(U.SIEGETANKSIEGED, 6, (40, 70)), sc.enemy_many(U.ZERGLING, 16, (52, 70))
    won, left = sim.predict_engage(Units(tanks6, sc.ai), Units(lings, sc.ai), optimistic=False, defender_player=0)
    check("(simulator quirk) 6 sieged tanks lose to 16 zerglings without dealing damage in the no-holder approach model",
          not won and left >= 0.99 * sum(u.health for u in lings), f"{won} {left}")
    check("...while the evaluation, with the tanks holding, has them win", ev.evaluate(tanks6, lings, stance=Stance.DEFENDING, cache_seconds=0) >= ER.VICTORY_DECISIVE)


def test_holding_ground_is_worth_a_volley():
    sc = scene()
    ev = FightEvaluator(sc.ai)
    marines, roaches = sc.own_many(U.MARINE, 16, (40, 60)), sc.enemy_many(U.ROACH, 8, (52, 60))
    meeting = ev.evaluate(marines, roaches, stance=Stance.MEETING, cache_seconds=0)
    defending = ev.evaluate(marines, roaches, stance=Stance.DEFENDING, cache_seconds=0)
    check("16 marines against 8 roaches: a coin toss in the open, better when the roaches have to walk into their range",
          defending > meeting, f"{meeting.name} / {defending.name}")
    check("...but a commitment never counts on that: cautiously it is the baseline again",
          ev.evaluate(marines, roaches, stance=Stance.DEFENDING, cautious=True, cache_seconds=0) == meeting)


def test_evaluate_agrees_with_ares_on_the_baseline():
    sc = scene()
    ev = FightEvaluator(sc.ai)
    from sc2.units import Units
    # (fights that are clearly won or lost: the simulator is not exactly repeatable on a borderline mix of unit types, where a result that
    # sits on the line between two labels comes out as either of them)
    for label, own, enemy in (
        ("marines vs zerglings", sc.own_many(U.MARINE, 16, (40, 60)), sc.enemy_many(U.ZERGLING, 14, (50, 60))),
        ("marines vs a lot of roaches", sc.own_many(U.MARINE, 6, (40, 62)), sc.enemy_many(U.ROACH, 18, (52, 62))),
        ("marines and tanks vs a few roaches", sc.own_many(U.MARINE, 30, (40, 64)) + sc.own_many(U.SIEGETANK, 2, (38, 64)),
         sc.enemy_many(U.ROACH, 5, (52, 64))),
        ("marines vs banelings", sc.own_many(U.MARINE, 12, (40, 66)), sc.enemy_many(U.BANELING, 7, (50, 66))),
    ):
        ares = sc.ai.mediator.can_win_fight(own_units=Units(own, sc.ai), enemy_units=Units(enemy, sc.ai), timing_adjust=False,
                                            good_positioning=False, workers_do_no_damage=True)
        ours = ev.evaluate(own, enemy, stance=Stance.MEETING, cache_seconds=0)
        check(f"the baseline is what Ares' can_win_fight says ({label}: {ours.name})", ours == ares, f"{ours.name} / {ares.name}")


# ----------------------------------------------------------------------------------------------- what the army does with it
def test_kite_in_confidence_ignores_units_that_are_too_far_to_take_part():
    sc = scene()
    front = sc.own_many(U.MARINE, 12, (60, 60), role=UnitRole.ATTACKING)
    behind = sc.own_many(U.MARINE, 28, (42, 60), role=UnitRole.ATTACKING)        # 18 cells behind the front: inside the old 20-cell circle
    roaches = sc.enemy_many(U.ROACH, 12, (68, 60))
    ctx = begin(sc)
    sc.manager._find_fights(ctx)
    army = sc.ai.mediator.get_units_from_role(UnitRole.ATTACKING)
    group, per_unit = sc.manager._fight_view(ctx, army, Stance.ATTACKING)
    wide = FightEvaluator(sc.ai).evaluate(front + behind, roaches, cache_seconds=0)
    check("counting every marine within 20 cells (the old view) the fight looks like a stomp", wide >= KITE_IN_RESULT, wide.name)
    check("judged on the marines that can be there in time it is 12 against 12: no kite-in for the front",
          front[0].tag in per_unit and per_unit[front[0].tag] < KITE_IN_RESULT, str(per_unit.get(front[0].tag)))
    check("the marines 18 cells back are in no fight, so they get no confidence at all", behind[0].tag not in per_unit)
    check("the group's own verdict is the front's fight too", group is not None and group < KITE_IN_RESULT, str(group))


def test_kite_in_confidence_has_to_hold_for_a_while():
    sc = scene()
    marines = sc.own_many(U.MARINE, 30, (60, 60), role=UnitRole.ATTACKING)
    sc.enemy_many(U.ROACH, 5, (66, 60))

    def view():
        ctx = begin(sc)
        sc.manager._find_fights(ctx)
        army = sc.ai.mediator.get_units_from_role(UnitRole.ATTACKING)
        return sc.manager._fight_view(ctx, army, Stance.ATTACKING)[1], sc.manager._judge(ctx.fights.fights[0], Stance.ATTACKING, cautious=True)

    first, raw = view()
    check("30 marines against 5 roaches is a stomp", raw >= KITE_IN_RESULT, raw.name)
    check("...but on first sight nobody is allowed to act on that yet", first and all(v < KITE_IN_RESULT for v in first.values()), str(set(first.values())))
    sc.ai._fake_time += 0.5
    second, _ = view()
    check("...nor a second later", all(v < KITE_IN_RESULT for v in second.values()), str(set(second.values())))
    sc.ai._fake_time += 2.0
    third, _ = view()
    check("...once it has held for the confirmation time they are", all(v >= KITE_IN_RESULT for v in third.values()) and len(third) == len(marines),
          str(set(third.values())))
    roaches_more = sc.enemy_many(U.ROACH, 40, (70, 66))
    fourth, _ = view()
    check("...and it starts over if the fight stops looking like a stomp", all(v < KITE_IN_RESULT for v in fourth.values()), str(set(fourth.values())))
    sc.ai._enemies[:] = [e for e in sc.ai._enemies if e.tag not in tags(roaches_more)]
    fifth, _ = view()
    check("...so the stomp that comes back has to hold all over again", all(v < KITE_IN_RESULT for v in fifth.values()), str(set(fifth.values())))


def test_a_push_is_judged_on_the_fight_it_is_in():
    sc = scene()
    sc.own_many(U.MARINE, 6, (100, 100), role=UnitRole.ATTACKING)                       # the front
    sc.own_many(U.MARINE, 60, (40, 40), role=UnitRole.ATTACKING)                        # the rest of the army, 85 cells from it
    sc.enemy_many(U.ROACH, 18, (110, 100))
    sc.ai.supply_army = 66
    sc.step(dt=1.0)
    check("the whole army against everything known of theirs is a stomp: the push starts", sc.manager.attacking is True, str(sc.manager.global_result))
    for _ in range(5):
        sc.step(dt=1.0)
    check("...but the fight the army is IN is 6 marines against 18 roaches, and the push is called off", sc.manager.attacking is False)
    check("(the whole-army verdict still looked fine: the old rule would have kept fighting)", sc.manager.global_result >= ER.VICTORY_DECISIVE,
          str(sc.manager.global_result))
    for _ in range(3):
        sc.step(dt=1.0)
    check("...and it is not started again the moment later on the strength of that verdict: the army gets time to pull back first",
          sc.manager.attacking is False)


def test_group_orders_advance_result():
    sc = scene()
    m, other = sc.own(U.MARINE, (60, 60)), sc.own(U.MARINE, (61, 60))
    o = GroupOrders(label="t", mode=Mode.ATTACK, target=Point2((150, 150)), hold_point=Point2((60, 60)), local_result=ER.VICTORY_EMPHATIC)
    check("without per-unit results the group's result stands in", o.advance_result(m) == ER.VICTORY_EMPHATIC)
    o.unit_results = {m.tag: ER.LOSS_CLOSE}
    check("with them a unit gets its own", o.advance_result(m) == ER.LOSS_CLOSE)
    check("...and a unit that is in no fight gets none, whatever the group's result says", o.advance_result(other) is None)


def test_bio_kites_in_on_its_own_fight_not_the_groups():
    def situation():
        sc = scene()
        m = sc.own(U.MARINE, (60, 60), cooldown=10.0)
        sc.enemy(U.ROACH, (64, 60))
        sc.enemy(U.HYDRALISK, (66, 60))
        grid = sc.ai.mediator.ground
        grid[57:68, 55:66] = 60.0                               # they are shooting at us: without confidence the marine backs off
        return sc, m

    def orders_for(sc, **kw):
        hp = sc.hold_point
        return GroupOrders(label="t", mode=Mode.ATTACK, target=Point2((150, 150)), hold_point=hp, front=Point2((1.0, 0.0)),
                           bio_position=hp + Point2((2.0, 0.0)), **kw)

    sc, m = situation()
    ctx = begin(sc)
    sc.manager.bio.control(sc.world.units([m]), orders_for(sc, local_result=ER.VICTORY_EMPHATIC, unit_results={m.tag: ER.VICTORY_OVERWHELMING}), ctx)
    c = [(a, t) for a, t, q in [(c.ability, c.target, c.queue) for c in sc.ai.actions if c.unit.tag == m.tag]]
    check("confident in its own fight: it steps forward", any(a == A.MOVE_MOVE and t[0] > 60 for a, t in c), str(c))
    sc, m = situation()
    ctx = begin(sc)
    sc.manager.bio.control(sc.world.units([m]), orders_for(sc, local_result=ER.VICTORY_EMPHATIC, unit_results={}), ctx)
    c = [(a, t) for a, t, q in [(c.ability, c.target, c.queue) for c in sc.ai.actions if c.unit.tag == m.tag]]
    check("in no fight of its own it does not push in on the group's confidence", not any(a == A.MOVE_MOVE and t[0] > 60 for a, t in c), str(c))


def main():
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    only = sys.argv[1:]
    for t in tests:
        if only and t.__name__ not in only:
            continue
        print(f"--- {t.__name__}")
        try:
            t()
        except Exception:
            traceback.print_exc()
            RESULTS.append((t.__name__, False, "exception"))
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
