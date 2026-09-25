import _bootstrap  # noqa: F401  (repo root on sys.path - keep this first)
import os, sys, traceback
REAL = os.environ.get('REAL') == '1'
from ares.consts import UnitRole, EngagementResult
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2

from gamefix import World
from fakes import Scene

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail and not cond else ""))


def scene_basic(**kw):
    sc = Scene(real_managers=REAL, **kw)
    sc.own(U.COMMANDCENTER, (20, 20))
    sc.own(U.BARRACKS, (28, 24))
    return sc


def test_hold_and_pre_position():
    sc = scene_basic()
    marines = sc.own_many(U.MARINE, 16, (40, 40))
    tanks = [sc.own(U.SIEGETANK, (44 + i, 44)) for i in range(3)]
    medivacs = [sc.own(U.MEDIVAC, (42, 42)), sc.own(U.MEDIVAC, (43, 42))]
    sc.step()
    roles = sc.ai.mediator.roles[UnitRole.ATTACKING]
    check("all army units got ATTACKING role", all(u.tag in roles for u in marines + tanks + medivacs))
    check("main army holds (not attacking)", sc.manager.attacking is False)
    cmds = sc.ai.actions
    check("commands were issued", len(cmds) > 0, str(len(cmds)))
    # marines walk to the bio position near the hold point
    marine_cmds = [c for c in cmds if c.unit.tag in {m.tag for m in marines}]
    check("marines ordered towards hold area", len(marine_cmds) == 16, str(len(marine_cmds)))
    tank_targets = [c.target for c in cmds if c.unit.tag in {t.tag for t in tanks}]
    check("tanks given distinct slot destinations", len({(round(t.x, 1), round(t.y, 1)) for t in tank_targets}) == 3, str(tank_targets))
    # put a tank at its slot -> it sieges proactively
    t0 = tanks[0]
    slot = sc.manager.positioning.tank_slots(sc.hold_point, 3)[sc.manager.tanks.slot_index[('main', t0.tag)]]
    sc.ai._own.remove(t0)
    t0b = sc.own(U.SIEGETANK, (slot.x, slot.y), tag=t0.tag, role=UnitRole.ATTACKING)
    sc.step()
    sieged = [c for c in sc.ai.actions if c.unit.tag == t0.tag and c.ability == AbilityId.SIEGEMODE_SIEGEMODE]
    check("tank at its slot sieges up proactively", len(sieged) == 1, str([(c.unit.tag, c.ability.name) for c in sc.ai.actions if c.unit.type_id == U.SIEGETANK]))


def test_fight_micro():
    sc = scene_basic()
    sc.ai.state.upgrades.add(UpgradeId.STIMPACK)
    marines = sc.own_many(U.MARINE, 20, (60, 60), role=UnitRole.ATTACKING)
    lings = sc.enemy_many(U.ZERGLING, 6, (68, 60))
    sc.step()
    cmds = sc.ai.actions
    attacked = [c for c in cmds if c.ability == AbilityId.ATTACK and hasattr(c.target, "tag")]
    check("marines with targets issue unit-targeted attacks", len(attacked) > 0, str(len(cmds)))
    kinds = {c.ability for c in cmds}
    print("   abilities issued:", sorted(a.name for a in kinds))


def test_defense_detachment():
    sc = scene_basic()
    marines = sc.own_many(U.MARINE, 30, (55, 55), role=UnitRole.ATTACKING)
    lings = sc.enemy_many(U.ZERGLING, 6, (32, 26))        # near the barracks / CC = a small threat at home
    sc.step()
    defenders = sc.ai.mediator.roles[UnitRole.BASE_DEFENDER]
    check("a detachment was split off", 3 <= len(defenders) < 30, str(len(defenders)))
    check("...and it is not the whole army", len(defenders) <= 18, str(len(defenders)))
    dcmds = [c for c in sc.ai.actions if c.unit.tag in defenders]
    check("defenders received orders", len(dcmds) > 0)
    # threat disappears -> defenders released after the delay
    sc.ai._enemies.clear()
    sc.step(dt=6.0)
    check("defenders released when threat is gone", len(sc.ai.mediator.roles[UnitRole.BASE_DEFENDER]) == 0,
          str(len(sc.ai.mediator.roles[UnitRole.BASE_DEFENDER])))


def test_big_threat_escalates():
    sc = scene_basic()
    sc.own_many(U.MARINE, 12, (40, 40), role=UnitRole.ATTACKING)
    sc.enemy_many(U.ROACH, 24, (32, 26))
    sc.step()
    check("no tiny detachment sacrificed vs a much bigger force", len(sc.ai.mediator.roles[UnitRole.BASE_DEFENDER]) == 0,
          str(len(sc.ai.mediator.roles[UnitRole.BASE_DEFENDER])))


def test_attack_decision():
    sc = scene_basic()
    sc.own_many(U.MARINE, 50, (40, 40), role=UnitRole.ATTACKING)
    sc.own_many(U.MARAUDER, 10, (44, 44), role=UnitRole.ATTACKING)
    sc.ai.supply_army = 50
    # nothing known about the enemy: sim-driven push must NOT start (no intel)
    sc.step()
    check("no push without intel", sc.manager.attacking is False)
    # they have an army we can see and beat
    sc.enemy_many(U.ZERGLING, 50, (150, 150))
    sc.step()
    check("push starts once a beatable known army is seen", sc.manager.attacking is True, str(sc.manager.global_result))
    # now a much stronger army is revealed
    sc.enemy_many(U.ROACH, 60, (152, 152))
    for _ in range(6):
        sc.step(dt=1.0)
    check("push is called off when the known army turns out to be far stronger", sc.manager.attacking is False,
          str(sc.manager.global_result))


def test_maxed_attacks():
    sc = scene_basic()
    sc.own_many(U.MARINE, 30, (40, 40), role=UnitRole.ATTACKING)
    sc.ai.supply_cap, sc.ai.supply_left = 200, 2
    sc.step()
    check("maxed out -> attack", sc.manager.attacking is True)


def _target_is(sc, point, tolerance=1.0):
    return sc.manager.positioning.attack_target().distance_to(Point2(point)) < tolerance


def _relocated(sc, units, dx, dy):
    """the same units (same tags and roles) a little further on - the fake world does not move anything by itself"""
    moved = []
    for u in units:
        sc.ai._own.remove(u)
        moved.append(sc.own(u.type_id, (u.position.x + dx, u.position.y + dy), tag=u.tag, role=UnitRole.ATTACKING))
    return moved


def test_army_gives_up_a_target_it_is_stuck_on():
    sc = scene_basic()
    marines = sc.own_many(U.MARINE, 20, (60, 60), role=UnitRole.ATTACKING)
    sc.ai.supply_cap, sc.ai.supply_left = 200, 2
    sc.enemy(U.HATCHERY, (120, 140))                                  # closest base to our start: the first target
    sc.enemy(U.HATCHERY, (150, 150))
    sc.step()
    check("attacking the closest base first", sc.manager.attacking and _target_is(sc, (120, 140)))
    for _ in range(14):                                               # the marines never get anywhere: stuck against something
        sc.step(dt=1.0)
    check("stuck for 12 s -> that base is given up and the next one becomes the target", _target_is(sc, (150, 150)), str(sc.manager.positioning.attack_target()))
    sc.step(dt=1.0)
    sent = [(c.target - m.position) for m in marines for c in sc.commands_for(m) if c.ability == AbilityId.ATTACK and hasattr(c.target, "x")]
    mean = Point2((sum(v.x for v in sent) / max(1, len(sent)), sum(v.y for v in sent) / max(1, len(sent))))
    dot = lambda a, b: a.x * b.x + a.y * b.y
    to_new, to_old = Point2((150, 150)) - Point2((60, 60)), Point2((120, 140)) - Point2((60, 60))
    check("...and the marines are sent towards it", sent and dot(mean.normalized, to_new.normalized) > dot(mean.normalized, to_old.normalized), str(mean))
    for _ in range(30):                                                # from here on the army moves: it is not stuck any more
        marines = _relocated(sc, marines, 1.0, 1.0)
        sc.step(dt=1.0)
    check("a target that was given up stays given up for a good while", _target_is(sc, (150, 150)) and not _target_is(sc, (120, 140)))
    # everything given up (nothing to walk to at all): it rotates - tries the one it gave up longest ago
    sc2 = scene_basic()
    sc2.own_many(U.MARINE, 20, (60, 60), role=UnitRole.ATTACKING)
    sc2.ai.supply_cap, sc2.ai.supply_left = 200, 2
    sc2.enemy(U.HATCHERY, (120, 140))
    sc2.step()
    positioning = sc2.manager.positioning
    positioning.give_up(Point2((120, 140)), 100.0)
    positioning.give_up(Point2((180, 180)), 50.0)                      # the enemy start location
    check("everything given up: the one given up longest ago is tried again", _target_is(sc2, (180, 180)), str(positioning.attack_target()))


def test_army_that_is_fighting_or_moving_is_not_stuck():
    # standing still while shooting is a fight, not a jam
    sc = scene_basic()
    sc.own_many(U.MARINE, 20, (60, 60), role=UnitRole.ATTACKING, cooldown=5.0)
    sc.ai.supply_cap, sc.ai.supply_left = 200, 2
    sc.enemy(U.HATCHERY, (120, 140))
    sc.enemy(U.HATCHERY, (150, 150))
    for _ in range(30):
        sc.step(dt=1.0)
    check("an army whose units are firing is not 'stuck'", _target_is(sc, (120, 140)))
    # walking, even slowly and not in a straight line, is not being stuck either
    sc = scene_basic()
    marines = sc.own_many(U.MARINE, 20, (60, 60), role=UnitRole.ATTACKING)
    sc.ai.supply_cap, sc.ai.supply_left = 200, 2
    sc.enemy(U.HATCHERY, (120, 140))
    sc.enemy(U.HATCHERY, (150, 150))
    sc.step()
    for i in range(40):
        marines = _relocated(sc, marines, 1.0, 0.4 if i % 2 else -0.4)
        sc.step(dt=1.0)
    check("an army that keeps moving is not 'stuck'", _target_is(sc, (120, 140)))


def test_attack_target_ignores_floating_buildings_while_ground_ones_exist():
    sc = scene_basic()
    sc.enemy(U.COMMANDCENTER, (100, 100), flying=True)                # lifted, closest, and hovering over who knows what
    barracks = sc.enemy(U.BARRACKS, (150, 150))
    check("the ground army goes for the building it can walk to", _target_is(sc, (150, 150)), str(sc.manager.positioning.attack_target()))
    sc.ai._enemies.remove(barracks)
    check("only floating buildings left: it goes for them after all", _target_is(sc, (100, 100)), str(sc.manager.positioning.attack_target()))


def test_staging_point_is_somewhere_standable():
    sc = scene_basic()
    sc.enemy(U.SPINECRAWLER, (100, 100))
    anchor = Point2((60, 100))
    ideal = sc.manager.positioning.staging_point(anchor, 3)
    check("control: the standoff point is 12.5 short of the defense", ideal is not None and abs(ideal.x - 87.5) < 0.1, str(ideal))
    sc.ai.in_pathing_grid = lambda p: not (85.0 <= p.x <= 90.0)      # that spot is a cliff
    moved = sc.manager.positioning.staging_point(anchor, 3)
    check("staging point: backed off to standable ground when the ideal spot is not", moved is not None and moved.x < 85.0 and moved.x > 79.0, str(moved))
    sc.ai.in_pathing_grid = lambda p: p.x < 70.0                     # nothing standable anywhere near the defense at all
    check("staging point: none at all when there is nowhere to stand", sc.manager.positioning.staging_point(anchor, 3) is None)


def test_progress_watch():
    from bot.army.progress import ProgressWatch
    target = Point2((100, 0))
    watch = ProgressWatch()
    at = Point2((0, 0))
    results = [watch.stuck(t, at, target, fighting=False) for t in range(0, 14)]
    check("progress watch: 12 s without moving -> stuck", results[-1] is True and results[10] is False, str(results))
    watch = ProgressWatch()
    results = [watch.stuck(t, at, target, fighting=(t % 5 != 0)) for t in range(0, 40)]
    check("progress watch: fighting keeps resetting the clock", not any(results), str(results))
    watch = ProgressWatch()
    results = [watch.stuck(t, Point2((t * 0.6, 0)), target, fighting=False) for t in range(0, 60)]
    check("progress watch: a group that keeps moving is never stuck", not any(results), str(results))
    watch = ProgressWatch()
    results = [watch.stuck(t, Point2((0, 0 if (t // 6) % 2 else 5)), target, fighting=False) for t in range(0, 70)]
    check("progress watch: jumping between two spots without getting closer is stuck too (slower)", results[-1] is True and not any(results[:40]), str([i for i, r in enumerate(results) if r][:3]))
    watch = ProgressWatch()
    for t in range(0, 20):
        watch.stuck(t, at, target, fighting=False)
    check("progress watch: a NEW target starts a new clock", watch.stuck(20, at, Point2((0, 100)), fighting=False) is False)
    check("progress watch: arriving is not being stuck", ProgressWatch().stuck(0, Point2((95, 0)), target, fighting=False) is False)


def test_banshee_harass():
    sc = scene_basic()
    b = sc.own(U.BANSHEE, (150, 160))
    sc.enemy(U.COMMANDCENTER if False else U.HATCHERY, (150, 150))
    sc.enemy_many(U.DRONE, 6, (148, 146))
    sc.step()
    check("banshee got the harass role", b.tag in sc.ai.mediator.roles[UnitRole.HARASSING_BANSHEE])
    cmds = sc.commands_for(b)
    check("banshee is ordered to do something", len(cmds) > 0)
    print("   banshee commands:", [(c.ability.name, getattr(c.target, 'tag', c.target)) for c in cmds])


def test_scouting_sweep():
    sc = scene_basic()
    sc.own_many(U.MARINE, 12, (40, 40), role=UnitRole.ATTACKING)
    sc.own_many(U.HELLION, 4, (42, 42), role=UnitRole.ATTACKING)
    sc.ai.supply_left = 0
    sc.step()
    scouts = sc.ai.mediator.roles[UnitRole.SCOUTING]
    check("hidden-base sweep started with scouts", len(scouts) >= 1, str(len(scouts)))
    check("scouts are fast units first", all(any(u.tag == t and u.type_id == U.HELLION for u in sc.ai.units) for t in list(scouts)[:3]))
    # they are left alone during the hold time
    sc.step(dt=5.0)
    stolen = [c for c in sc.ai.actions if c.unit.tag in scouts]
    check("army manager does not order scouts during the sweep", len(stolen) == 0, str(len(stolen)))
    sc.step(dt=40.0)
    check("scouts return to the army afterwards", len(sc.ai.mediator.roles[UnitRole.SCOUTING]) == 0)


def test_liberator_and_tanks():
    sc = scene_basic()
    lib = sc.own(U.LIBERATOR, (60, 60), role=UnitRole.ATTACKING)
    sc.ai.ability_grants[lib.tag] = {AbilityId.MORPH_LIBERATORAGMODE}
    sc.enemy(U.SIEGETANK, (66, 60))
    sc.step()
    cmds = sc.commands_for(lib)
    print("   liberator commands:", [(c.ability.name, c.target) for c in cmds])
    check("liberator goes for the enemy tank", len(cmds) > 0)


def test_staging_before_static_defense():
    sc = scene_basic()
    sc.ai.supply_cap, sc.ai.supply_left = 200, 2                 # maxed -> attack
    marines = sc.own_many(U.MARINE, 20, (120, 120), role=UnitRole.ATTACKING)
    tanks = [sc.own(U.SIEGETANK, (124 + i, 120), role=UnitRole.ATTACKING) for i in range(3)]
    pf = sc.enemy(U.PLANETARYFORTRESS, (150, 150))
    sc.step()
    check("attacking", sc.manager.attacking)
    check("a staging stop was set up", sc.manager.staging_since is not None)
    mc = [c for c in sc.ai.actions if c.unit.type_id == U.MARINE and hasattr(c.target, "x")]
    d = [Point2((c.target.x, c.target.y)).distance_to(pf.position) for c in mc]
    check("bio marches towards a point ~12.5 short of the planetary fortress", d and 12 <= min(d) <= 13, str(min(d) if d else None))

    # army that has reached the staging area: tanks dig in
    sc2 = scene_basic()
    sc2.ai.supply_cap, sc2.ai.supply_left = 200, 2
    pf2 = sc2.enemy(U.PLANETARYFORTRESS, (150, 150))
    sc2.own_many(U.MARINE, 20, (135, 135), role=UnitRole.ATTACKING)
    t2 = [sc2.own(U.SIEGETANK, (136 + i, 136), role=UnitRole.ATTACKING) for i in range(3)]
    sc2.step()
    sieges = [c for c in sc2.ai.actions if c.ability == AbilityId.SIEGEMODE_SIEGEMODE]
    check("tanks at the staging point siege up", len(sieges) == 3, str(len(sieges)))

    # dug in for a few seconds -> the push resumes (staging released and put on cooldown)
    sc3 = scene_basic()
    sc3.ai.supply_cap, sc3.ai.supply_left = 200, 2
    sc3.enemy(U.PLANETARYFORTRESS, (150, 150))
    sc3.own_many(U.MARINE, 20, (135, 135), role=UnitRole.ATTACKING)
    for i in range(3):
        sc3.own(U.SIEGETANKSIEGED, (137 + i, 137), role=UnitRole.ATTACKING)
    sc3.step()
    sc3.step(dt=5.0)
    check("staging is released once the tanks are dug in", sc3.manager.staging_since is None and sc3.manager.staging_cooldown_until > sc3.ai.time)


def test_numpy_points_from_ares():
    """Ares' path points come back with numpy int coordinates, and Point2.__bool__ then raises TypeError - so the approach
    point is normalised and no army code may truth-test a point. The scene normally pins front_vector to a constant; here
    the real one runs on a numpy-typed path, holding and attacking."""
    import numpy as np
    from bot.army.positioning import Positioning
    sc = scene_basic()
    positioning = sc.manager.positioning
    positioning.front_vector = Positioning.front_vector.__get__(positioning)
    sc.ai.mediator.find_raw_path = lambda **kw: [Point2((np.int32(x), np.int32(y))) for x, y in ((180, 180), (120, 100), (90, 70), (70, 60))]
    marines = sc.own_many(U.MARINE, 14, (40, 40))
    tanks = [sc.own(U.SIEGETANK, (44 + i, 44)) for i in range(2)]
    sc.step()
    check("holding on a numpy-typed approach path: orders issued, no stage errored", len(sc.ai.actions) > 0 and not sc.manager._errors, str(sc.manager._errors))
    front = positioning.front_vector(sc.hold_point)
    check("the front vector is made of plain floats", type(front[0]) is float and type(front[1]) is float, str(type(front[0])))
    sc.ai.supply_cap, sc.ai.supply_left = 200, 2          # maxed: attacks
    sc.own_many(U.MARINE, 30, (42, 46), role=UnitRole.ATTACKING)
    sc.step()
    sc.step()
    check("attacking on a numpy-typed approach path: no stage errored", sc.manager.attacking and not sc.manager._errors, str(sc.manager._errors))


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
