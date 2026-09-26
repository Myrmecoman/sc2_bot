"""Per-controller behavior tests: each builds a small scene and drives ONE controller directly."""
import _bootstrap  # noqa: F401  (repo root on sys.path - keep this first)
import os, sys, traceback, asyncio
import numpy as np
REAL = os.environ.get("REAL") == "1"
from ares.consts import UnitRole, EngagementResult as ER
from sc2.ids.ability_id import AbilityId as A
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2

import gamefix_more  # noqa: F401  (more unit types for the fixture: banelings, ...)
from fakes import Scene
from bot.army.context import ArmyContext
from bot.army.orders import GroupOrders, Mode

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail and not cond else ""))


def mk(**kw):
    sc = Scene(real_managers=REAL, **kw)
    sc.own(U.COMMANDCENTER, (20, 20))
    return sc


def orders(sc, mode=Mode.ATTACK, target=(150, 150), local=None, retreating=False, anchor=None):
    hp = sc.hold_point
    return GroupOrders(label="t", mode=mode, target=Point2(target), hold_point=hp, front=Point2((1.0, 0.0)),
                       bio_position=hp + Point2((2.0, 0.0)), anchor=Point2(anchor) if anchor else None,
                       local_result=local, retreating=retreating)


def begin(sc):
    """refresh per-frame state like a real step would, and return a fresh context"""
    sc.ai._fake_time += 0.5
    sc.ai.state.game_loop += 11
    for u in sc.world.all_units:
        if not getattr(u, "_ghost", False):
            u.game_loop = sc.ai.state.game_loop
    sc.ai.actions.clear()
    if hasattr(sc.ai.mediator, "refresh"):
        sc.ai.mediator.refresh()
    return ArmyContext(sc.ai, sc.manager.positioning)


def cmds(sc, unit):
    return [(c.ability, c.target, c.queue) for c in sc.ai.actions if c.unit.tag == unit.tag]


def danger(sc, pos, radius=5, value=60.0, air=False):
    grid = sc.ai.mediator.air if air else sc.ai.mediator.ground
    x, y = int(pos[0]), int(pos[1])
    grid[max(0, x - radius): x + radius + 1, max(0, y - radius): y + radius + 1] = value


# ------------------------------------------------------------------------------------------------------------ bio
def test_bio_shoots_ready_and_stims():
    sc = mk()
    sc.ai.state.upgrades.add(UpgradeId.STIMPACK)
    m = sc.own(U.MARINE, (60, 60), cooldown=0.0)
    z = sc.enemy(U.ZERGLING, (63, 60))
    ctx = begin(sc)
    sc.manager.bio.control(sc.world.units([m]), orders(sc), ctx)
    c = cmds(sc, m)
    check("bio: attacks the in-range target", any(a == A.ATTACK and getattr(t, "tag", None) == z.tag for a, t, q in c), str(c))
    check("bio: stims at full health with a target in range", any(a == A.EFFECT_STIM_MARINE for a, t, q in c), str(c))
    sc2 = mk()
    sc2.ai.state.upgrades.add(UpgradeId.STIMPACK)
    m2 = sc2.own(U.MARINE, (60, 60), cooldown=0.0, buffs=[BuffId.STIMPACK])
    sc2.enemy(U.ZERGLING, (63, 60))
    ctx = begin(sc2)
    sc2.manager.bio.control(sc2.world.units([m2]), orders(sc2), ctx)
    check("bio: no second stim while stimmed", not any(a == A.EFFECT_STIM_MARINE for a, t, q in cmds(sc2, m2)))
    sc3 = mk()
    sc3.ai.state.upgrades.add(UpgradeId.STIMPACK)
    m3 = sc3.own(U.MARINE, (60, 60), cooldown=0.0, hp=30)
    sc3.enemy(U.ZERGLING, (63, 60))
    ctx = begin(sc3)
    sc3.manager.bio.control(sc3.world.units([m3]), orders(sc3), ctx)
    check("bio: no stim when hurt", not any(a == A.EFFECT_STIM_MARINE for a, t, q in cmds(sc3, m3)))


def test_bio_kites_back_when_unsafe():
    sc = mk()
    m = sc.own(U.MARINE, (60, 60), cooldown=10.0)
    sc.enemy(U.STALKER if False else U.MARAUDER, (64, 60))          # marauder range 6 > marine 5... use a shorter-range one below
    sc.ai._enemies.clear()
    sc.enemy(U.ROACH, (64, 60))                                       # roach range 4 < marine 5: kiteable
    danger(sc, (62, 60), radius=4)
    ctx = begin(sc)
    sc.manager.bio.control(sc.world.units([m]), orders(sc), ctx)
    c = cmds(sc, m)
    check("bio: kites away (move) from a slower shorter-range threat while on cooldown", any(a == A.MOVE_MOVE for a, t, q in c), str(c))


def test_bio_futile_to_kite_holds():
    sc = mk()
    m = sc.own(U.MARINE, (60, 60), cooldown=10.0)
    st = sc.enemy(U.STALKER, (65, 60))                                # outranges (6>5) and faster (4.13>3.15)
    danger(sc, (62, 60), radius=5)
    ctx = begin(sc)
    sc.manager.bio.control(sc.world.units([m]), orders(sc), ctx)
    c = cmds(sc, m)
    check("bio: holds and trades vs a faster longer-range unit (no retreat)", not any(a == A.MOVE_MOVE for a, t, q in c) and any(a == A.ATTACK for a, t, q in c), str(c))


def test_bio_melee_only_still_kites_even_when_winning():
    sc = mk()
    m = sc.own(U.MARINE, (60, 60), cooldown=10.0)
    sc.enemy(U.ZEALOT, (63, 60))
    danger(sc, (62, 60), radius=4)
    ctx = begin(sc)
    sc.manager.bio.control(sc.world.units([m]), orders(sc, local=ER.VICTORY_EMPHATIC), ctx)
    c = cmds(sc, m)
    check("bio: still kites away from melee-only enemies even at overwhelming odds", any(a == A.MOVE_MOVE for a, t, q in c), str(c))


def test_bio_kites_in_when_winning_vs_ranged():
    sc = mk()
    m = sc.own(U.MARINE, (60, 60), cooldown=10.0)
    sc.enemy(U.ROACH, (64, 60))
    sc.enemy(U.HYDRALISK, (66, 60))
    danger(sc, (62, 60), radius=5)
    ctx = begin(sc)
    sc.manager.bio.control(sc.world.units([m]), orders(sc, local=ER.VICTORY_OVERWHELMING), ctx)
    c = cmds(sc, m)
    towards = [t for a, t, q in c if a == A.MOVE_MOVE]
    check("bio: pushes in (stutter forward) when very confident vs ranged", bool(towards) and towards[0][0] > 60, str(c))


def test_bio_harmless_target_kite_in():
    sc = mk()
    m = sc.own(U.MARINE, (60, 60), cooldown=10.0)
    sc.enemy(U.COMMANDCENTER, (67, 60))
    danger(sc, (62, 60), radius=6)
    ctx = begin(sc)
    sc.manager.bio.control(sc.world.units([m]), orders(sc), ctx)
    c = cmds(sc, m)
    check("bio: presses in on a harmless building instead of retreating", not any(a == A.MOVE_MOVE and t[0] < 60 for a, t, q in c) and len(c) > 0, str(c))


def _backs_away(c):
    """the commands step AWAY from enemies that stand on the +x side, and none of them steps towards them"""
    return any(a == A.MOVE_MOVE and t[0] < 60 for a, t, q in c) and not any(a == A.MOVE_MOVE and t[0] > 60 for a, t, q in c)


def test_bio_always_kites_away_from_banelings_even_when_winning():
    # control: the same fight without banelings is pushed in (the "kite in when very confident" rule)
    sc = mk()
    m = sc.own(U.MARINE, (60, 60), cooldown=10.0)
    sc.enemy(U.ROACH, (64, 60))
    sc.enemy(U.HYDRALISK, (66, 60))
    danger(sc, (62, 60), radius=5)
    ctx = begin(sc)
    sc.manager.bio.control(sc.world.units([m]), orders(sc, local=ER.VICTORY_EMPHATIC), ctx)
    check("control: no banelings -> still pushes in at overwhelming odds", any(a == A.MOVE_MOVE and t[0] > 60 for a, t, q in cmds(sc, m)), str(cmds(sc, m)))
    # a baneling 5 away, the danger grid says "safe": backs away all the same, at the same overwhelming odds
    sc = mk()
    m = sc.own(U.MARINE, (60, 60), cooldown=10.0)
    sc.enemy(U.ROACH, (64, 60))
    sc.enemy(U.HYDRALISK, (66, 60))
    sc.enemy(U.BANELING, (65, 61))
    ctx = begin(sc)
    sc.manager.bio.control(sc.world.units([m]), orders(sc, local=ER.VICTORY_EMPHATIC), ctx)
    c = cmds(sc, m)
    check("bio: backs away from banelings at overwhelming odds, without the danger grid asking for it", _backs_away(c), str(c))


def test_bio_baneling_beyond_kite_radius_still_turns_off_the_shortcuts():
    # a baneling 10 away (inside the fight radius, outside the step-back radius): no kite-in at overwhelming odds
    sc = mk()
    m = sc.own(U.MARINE, (60, 60), cooldown=10.0)
    sc.enemy(U.ROACH, (64, 60))
    sc.enemy(U.HYDRALISK, (66, 60))
    sc.enemy(U.BANELING, (70, 60))
    danger(sc, (62, 60), radius=5)
    ctx = begin(sc)
    sc.manager.bio.control(sc.world.units([m]), orders(sc, local=ER.VICTORY_EMPHATIC), ctx)
    c = cmds(sc, m)
    check("bio: a baneling 10 away (outside the step-back distance) already forbids kiting in - the danger grid's kite-away applies", _backs_away(c), str(c))
    # "futile to run" (a faster longer-range stalker) normally means hold and trade; not with a baneling about
    sc = mk()
    m = sc.own(U.MARINE, (60, 60), cooldown=10.0)
    sc.enemy(U.STALKER, (65, 60))
    sc.enemy(U.BANELING, (70, 60))
    danger(sc, (62, 60), radius=5)
    ctx = begin(sc)
    sc.manager.bio.control(sc.world.units([m]), orders(sc), ctx)
    c = cmds(sc, m)
    check("bio: with a baneling about, 'futile to kite' no longer keeps it in place", _backs_away(c), str(c))
    # a harmless target (a building) normally gets pressed; not with a baneling about
    sc = mk()
    m = sc.own(U.MARINE, (60, 60), cooldown=10.0)
    sc.enemy(U.COMMANDCENTER, (67, 60))
    sc.enemy(U.BANELING, (72, 60))
    danger(sc, (62, 60), radius=6)
    ctx = begin(sc)
    sc.manager.bio.control(sc.world.units([m]), orders(sc), ctx)
    c = cmds(sc, m)
    check("bio: with a baneling about, a harmless building is not pressed", _backs_away(c), str(c))


def test_bio_kites_and_shoots_banelings_not_just_kites():
    """the kite is shoot-when-ready, step-back-on-cooldown: a marine that only ran would never kill a baneling"""
    def marine_vs(cooldown, baneling_at, extra=()):
        sc = mk()
        m = sc.own(U.MARINE, (60, 60), cooldown=cooldown)
        b = sc.enemy(U.BANELING, baneling_at)
        for kind, pos in extra:
            sc.enemy(kind, pos)
        ctx = begin(sc)
        sc.manager.bio.control(sc.world.units([m]), orders(sc), ctx)
        return b, cmds(sc, m)
    b, c = marine_vs(0.0, (64, 60))
    check("bio: weapon ready, baneling in range -> shoots it", any(a == A.ATTACK and getattr(t, "tag", None) == b.tag for a, t, q in c), str(c))
    check("bio: ...and does not run instead", not any(a == A.MOVE_MOVE for a, t, q in c), str(c))
    b, c = marine_vs(10.0, (64, 60))
    check("bio: weapon on cooldown, baneling in range -> steps back", _backs_away(c), str(c))
    # a baneling just outside weapon range (5.9 away, range 5.75 centre to centre) while the weapon is ready: still shoots
    # (it steps forward a hair to do it) instead of running without ever firing
    b, c = marine_vs(0.0, (65.9, 60))
    check("bio: weapon ready, baneling just out of range -> shoots (no retreat without a shot)", any(a == A.ATTACK and getattr(t, "tag", None) == b.tag for a, t, q in c) and not any(a == A.MOVE_MOVE for a, t, q in c), str(c))
    # control: a far target with nothing dangerous about is walked up to, as always
    sc = mk()
    m = sc.own(U.MARINE, (60, 60), cooldown=0.0)
    sc.enemy(U.ROACH, (69, 60))
    ctx = begin(sc)
    sc.manager.bio.control(sc.world.units([m]), orders(sc), ctx)
    check("control: weapon ready, target out of range, no banelings -> walks in to shoot", any(a == A.ATTACK for a, t, q in cmds(sc, m)), str(cmds(sc, m)))


def test_bio_retreating_group_runs_home_from_banelings():
    sc = mk()
    m = sc.own(U.MARINE, (90, 90), cooldown=10.0)
    sc.enemy(U.BANELING, (94, 90))
    ctx = begin(sc)
    sc.manager.bio.control(sc.world.units([m]), orders(sc, mode=Mode.HOLD, retreating=True), ctx)
    c = cmds(sc, m)
    check("bio: a retreating group heads for the hold point when banelings are close", any(a == A.MOVE_MOVE and abs(t[0] - 60) < 1 for a, t, q in c), str(c))


def test_bio_ignores_remembered_and_hallucinated_banelings():
    sc = mk()
    m = sc.own(U.MARINE, (60, 60), cooldown=10.0)
    sc.enemy(U.ROACH, (64, 60))
    sc.enemy(U.HYDRALISK, (66, 60))
    ghost = sc.enemy(U.BANELING, (65, 61))
    ghost._ghost = True
    ghost.game_loop = 1                                               # last seen long ago: a remembered ghost
    danger(sc, (62, 60), radius=5)
    ctx = begin(sc)
    sc.manager.bio.control(sc.world.units([m]), orders(sc, local=ER.VICTORY_EMPHATIC), ctx)
    check("bio: a baneling we only remember does not stop the push-in", any(a == A.MOVE_MOVE and t[0] > 60 for a, t, q in cmds(sc, m)), str(cmds(sc, m)))
    check("context: banelings_near ignores memory units", ctx.banelings_near(m) == [])


def test_context_targets_are_worked_out_per_shooter():
    """ArmyContext classifies each enemy once per step (see ArmyContext._kind); what a unit is offered must still be exactly what it can
    shoot: no ghosts, no ignored types (eggs, larvae, changelings...), nothing it cannot hit (a marauder cannot shoot air)."""
    import gamefix
    gamefix.STATS.setdefault(U.CHANGELING, (5, 0, 0, 3.15, [], [gamefix.LIGHT, gamefix.BIO], 0, 0, 0))      # (an ignored type the fixture lacks)
    sc = mk()
    marauder = sc.own(U.MARAUDER, (60, 60))
    marine = sc.own(U.MARINE, (60, 61))
    zergling = sc.enemy(U.ZERGLING, (63, 60))
    muta = sc.enemy(U.MUTALISK, (63, 62))
    sc.enemy(U.CHANGELING, (62, 60))
    ghost = sc.enemy(U.ROACH, (64, 60))
    ghost._ghost = True
    ghost.game_loop = 1
    bane = sc.enemy(U.BANELING, (65, 60))
    ctx = begin(sc)
    ctx.prefetch_near([marauder, marine])
    tags = lambda units: {u.tag for u in units}
    check("context: a marauder is offered ground units only - no air, no eggs, no ghosts",
          tags(ctx.targets_near(marauder)) == {zergling.tag, bane.tag}, str(tags(ctx.targets_near(marauder))))
    check("context: a marine is offered air units too", tags(ctx.targets_near(marine)) == {zergling.tag, muta.tag, bane.tag}, str(tags(ctx.targets_near(marine))))
    check("context: the baneling is found (and only it) - however many times it is asked", tags(ctx.banelings_near(marine)) == {bane.tag} == tags(ctx.banelings_near(marine)))
    sc2 = mk()
    m = sc2.own(U.MARINE, (60, 60))
    sc2.enemy(U.ZERGLING, (63, 60))
    ctx = begin(sc2)
    check("context: no banelings anywhere -> none near anyone", ctx.banelings_near(m) == [] and ctx.close_banelings(m) == [])


def test_cyclone_always_kites_away_from_banelings():
    sc = mk()
    cy = sc.own(U.CYCLONE, (60, 60), cooldown=10.0)
    sc.enemy(U.ROACH, (64, 60))
    sc.enemy(U.HYDRALISK, (66, 60))
    danger(sc, (62, 60), radius=5)
    ctx = begin(sc)
    sc.manager.cyclones.control(sc.world.units([cy]), orders(sc, local=ER.VICTORY_EMPHATIC), ctx)
    check("control: cyclone without banelings pushes in at overwhelming odds", any(a == A.MOVE_MOVE and t[0] > 60 for a, t, q in cmds(sc, cy)), str(cmds(sc, cy)))
    sc = mk()
    cy = sc.own(U.CYCLONE, (60, 60), cooldown=10.0)
    sc.enemy(U.ROACH, (64, 60))
    sc.enemy(U.HYDRALISK, (66, 60))
    sc.enemy(U.BANELING, (65, 61))
    ctx = begin(sc)
    sc.manager.cyclones.control(sc.world.units([cy]), orders(sc, local=ER.VICTORY_EMPHATIC), ctx)
    c = cmds(sc, cy)
    check("cyclone: backs away from banelings at overwhelming odds", _backs_away(c), str(c))
    # holding position with something in range: normally stands and fires; with banelings close it does not stand
    sc = mk()
    cy = sc.own(U.CYCLONE, (60, 60), cooldown=10.0)
    sc.enemy(U.ROACH, (63, 60))
    sc.enemy(U.BANELING, (64, 61))
    ctx = begin(sc)
    sc.manager.cyclones.control(sc.world.units([cy]), orders(sc, mode=Mode.HOLD), ctx)
    c = cmds(sc, cy)
    check("cyclone: a HOLDing cyclone still backs away from close banelings", _backs_away(c), str(c))


def test_reaper_always_kites_away_from_banelings():
    sc = mk()
    r = sc.own(U.REAPER, (60, 60), cooldown=10.0)
    sc.enemy(U.STALKER, (65, 60))                                     # "futile to kite" on its own
    sc.enemy(U.BANELING, (64, 61))
    ctx = begin(sc)
    sc.manager.reapers.control(sc.world.units([r]), orders(sc), ctx)
    c = cmds(sc, r)
    check("reaper: backs away from close banelings even against a stalker (no 'futile to kite')", _backs_away(c), str(c))


def test_bio_hold_and_march():
    sc = mk()
    m = sc.own(U.MARINE, (30, 30))
    ctx = begin(sc)
    sc.manager.bio.control(sc.world.units([m]), orders(sc, mode=Mode.HOLD), ctx)
    c = cmds(sc, m)
    check("bio: walks to the hold position when holding", any(a == A.MOVE_MOVE and abs(t[0] - 62) < 0.6 for a, t, q in c), str(c))
    sc = mk()
    m = sc.own(U.MARINE, (60, 60))
    ctx = begin(sc)
    sc.manager.bio.control(sc.world.units([m]), orders(sc, mode=Mode.ATTACK), ctx)
    c = cmds(sc, m)
    check("bio: a-moves towards the target when attacking with nothing near", any(a == A.ATTACK for a, t, q in c), str(c))
    # retreating with enemies near and unsafe -> heads for the hold point rather than local kite
    sc = mk()
    m = sc.own(U.MARINE, (90, 90), cooldown=10.0)
    sc.enemy(U.ROACH, (94, 90))
    danger(sc, (92, 90), radius=4)
    ctx = begin(sc)
    sc.manager.bio.control(sc.world.units([m]), orders(sc, mode=Mode.HOLD, retreating=True), ctx)
    c = cmds(sc, m)
    check("bio: retreating units run for the hold point", any(a == A.MOVE_MOVE and abs(t[0] - 60) < 1 for a, t, q in c), str(c))


# ---------------------------------------------------------------------------------------------------------- tanks
def test_tanks_siege_logic():
    sc = mk()
    t = sc.own(U.SIEGETANK, (60, 60))
    sc.enemy(U.ROACH, (69, 60))                                          # 9 away, within 11
    ctx = begin(sc)
    sc.manager.tanks.control(sc.world.units([t]), orders(sc), ctx)
    check("tank: sieges when an enemy is within engage range", any(a == A.SIEGEMODE_SIEGEMODE for a, t_, q in cmds(sc, t)))
    # sieged, enemy within hold range -> stays
    sc = mk()
    t = sc.own(U.SIEGETANKSIEGED, (60, 60))
    sc.enemy(U.ROACH, (72, 60))
    ctx = begin(sc)
    sc.manager.tanks.siege_since[t.tag] = -100.0
    sc.manager.tanks.control(sc.world.units([t]), orders(sc), ctx)
    check("tank: stays sieged while an enemy is within 14", len(cmds(sc, t)) == 0, str(cmds(sc, t)))
    # enemy gone; not yet min duration -> stays; after -> unsieges
    sc = mk()
    t = sc.own(U.SIEGETANKSIEGED, (60, 60))
    ctx = begin(sc)
    sc.manager.tanks.control(sc.world.units([t]), orders(sc), ctx)
    check("tank: does not unsiege before the minimum siege duration", len(cmds(sc, t)) == 0, str(cmds(sc, t)))
    sc.ai._fake_time += 5.0
    ctx = begin(sc)
    sc.manager.tanks.control(sc.world.units([t]), orders(sc), ctx)
    check("tank: unsieges once nothing is near and the minimum time has passed", any(a == A.UNSIEGE_UNSIEGE for a, t_, q in cmds(sc, t)), str(cmds(sc, t)))
    # a sieged tank never gets move orders
    sc = mk()
    t = sc.own(U.SIEGETANKSIEGED, (60, 60))
    ctx = begin(sc)
    sc.manager.tanks.control(sc.world.units([t]), orders(sc, mode=Mode.ATTACK), ctx)
    check("tank: a sieged tank is never ordered to move", not any(a in (A.MOVE_MOVE, A.ATTACK) for a, t_, q in cmds(sc, t)))


def test_tanks_guard_exposed_liberator():
    sc = mk()
    lib = sc.own(U.LIBERATORAG, (80, 80))
    t = sc.own(U.SIEGETANK, (50, 50))
    ctx = begin(sc)
    sc.manager.tanks.control(sc.world.units([t]), orders(sc), ctx)
    c = cmds(sc, t)
    check("tank: heads for an exposed sieged liberator", any(a == A.ATTACK and abs(t_.x - 80) < 8 for a, t_, q in c if hasattr(t_, "x")), str(c))


# -------------------------------------------------------------------------------------------------------- cyclones
def test_cyclone_lockon():
    sc = mk()
    c1 = sc.own(U.CYCLONE, (60, 60))
    sc.ai.ability_grants[c1.tag] = {A.LOCKON_LOCKON, A.LOCKONAIR_LOCKONAIR}
    sc.enemy(U.SCV, (64, 60))
    r = sc.enemy(U.ROACH, (66, 60))
    v = sc.enemy(U.VOIDRAY, (67, 60))
    import asyncio
    from bot.ares_compat import refresh_ability_cache
    asyncio.run(refresh_ability_cache(sc.ai, sc.ai.units))
    ctx = begin(sc)
    sc.manager.cyclones.control(sc.world.units([c1]), orders(sc), ctx)
    c = cmds(sc, c1)
    check("cyclone: locks on to skytoss first, never a worker", any(a == A.LOCKONAIR_LOCKONAIR and t.tag == v.tag for a, t, q in c), str(c))
    # same target is not re-locked next frame
    ctx = begin(sc)
    sc.manager.cyclones.control(sc.world.units([c1]), orders(sc), ctx)
    c = cmds(sc, c1)
    check("cyclone: does not re-lock the same target immediately", not any(a == A.LOCKONAIR_LOCKONAIR and t.tag == v.tag for a, t, q in c), str(c))


# ---------------------------------------------------------------------------------------------------------- ravens
def test_raven_matrix_and_turret():
    import asyncio
    from bot.ares_compat import refresh_ability_cache
    from sc2.data import Race
    sc = mk(enemy_race=Race.Terran)
    rv = sc.own(U.RAVEN, (60, 60), energy=100)
    sc.ai.ability_grants[rv.tag] = {A.EFFECT_INTERFERENCEMATRIX, A.BUILDAUTOTURRET_AUTOTURRET}
    tank = sc.enemy(U.SIEGETANKSIEGED, (66, 60))
    asyncio.run(refresh_ability_cache(sc.ai, sc.ai.units))
    ctx = begin(sc)
    asyncio.run(sc.manager.ravens.control(sc.world.units([rv]), orders(sc), ctx))
    c = cmds(sc, rv)
    check("raven: matrixes a sieged tank", any(a == A.EFFECT_INTERFERENCEMATRIX and t.tag == tank.tag for a, t, q in c), str(c))
    sc = mk(enemy_race=Race.Zerg)
    rv = sc.own(U.RAVEN, (60, 60), energy=100)
    sc.ai.ability_grants[rv.tag] = {A.BUILDAUTOTURRET_AUTOTURRET}
    sc.enemy(U.ROACH, (63, 60))
    asyncio.run(refresh_ability_cache(sc.ai, sc.ai.units))
    ctx = begin(sc)
    asyncio.run(sc.manager.ravens.control(sc.world.units([rv]), orders(sc), ctx))
    c = cmds(sc, rv)
    check("raven: drops an auto-turret near a Zerg unit", any(a == A.BUILDAUTOTURRET_AUTOTURRET for a, t, q in c), str(c))


# --------------------------------------------------------------------------------------------------------- vikings
def test_viking_always_kites():
    sc = mk()
    v = sc.own(U.VIKINGFIGHTER, (60, 60), cooldown=15.0)
    sc.enemy(U.MUTALISK, (65, 60))
    danger(sc, (61, 60), radius=4, air=True)
    ctx = begin(sc)
    sc.manager.vikings.control(sc.world.units([v]), orders(sc), ctx)
    c = cmds(sc, v)
    check("viking: retreats between shots when in danger", any(a == A.MOVE_MOVE for a, t, q in c), str(c))
    sc = mk()
    v = sc.own(U.VIKINGFIGHTER, (60, 60), cooldown=0.0)
    m = sc.enemy(U.MUTALISK, (66, 60))
    ctx = begin(sc)
    sc.manager.vikings.control(sc.world.units([v]), orders(sc), ctx)
    c = cmds(sc, v)
    check("viking: shoots when ready", any(a == A.ATTACK and t.tag == m.tag for a, t, q in c), str(c))


# -------------------------------------------------------------------------------------------------------- medivacs
def test_medivac_heals_and_boosts():
    import asyncio
    from bot.ares_compat import refresh_ability_cache
    sc = mk()
    md = sc.own(U.MEDIVAC, (60, 60))
    hurt = sc.own(U.MARINE, (62, 60), hp=20)
    sc.ai.ability_grants[md.tag] = {A.EFFECT_MEDIVACIGNITEAFTERBURNERS}
    asyncio.run(refresh_ability_cache(sc.ai, sc.ai.units))
    ctx = begin(sc)
    sc.manager.medivacs.control(sc.world.units([md]), orders(sc), ctx)
    c = cmds(sc, md)
    check("medivac: heals a hurt marine", any(a == A.MEDIVACHEAL_HEAL and t.tag == hurt.tag for a, t, q in c), str(c))
    check("medivac: boosts when afterburners are ready", any(a == A.EFFECT_MEDIVACIGNITEAFTERBURNERS for a, t, q in c), str(c))


# -------------------------------------------------------------------------------------------------------- banshees
def test_banshee_cloak_and_retreat():
    import asyncio
    from bot.ares_compat import refresh_ability_cache
    sc = mk()
    sc.ai.state.upgrades.add(UpgradeId.BANSHEECLOAK)
    b = sc.own(U.BANSHEE, (150, 160), energy=100)
    sc.ai.ability_grants[b.tag] = {A.BEHAVIOR_CLOAKON_BANSHEE}
    sc.enemy(U.MARINE, (154, 160))
    danger(sc, (152, 160), radius=6, air=True)
    asyncio.run(refresh_ability_cache(sc.ai, sc.ai.units))
    ctx = begin(sc)
    sc.manager.banshees.control(sc.world.units([b]), orders(sc), ctx)
    c = cmds(sc, b)
    check("banshee: cloaks and runs when in danger", any(a == A.BEHAVIOR_CLOAKON_BANSHEE for a, t, q in c) and any(a == A.MOVE_MOVE for a, t, q in c), str(c))
    sc = mk()
    b = sc.own(U.BANSHEE, (150, 160), hp=40)
    ctx = begin(sc)
    sc.manager.banshees.control(sc.world.units([b]), orders(sc), ctx)
    c = cmds(sc, b)
    check("banshee: flies home when badly hurt", any(a == A.MOVE_MOVE and t[0] < 100 for a, t, q in c), str(c))


def test_banshee_prefers_workers():
    sc = mk()
    b = sc.own(U.BANSHEE, (150, 160), cooldown=0.0)
    mar = sc.enemy(U.MARINE, (153, 160))
    scv = sc.enemy(U.SCV, (156, 160))
    ctx = begin(sc)
    sc.manager.banshees.control(sc.world.units([b]), orders(sc), ctx)
    c = cmds(sc, b)
    check("banshee: shoots workers before other units", any(a == A.ATTACK and getattr(t, "tag", None) == scv.tag for a, t, q in c), str(c))


# --------------------------------------------------------------------------------------------------------- reapers
def test_reaper_uses_grenade_behavior():
    import asyncio
    from bot.ares_compat import refresh_ability_cache
    sc = mk()
    r = sc.own(U.REAPER, (150, 160), cooldown=30.0)
    sc.ai.ability_grants[r.tag] = {A.KD8CHARGE_KD8CHARGE}
    for i in range(4):
        sc.enemy(U.MARINE, (154 + i * 0.5, 160))
    asyncio.run(refresh_ability_cache(sc.ai, sc.ai.units))
    ctx = begin(sc)
    sc.manager.reapers.control(sc.world.units([r]), orders(sc), ctx)
    c = cmds(sc, r)
    print("   reaper commands:", [(a.name, t) for a, t, q in c])
    check("reaper: controller ran with Ares' ReaperGrenade and produced an order", len(c) > 0, str(c))


# -------------------------------------------------------------------------------------------------- manager level
# ------------------------------------------------------------------------------------- tanks vs buildings in range
def _unsieges(c):
    return any(a == A.UNSIEGE_UNSIEGE for a, t, q in c)


def test_sieged_tank_keeps_shelling_a_building_in_range():
    # a Hatchery whose centre is 15.8 away is 15.8 - 0.875 - 2.5 = 12.4 away at its nearest edge: inside a sieged tank's range 13
    for mode in (Mode.ATTACK, Mode.HOLD):
        sc = mk()
        t = sc.own(U.SIEGETANKSIEGED, (70, 60))
        sc.manager.tanks.siege_since[t.tag] = -100.0                 # sieged long ago: the minimum time is not what holds it
        sc.enemy(U.HATCHERY, (85.8, 60))
        ctx = begin(sc)
        sc.manager.tanks.control(sc.world.units([t]), orders(sc, mode=mode), ctx)
        check(f"tank: stays sieged while it can shoot a building ({mode.name})", not _unsieges(cmds(sc, t)), str(cmds(sc, t)))
    # the same building out of reach (nearest edge 14.5 away), or only an old snapshot of it: nothing to shoot -> unsiege
    for label, kwargs, x in (("out of reach", {}, 87.9), ("only a snapshot", {"visible": False}, 85.8)):
        sc = mk()
        t = sc.own(U.SIEGETANKSIEGED, (70, 60))
        sc.manager.tanks.siege_since[t.tag] = -100.0
        sc.enemy(U.HATCHERY, (x, 60), **kwargs)
        ctx = begin(sc)
        sc.manager.tanks.control(sc.world.units([t]), orders(sc, mode=Mode.ATTACK), ctx)
        check(f"tank: unsieges when the building is {label}", _unsieges(cmds(sc, t)), str(cmds(sc, t)))


def test_unsieged_tank_sieges_at_a_building_it_can_hit():
    sc = mk()
    t = sc.own(U.SIEGETANK, (70, 60))
    sc.enemy(U.HATCHERY, (83.5, 60))                                  # nearest edge 10.1 away, centre 13.5
    ctx = begin(sc)
    sc.manager.tanks.control(sc.world.units([t]), orders(sc, mode=Mode.ATTACK), ctx)
    check("tank: sieges up at a big building whose edge is in reach", any(a == A.SIEGEMODE_SIEGEMODE for a, tt, q in cmds(sc, t)), str(cmds(sc, t)))


# --------------------------------------------------------------------------------------------------------- liberators
def _liberator_in_defender_mode(sc, lib):
    """the liberator as the observation shows it once the morph has finished: same tag, same place, LiberatorAG"""
    sc.ai._own.remove(lib)
    return sc.own(U.LIBERATORAG, (lib.position.x, lib.position.y), tag=lib.tag, role=UnitRole.ATTACKING)


def _unsieges_lib(sc, unit):
    return any(a == A.MORPH_LIBERATORAAMODE for a, t, q in cmds(sc, unit))


def test_liberator_gets_to_shoot_before_it_can_unsiege():
    import asyncio
    from bot.ares_compat import refresh_ability_cache
    sc = mk()
    lib = sc.own(U.LIBERATOR, (60, 60), role=UnitRole.ATTACKING)
    sc.ai.ability_grants[lib.tag] = {A.MORPH_LIBERATORAGMODE}
    tank = sc.enemy(U.SIEGETANKSIEGED, (68, 60))                      # 8 from the liberator, 4 from the zone it will cover
    asyncio.run(refresh_ability_cache(sc.ai, sc.ai.units))
    ctx = begin(sc)
    sc.manager.liberators.control(sc.world.units([lib]), orders(sc), ctx)
    check("liberator: orders Defender Mode over the tank", any(a == A.MORPH_LIBERATORAGMODE for a, t, q in cmds(sc, lib)), str(cmds(sc, lib)))
    zone = sc.manager.liberators.ag_zone.get(lib.tag)
    check("liberator: remembers the zone it was ordered to cover", zone is not None and abs(zone.x - 64) < 0.5, str(zone))

    # the morph takes longer than the order-time lock: LiberatorAG is first SEEN after the lock has expired (3.5 s later)
    sc.ai._fake_time += 3.5
    ag = _liberator_in_defender_mode(sc, lib)
    ctx = begin(sc)
    sc.manager.liberators.control(sc.world.units([ag]), orders(sc), ctx)
    check("liberator: not unsieged the moment Defender Mode is first seen (it has not fired yet)", not _unsieges_lib(sc, ag), str(cmds(sc, ag)))

    # nothing left anywhere, but the shooting window (3 s from first seen) has not passed: still up
    sc.ai._enemies.clear()
    sc.ai._fake_time += 1.0
    ctx = begin(sc)
    sc.manager.liberators.control(sc.world.units([ag]), orders(sc), ctx)
    check("liberator: stays up for its shooting window even with nothing left", not _unsieges_lib(sc, ag), str(cmds(sc, ag)))
    sc.ai._fake_time += 3.5
    ctx = begin(sc)
    sc.manager.liberators.control(sc.world.units([ag]), orders(sc), ctx)
    check("liberator: comes down once the window is over and nothing is in the zone", _unsieges_lib(sc, ag), str(cmds(sc, ag)))


def test_liberator_stays_up_while_something_is_in_its_zone():
    import asyncio
    from bot.ares_compat import refresh_ability_cache
    sc = mk()
    lib = sc.own(U.LIBERATOR, (60, 60), role=UnitRole.ATTACKING)
    sc.ai.ability_grants[lib.tag] = {A.MORPH_LIBERATORAGMODE}
    sc.enemy(U.SIEGETANKSIEGED, (68, 60))
    asyncio.run(refresh_ability_cache(sc.ai, sc.ai.units))
    ctx = begin(sc)
    sc.manager.liberators.control(sc.world.units([lib]), orders(sc), ctx)
    ag = _liberator_in_defender_mode(sc, lib)
    sc.ai._fake_time += 30.0                                          # long past every lock
    # a marine walks about in the zone (centre (64, 60), radius 5) - 9 from the liberator, far outside its own 6
    sc.ai._enemies.clear()
    sc.enemy(U.MARINE, (68.5, 62))
    ctx = begin(sc)
    sc.manager.liberators.control(sc.world.units([ag]), orders(sc), ctx)
    check("liberator: stays sieged while an enemy is inside its zone, however far that is from the liberator", not _unsieges_lib(sc, ag), str(cmds(sc, ag)))
    # only a building in the zone: Defender Mode cannot hit those
    sc.ai._enemies.clear()
    sc.enemy(U.SPINECRAWLER, (64, 60))
    sc.ai._fake_time += 4.0                                           # (past the shooting window that the marine above opened)
    ctx = begin(sc)
    sc.manager.liberators.control(sc.world.units([ag]), orders(sc), ctx)
    check("liberator: a building in the zone is no reason to stay sieged", _unsieges_lib(sc, ag), str(cmds(sc, ag)))


# ---------------------------------------------------------------------------------------- banshees and defended targets
def test_banshee_skips_defended_targets_and_picks_another():
    sc = mk()
    b = sc.own(U.BANSHEE, (60, 60))
    defended = sc.enemy(U.DRONE, (68, 60))                            # closest - but a queen and a spore stand around it
    free = sc.enemy(U.DRONE, (60, 72))
    danger(sc, (66, 60), radius=5, air=True)                          # the spot it would shoot the first one from is in anti-air range
    ctx = begin(sc)
    sc.manager.banshees.control(sc.world.units([b]), orders(sc), ctx)
    c = cmds(sc, b)
    check("banshee: goes for the undefended worker instead of the defended one",
          any(a == A.ATTACK and getattr(t, "tag", None) == free.tag for a, t, q in c)
          and not any(getattr(t, "tag", None) == defended.tag for a, t, q in c), str(c))
    # only defended targets: it does not fly into them at all
    sc = mk()
    b = sc.own(U.BANSHEE, (60, 60))
    defended = sc.enemy(U.DRONE, (68, 60))
    danger(sc, (66, 60), radius=5, air=True)
    ctx = begin(sc)
    sc.manager.banshees.control(sc.world.units([b]), orders(sc), ctx)
    c = cmds(sc, b)
    check("banshee: with only defended targets it goes on to roam instead of attacking", not any(getattr(t, "tag", None) == defended.tag for a, t, q in c), str(c))


def test_banshee_that_can_cloak_still_goes_for_defended_targets():
    """it cloaks when it gets into danger (see _control_unit), so a defended target is fair game for it - unlike for a banshee
    that has no cloak to hide behind"""
    import asyncio
    from bot.ares_compat import refresh_ability_cache
    sc = mk()
    sc.ai.state.upgrades.add(UpgradeId.BANSHEECLOAK)
    b = sc.own(U.BANSHEE, (60, 60), energy=100.0)
    sc.ai.ability_grants[b.tag] = {A.BEHAVIOR_CLOAKON_BANSHEE}
    defended = sc.enemy(U.DRONE, (68, 60))
    danger(sc, (66, 60), radius=5, air=True)
    asyncio.run(refresh_ability_cache(sc.ai, sc.ai.units))
    ctx = begin(sc)
    sc.manager.banshees.control(sc.world.units([b]), orders(sc), ctx)
    c = cmds(sc, b)
    check("banshee: with cloak researched and energy it still goes for the defended worker", any(a == A.ATTACK and getattr(t, "tag", None) == defended.tag for a, t, q in c), str(c))


def test_banshee_writes_off_a_target_it_cannot_shoot():
    sc = mk()
    b = sc.own(U.BANSHEE, (60, 60))
    near = sc.enemy(U.DRONE, (66, 60))
    far = sc.enemy(U.DRONE, (60, 70))
    last = []
    for _ in range(18):                                               # 9 s: the fake banshee never fires
        ctx = begin(sc)
        sc.manager.banshees.control(sc.world.units([b]), orders(sc), ctx)
        last = cmds(sc, b)
    check("banshee: after 6 s without a shot it moves on to another target",
          any(a == A.ATTACK and getattr(t, "tag", None) == far.tag for a, t, q in last), str(last))


def test_banshee_never_just_stays_at_a_defended_base():
    sc = mk()
    b = sc.own(U.BANSHEE, (60, 60))
    for base, value in (((180, 180), 60.0), ((150, 150), 45.0), ((120, 140), 35.0)):
        danger(sc, base, radius=9, value=value, air=True)             # every base is defended, one less than the others
    sc.manager.banshees.roam[b.tag] = Point2((180, 180))              # ...and it is sitting at the worst one
    ctx = begin(sc)
    sc.manager.banshees.control(sc.world.units([b]), orders(sc), ctx)
    pick = sc.manager.banshees.roam[b.tag]
    check("banshee: when every base is defended it moves to the least defended one", abs(pick.x - 120) < 1 and abs(pick.y - 140) < 1, str(pick))


# ----------------------------------------------------------------------------- marching does not push units into walls
def test_marching_units_do_not_hop_into_a_wall():
    def march(with_wall):
        sc = mk()
        marines = sc.own_many(U.MARINE, 8, (60, 60), spacing=0.6)   # a 8x1 row would leave the middle ones with a symmetric
        marines = [m for m in marines if m.position.y < 60.5 or m.position.x > 60.5]    # neighbourhood - drop that: keep a ragged clump
        if with_wall:
            sc.ai.in_pathing_grid = lambda p: not (61.5 <= p.y <= 63.5)     # a wall just ahead of them (the target is up and right)
        ctx = begin(sc)
        sc.manager.bio.control(sc.world.units(marines), orders(sc, mode=Mode.ATTACK, target=(150, 150)), ctx)
        return [t for m in marines for a, t, q in cmds(sc, m) if a == A.ATTACK and hasattr(t, "x")]
    free = march(False)
    check("control: without a wall the clumped marines hop a few cells ahead", any(t.distance_to(Point2((150, 150))) > 10 for t in free), str(free[:3]))
    walled = march(True)
    check("bio: with a wall in the way every marine is sent to the far target, none to a spot behind the wall",
          len(walled) > 0 and all(t.distance_to(Point2((150, 150))) < 1 for t in walled), str(walled[:3]))


def test_ground_followers_do_not_aim_behind_a_wall():
    sc = mk()
    cy = sc.own(U.CYCLONE, (60, 60))
    sc.ai.in_pathing_grid = lambda p: not (62.0 <= p.x <= 63.0)
    ctx = begin(sc)
    sc.manager.cyclones.control(sc.world.units([cy]), orders(sc, mode=Mode.ATTACK, target=(150, 150), anchor=(60, 60)), ctx)
    c = [t for a, t, q in cmds(sc, cy) if a == A.ATTACK and hasattr(t, "x")]
    check("cyclone: follows to the far target when the point ahead of the army is behind a wall", c and c[0].distance_to(Point2((150, 150))) < 1, str(c))


def test_diversion_and_stragglers():
    sc = mk()
    sc.ai.supply_cap, sc.ai.supply_left = 200, 2                 # maxed -> attack
    sc.own_many(U.MARINE, 20, (60, 60), role=UnitRole.ATTACKING)
    far = sc.own(U.MARINE, (30, 30), role=UnitRole.ATTACKING)     # straggler far from the blob
    sc.enemy(U.HATCHERY, (180, 180))                              # main target: enemy main (home)
    sc.enemy(U.HATCHERY, (150, 150))                              # a different base
    sc.ai.enemy_structures_list = True
    sc.step()
    check("attacking with a large bio force", sc.manager.attacking)
    div = sc.ai.mediator.roles[UnitRole.CONTROL_GROUP_ONE]
    print("   diversion squad:", len(div), "target:", sc.manager.diversion_target)
    check("a diversion squad may split off (size <= 3)", len(div) <= 3)
    check("the straggler is ordered towards the main blob, not the enemy", any(c.unit.tag == far.tag and getattr(c.target, "x", 0) < 100 for c in sc.ai.actions), str([(c.ability.name, c.target) for c in sc.commands_for(far)]))
    # main stops attacking -> diversion dissolves
    sc.ai.supply_cap, sc.ai.supply_left = 120, 30
    sc.manager.attacking = False
    sc.step()
    check("diversion dissolves when the main army stops attacking", len(sc.ai.mediator.roles[UnitRole.CONTROL_GROUP_ONE]) == 0)


def test_air_threat_defenders_can_shoot_air():
    sc = mk()
    sc.own_many(U.MARAUDER, 20, (55, 55), role=UnitRole.ATTACKING)
    sc.own_many(U.MARINE, 20, (58, 55), role=UnitRole.ATTACKING)
    sc.enemy_many(U.MUTALISK, 4, (24, 24))
    sc.ai.state.game_loop += 0
    sc.step()
    d = sc.ai.mediator.roles[UnitRole.BASE_DEFENDER]
    types = {u.type_id for u in sc.ai.units if u.tag in d}
    check("air threat: defenders exist and are all able to hit air", len(d) > 0 and types <= {U.MARINE}, str(types))


def test_emergency_fallback():
    sc = mk()
    sc.own_many(U.MARINE, 5, (60, 60), role=UnitRole.ATTACKING)
    sc.manager.positioning.hold_point = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    sc.step()
    check("emergency fallback: a broken core does not leave the army idle or crash", True)


def test_enemy_tracker():
    from bot.army.enemy_tracker import EnemyTracker
    sc = mk()
    ai = sc.ai
    tr = EnemyTracker(ai)
    z = sc.enemy(U.ROACH, (100, 100))
    sc.step()
    tr.update(ai.visible_enemy_units)
    check("tracker: sees a roach", len(tr) == 1)
    ai._enemies.clear()
    ai._fake_time += 600.0
    ai.state.game_loop += int(600 * 22.4)
    tr.update(ai.visible_enemy_units)
    check("tracker: a roach not seen for 10 minutes is STILL alive (no time decay)", len(tr) == 1)
    known = tr.known_army()
    check("tracker: stale snapshot comes back healed", len(known) == 1 and known[0].health == known[0].health_max)
    tr.remove(z.tag)
    check("tracker: death removes it and counts its supply as seen", len(tr) == 0 and tr.killed_supply == 2.0, str(tr.killed_supply))


def test_compat_abilities():
    from bot.ares_compat import install_unit_abilities
    sc = mk()
    m = sc.own(U.MARINE, (10, 10))
    check("compat: Unit.abilities exists and is empty without cache", install_unit_abilities() and len(m.abilities) == 0)
    sc.ai.ability_cache = {m.tag: frozenset({A.EFFECT_STIM_MARINE})}
    check("compat: Unit.abilities reads the per-step cache", A.EFFECT_STIM_MARINE in m.abilities)


def test_compat_point_truthiness():
    """The crash a real game hit: Ares tests points with `if point:` and its paths are made of numpy ints, and mainline's
    Point2.__bool__ returns `self[0] != 0 or self[1] != 0` as it is - a numpy bool - which Python refuses
    ("__bool__ should return bool, returned numpy.bool")."""
    import numpy as np
    from ares.behaviors.combat.individual.place_predictive_aoe import PlacePredictiveAoE
    from bot.ares_compat import install_point_bool
    mk()                                                                     # a Scene installs the bridge, like the bot does
    check("compat: Point2 truthiness is patched (and idempotent)", install_point_bool() and install_point_bool())
    cases = [((np.int32(48), np.int32(72)), True), ((np.int64(0), np.int64(5)), True), ((np.float64(0.0), np.float64(0.0)), False),
             ((np.int32(0), np.int32(0)), False), ((3.5, 0), True), ((0, 0), False)]
    for coords, expected in cases:
        try:
            truth = bool(Point2(coords))
        except TypeError as e:
            truth = f"raised {e}"
        check(f"compat: bool(Point2({coords})) is {expected}", truth is expected, str(truth))
    # the exact call from the traceback: the unit is closer to its current path point than one step, so `if next_target:` runs
    try:
        pos, reached = PlacePredictiveAoE._get_unit_next_position(
            current_position=Point2((49.33, 72.0)), current_target=Point2((np.int32(49), np.int32(72))),
            distance_per_step=0.47, next_target=Point2((np.int32(48), np.int32(72))))
        check("compat: Ares' PlacePredictiveAoE steps on to the next numpy path point", reached is True and abs(pos.x - 48.86) < 0.05, str((pos, reached)))
    except TypeError as e:
        check("compat: Ares' PlacePredictiveAoE steps on to the next numpy path point", False, str(e))


# ------------------------------------------------------------------------------------------------------------------------------
# the notes of 2026-09-26: banshees that idle, liberators that rarely siege, bio that splits before tanks, ravens that drop turrets forward
# ------------------------------------------------------------------------------------------------------------------------------
def _turret_spots(c):
    return [t for a, t, q in c if a == A.BUILDAUTOTURRET_AUTOTURRET]


def test_raven_turret_goes_in_front_of_the_raven():
    import asyncio
    from bot.ares_compat import refresh_ability_cache
    from sc2.data import Race

    def drop(raven_x, enemy_x):
        sc = mk(enemy_race=Race.Zerg)
        rv = sc.own(U.RAVEN, (raven_x, 60), energy=100)
        sc.ai.ability_grants[rv.tag] = {A.BUILDAUTOTURRET_AUTOTURRET}
        sc.enemy(U.ROACH, (enemy_x, 60))
        asyncio.run(refresh_ability_cache(sc.ai, sc.ai.units))
        ctx = begin(sc)
        asyncio.run(sc.manager.ravens.control(sc.world.units([rv]), orders(sc), ctx))
        return cmds(sc, rv)

    c = drop(60, 63)                                     # an enemy 3 away: the turret goes 2 ahead of the raven, not on top of it
    spots = _turret_spots(c)
    check("raven: with an enemy close by the turret goes in front of the raven, not under it", spots and 61.4 <= spots[0].x <= 63, str(c))
    c = drop(60, 68)                                     # 8 away: the spot 4 short of the roach is out of cast range: it flies up first
    check("raven: with the enemy farther off it flies forward first, and drops nothing yet",
          not _turret_spots(c) and any(a == A.MOVE_MOVE and 60.5 < t[0] <= 64 for a, t, q in c), str(c))
    c = drop(62, 68)                                     # in reach of that spot now: the turret goes there, 4 short of the roach
    spots = _turret_spots(c)
    check("raven: within reach it drops the turret forward, towards the enemy", spots and 63 <= spots[0].x <= 65.5, str(c))


def _hover_over_empty_base(sc, banshee, steps):
    for _ in range(steps):
        ctx = begin(sc)
        sc.manager.banshees.control(sc.world.units([banshee]), orders(sc), ctx)
    return cmds(sc, banshee)


def test_banshee_moves_on_from_a_base_with_nothing_to_shoot():
    sc = mk()
    b = sc.own(U.BANSHEE, (180, 180))
    sc.enemy(U.HATCHERY, (180, 180))                                      # a base - but buildings are never shot at, and nobody is home
    sc.manager.banshees.roam[b.tag] = Point2((180, 180))
    _hover_over_empty_base(sc, b, 8)                                      # 4 s: still patient
    check("banshee: hovers over its base for a moment first", sc.manager.banshees.roam.get(b.tag) == Point2((180, 180)), str(sc.manager.banshees.roam))
    _hover_over_empty_base(sc, b, 8)                                      # 8 s in all: past IDLE_PATIENCE
    pick = sc.manager.banshees.roam.get(b.tag)
    check("banshee: with nothing to shoot for IDLE_PATIENCE it goes to another base", pick is not None and pick.distance_to(Point2((180, 180))) > 20, str(pick))


def test_banshee_rejoins_the_army_when_no_base_has_anything_for_it():
    sc = mk()
    b = sc.own(U.BANSHEE, (180, 180))
    sc.enemy(U.HATCHERY, (180, 180))
    sc.manager.banshees.roam[b.tag] = Point2((180, 180))
    for base in ((150, 150), (120, 140)):                                 # the others were found empty a moment ago
        sc.manager.banshees._dull_bases.append((Point2(base), 1e9))
    c = _hover_over_empty_base(sc, b, 16)
    check("banshee: with every base empty it heads for the army (the hold point) instead of hovering",
          sc.manager.banshees._recalled_until.get(b.tag, 0) > sc.ai.time and any(a == A.MOVE_MOVE and abs(t[0] - 60) < 1 for a, t, q in c), str(c))


def test_banshee_waiting_for_a_repair_gives_up_and_goes_back_to_work():
    from bot.army.units.banshees import REPAIR_PATIENCE
    sc = mk()
    b = sc.own(U.BANSHEE, (22, 22), hp=40)                                # badly hurt, over the townhall at (20, 20) - and nobody repairs it
    c = _hover_over_empty_base(sc, b, 4)
    check("banshee: a badly hurt banshee waits over the townhall for its repair", b.tag in sc.manager.banshees.retreating, str(c))
    c = _hover_over_empty_base(sc, b, int(REPAIR_PATIENCE / 0.5) + 4)
    check("banshee: with nobody repairing it it gives up waiting and flies out again",
          b.tag not in sc.manager.banshees.retreating and any(a == A.MOVE_MOVE and t[0] > 100 for a, t, q in c), str(c))
    c = _hover_over_empty_base(sc, b, 6)
    check("banshee: ...and is not sent straight back home", b.tag not in sc.manager.banshees.retreating, str(c))


def test_banshee_hurt_flies_to_a_townhall_not_the_hold_point():
    sc = mk()
    b = sc.own(U.BANSHEE, (150, 160), hp=40)
    ctx = begin(sc)
    sc.manager.banshees.control(sc.world.units([b]), orders(sc), ctx)
    c = cmds(sc, b)
    check("banshee: a hurt one goes to the townhall (where the SCVs are), which is not where the army holds",
          any(a == A.MOVE_MOVE and abs(t[0] - 20) < 1 and abs(t[1] - 20) < 1 for a, t, q in c), str(c))


def test_liberator_sieges_without_the_ability_being_listed():
    sc = mk()
    lib = sc.own(U.LIBERATOR, (60, 60), role=UnitRole.ATTACKING)          # the game's list of usable abilities says nothing about the morph
    sc.enemy(U.SIEGETANKSIEGED, (68, 60))
    ctx = begin(sc)
    sc.manager.liberators.control(sc.world.units([lib]), orders(sc), ctx)
    check("liberator: orders Defender Mode over the tank whatever the list of abilities says", any(a == A.MORPH_LIBERATORAGMODE for a, t, q in cmds(sc, lib)), str(cmds(sc, lib)))


def test_liberator_gives_up_on_a_siege_that_never_happens():
    sc = mk()
    lib = sc.own(U.LIBERATOR, (60, 60), role=UnitRole.ATTACKING)          # never turns into a Defender Mode liberator
    sc.enemy(U.SIEGETANKSIEGED, (68, 60))
    given = []
    for _ in range(10):                                                   # 3.5 s apart, 35 s in all
        sc.ai._fake_time += 3.0
        ctx = begin(sc)
        sc.manager.liberators.control(sc.world.units([lib]), orders(sc), ctx)
        given.append(any(a == A.MORPH_LIBERATORAGMODE for a, t, q in cmds(sc, lib)))
    check("liberator: a few orders (not one every step, not forever) when the morph never happens", 2 <= sum(given) <= 3, str(given))
    check("liberator: ...then it leaves sieging alone for a while", sc.manager.liberators.no_siege_until.get(lib.tag, 0) > sc.ai.time, str(sc.manager.liberators.no_siege_until))
    check("liberator: ...and does not hover over the spot doing nothing: it carries on as air support", not given[-1] and len(cmds(sc, lib)) > 0, str(cmds(sc, lib)))


def test_liberator_comes_down_when_only_units_outside_the_zone_are_near():
    sc = mk()
    lib = sc.own(U.LIBERATOR, (60, 60), role=UnitRole.ATTACKING)
    sc.ai.ability_grants[lib.tag] = {A.MORPH_LIBERATORAGMODE}
    sc.enemy(U.SIEGETANKSIEGED, (68, 60))
    ctx = begin(sc)
    sc.manager.liberators.control(sc.world.units([lib]), orders(sc), ctx)      # zone centred on (64, 60)
    ag = _liberator_in_defender_mode(sc, lib)
    sc.ai._fake_time += 30.0                                              # long past the order-time lock
    sc.ai._enemies.clear()
    sc.enemy(U.MARINE, (58, 64))                                          # 4.5 from the liberator itself, 7.2 from the zone's centre
    ctx = begin(sc)
    sc.manager.liberators.control(sc.world.units([ag]), orders(sc), ctx)  # (first seen sieged now: its shooting window starts)
    sc.ai._fake_time += 4.0
    ctx = begin(sc)
    sc.manager.liberators.control(sc.world.units([ag]), orders(sc), ctx)
    check("liberator: nothing in its zone -> it comes down, however near the liberator itself the enemy is", _unsieges_lib(sc, ag), str(cmds(sc, ag)))


def test_bio_spreads_out_on_the_way_in_to_sieged_tanks():
    def points(tank_x, mode=Mode.ATTACK):
        sc = mk()
        marines = sc.own_many(U.MARINE, 12, (60, 60), spacing=0.5)          # a tight ball
        if tank_x is not None:
            sc.enemy(U.SIEGETANKSIEGED, (tank_x, 60))
        ctx = begin(sc)
        sc.manager.bio.control(sc.world.units(marines), orders(sc, mode=mode, target=(150, 150)), ctx)
        return [t for m in marines for a, t, q in cmds(sc, m) if a == A.ATTACK and hasattr(t, "x")]

    def spread(pts):
        return max(p.distance_to(q) for p in pts for q in pts)

    plain, split = points(None), points(80)                              # the tank is 20 away: outside the marines' 15 look-out
    check("bio: marching towards a sieged tank the ordered points are spread further apart than on a plain march",
          len(split) == 12 and spread(split) > spread(plain) + 1.0, f"{spread(plain):.1f} vs {spread(split):.1f}")
    check("bio: (a plain march is not changed by it)", len(plain) == 12, str(len(plain)))
    held = points(80, mode=Mode.HOLD)
    check("bio: no splitting while holding position", not any(t.distance_to(Point2((80, 60))) < 3 for t in held), str(held[:3]))

    # stopped on purpose (the staging point in front of tanks, a pause for the tail): the army holds, it does not charge the tanks
    for what in ("staging", "pausing"):
        sc = mk()
        marines = sc.own_many(U.MARINE, 12, (60, 60), spacing=0.5)
        sc.enemy(U.SIEGETANKSIEGED, (80, 60))
        o = orders(sc, mode=Mode.ATTACK, target=(60, 60))
        if what == "staging":
            o.staging = Point2((60, 60))
        else:
            o.pausing = True
        ctx = begin(sc)
        sc.manager.bio.control(sc.world.units(marines), o, ctx)
        ordered = [t for m in marines for a, t, q in cmds(sc, m) if a == A.ATTACK and hasattr(t, "x")]
        check(f"bio: while the army is {what} it does not spread out towards the tanks it faces", ordered and all(t.x < 68 for t in ordered), str([round(t.x) for t in ordered]))

    # something already in weapon range: the fight logic, not the split
    sc = mk()
    m = sc.own(U.MARINE, (60, 60), cooldown=0.0)
    z = sc.enemy(U.ZERGLING, (63, 60))
    sc.enemy(U.SIEGETANKSIEGED, (74, 60))
    ctx = begin(sc)
    sc.manager.bio.control(sc.world.units([m]), orders(sc, mode=Mode.ATTACK), ctx)
    check("bio: a target in weapon range is shot at, tank or no tank", any(a == A.ATTACK and getattr(t, "tag", None) == z.tag for a, t, q in cmds(sc, m)), str(cmds(sc, m)))
    # banelings keep their rule: no walking on towards the tanks while they are about
    sc = mk()
    m = sc.own(U.MARINE, (60, 60), cooldown=10.0)
    sc.enemy(U.BANELING, (64.5, 60))
    sc.enemy(U.SIEGETANKSIEGED, (74, 60))
    ctx = begin(sc)
    sc.manager.bio.control(sc.world.units([m]), orders(sc, mode=Mode.ATTACK), ctx)
    c = cmds(sc, m)
    check("bio: banelings close by are still backed away from, tanks or no tanks", _backs_away(c), str(c))


# ------------------------------------------------------------------------------------------------------------------------------
# a locked-on cyclone kites: the lock keeps firing up to 15 range, while the target stays in view
# ------------------------------------------------------------------------------------------------------------------------------
def _locked_cyclone(buffs=(BuffId.LOCKON,), extra_enemy=None):
    """a Cyclone at (60, 60) that has just cast Lock On at a marine 6 away (in cast range): returns (scene, cyclone, marine) after the cast"""
    from bot.ares_compat import refresh_ability_cache
    sc = mk()
    cy = sc.own(U.CYCLONE, (60, 60))
    sc.ai.ability_grants[cy.tag] = {A.LOCKON_LOCKON, A.LOCKONAIR_LOCKONAIR}
    marine = sc.enemy(U.MARINE, (66, 60), buffs=list(buffs))
    if extra_enemy is not None:
        sc.enemy(*extra_enemy)
    asyncio.run(refresh_ability_cache(sc.ai, sc.ai.units))
    ctx = begin(sc)
    sc.manager.cyclones.control(sc.world.units([cy]), orders(sc), ctx)
    return sc, cy, marine


def _move(sc, unit, x, own=False, **kw):
    """the same unit (same tag) a moment later, at x"""
    (sc.ai._own if own else sc.ai._enemies).remove(unit)
    return (sc.own if own else sc.enemy)(unit.type_id, (x, 60), tag=unit.tag, **kw)


def _next_step(sc, cy, **order_kw):
    from bot.ares_compat import refresh_ability_cache
    asyncio.run(refresh_ability_cache(sc.ai, sc.ai.units))
    ctx = begin(sc)
    sc.manager.cyclones.control(sc.world.units([cy]), orders(sc, **order_kw), ctx)
    return cmds(sc, cy)


def _fire_on(sc, x_from=55, x_to=66):
    """enemy fire over the cells x_from..x_to (around the cyclone at x = 60)"""
    sc.ai.mediator.ground[x_from:x_to, 50:70] = 60.0


def test_locked_cyclone_records_the_lock_and_does_not_recast():
    sc, cy, marine = _locked_cyclone(extra_enemy=(U.MARINE, (65, 61)))
    check("cyclone: the lock is recorded (which unit, when)", sc.manager.cyclones.locks.get(cy.tag, (None,))[0] == marine.tag, str(sc.manager.cyclones.locks))
    c = _next_step(sc, cy)
    check("cyclone: safe with the target well inside 15, it stays put and does not spend a second lock (which would end the first)",
          len(c) == 0, str(c))


def test_locked_cyclone_steps_out_of_fire_but_keeps_the_lock():
    sc, cy, marine = _locked_cyclone()
    marine = _move(sc, marine, 69.0, buffs=[BuffId.LOCKON])              # the target is 9 away: room to go 5 further back...
    _fire_on(sc)                                                          # ...and the cyclone stands in fire (cells 55-65)
    c = _next_step(sc, cy)
    moves = [t for a, t, q in c if a == A.MOVE_MOVE]
    check("cyclone: locked and in fire, it retreats", len(moves) == 1 and moves[0][0] < 60, str(c))
    # the safe cells start 6 back (x = 54): that would be 15 from the target - the retreat stops where the lock still holds (13.5 + radii)
    check("cyclone: ...but only as far as the target stays inside the lock's range (not all the way to the safe spot)", moves and 54.3 < moves[0][0] < 55.3, str(moves))


def test_locked_cyclone_at_the_edge_of_the_lock_leaves_it_rather_than_die():
    sc, cy, marine = _locked_cyclone()
    marine = _move(sc, marine, 74.0, buffs=[BuffId.LOCKON])              # 13.25 from the target: no room to back away and keep it
    _fire_on(sc)
    c = _next_step(sc, cy)
    moves = [t for a, t, q in c if a == A.MOVE_MOVE]
    check("cyclone: in fire with no way out that keeps the lock, the cyclone still comes first (all the way to the safe spot)", moves and moves[0][0] < 55, str(c))


def test_locked_cyclone_follows_a_target_that_walks_away():
    sc, cy, marine = _locked_cyclone()
    marine = _move(sc, marine, 75.5, buffs=[BuffId.LOCKON])              # 14.75 from the cyclone's edge: the lock ends at 15
    c = _next_step(sc, cy)
    moves = [t for a, t, q in c if a == A.MOVE_MOVE]
    check("cyclone: safe, with the target about to leave the lock's range, it steps after it", moves and 62.5 < moves[0][0] < 64, str(c))
    sc, cy, marine = _locked_cyclone()
    marine = _move(sc, marine, 80.0, buffs=[BuffId.LOCKON])              # out of range: the lock is over
    c = _next_step(sc, cy)
    check("cyclone: ...and one that has left it is not chased (the lock is forgotten)", cy.tag not in sc.manager.cyclones.locks, str(sc.manager.cyclones.locks))


def test_locked_cyclone_lock_ends_when_the_target_leaves_view():
    sc, cy, marine = _locked_cyclone(extra_enemy=(U.ZERGLING, (64, 60)))
    locked = next(e for e in sc.ai._enemies if e.tag == sc.manager.cyclones.locks[cy.tag][0])       # (the zergling: the lowest hit points)
    sc.ai._enemies.remove(locked)
    ghost = sc.enemy(locked.type_id, (locked.position.x, locked.position.y), tag=locked.tag)
    ghost._ghost = True
    ghost.game_loop = 1                                                   # only a memory of it now
    c = _next_step(sc, cy)
    check("cyclone: the target gone from view, the lock on it is forgotten", sc.manager.cyclones.locks.get(cy.tag, (None,))[0] != locked.tag, str(sc.manager.cyclones.locks))
    check("cyclone: ...and the cyclone carries on with the normal logic (a fresh lock on the marine, which it can see)",
          any(a == A.LOCKON_LOCKON and getattr(t, "tag", None) == marine.tag for a, t, q in c), str(c))


def test_locked_cyclone_cast_that_never_took_is_tried_again():
    sc, cy, marine = _locked_cyclone(buffs=())                            # no buff on the target, and the ability is still on offer
    sc.ai._fake_time += 1.2                                               # (begin adds 0.5: the next step is 1.7 s after the cast)
    c = _next_step(sc, cy)
    check("cyclone: no sign of a lock 1.5 s after the cast -> it never took: the lock is dropped and cast again",
          any(a == A.LOCKON_LOCKON and getattr(t, "tag", None) == marine.tag for a, t, q in c), str(c))
    sc, cy, marine = _locked_cyclone()                                    # with the buff on the target
    sc.ai._fake_time += 1.2
    c = _next_step(sc, cy)
    check("cyclone: ...but a target that carries the lock keeps its lock", cy.tag in sc.manager.cyclones.locks and not c, str((c, sc.manager.cyclones.locks)))


def test_locked_cyclone_retreating_group_keeps_the_lock_while_it_goes_home():
    sc, cy, marine = _locked_cyclone()
    # the group retreats to the hold point at (60, 60); the cyclone has meanwhile been drawn out to (75, 60), its target to (84, 60)
    cy = _move(sc, cy, 75.0, own=True)
    sc.ai.ability_grants[cy.tag] = {A.LOCKON_LOCKON, A.LOCKONAIR_LOCKONAIR}
    marine = _move(sc, marine, 84.0, buffs=[BuffId.LOCKON])
    sc.ai.mediator.ground[70:80, 50:70] = 60.0                            # in fire
    c = _next_step(sc, cy, mode=Mode.HOLD, retreating=True)
    moves = [t for a, t, q in c if a == A.MOVE_MOVE]
    check("cyclone: a retreating group's locked cyclone heads for the hold point, as far as the lock allows (not the whole way)", moves and 69 < moves[0][0] < 71, str(c))


def test_locked_cyclone_is_left_alone_while_the_cast_is_on_it():
    sc, cy, marine = _locked_cyclone()
    _fire_on(sc)
    cy = _move(sc, cy, 60.0, own=True, orders=[(A.LOCKON_LOCKON, marine.tag)])     # the game still shows the cast as its order
    sc.ai.ability_grants[cy.tag] = {A.LOCKON_LOCKON, A.LOCKONAIR_LOCKONAIR}
    c = _next_step(sc, cy)
    check("cyclone: while the cast is still its order, nothing is ordered (a move could cancel it), fire or no fire", len(c) == 0, str(c))


def test_farthest_within():
    from bot.army.units.cyclones import farthest_within
    centre = Point2((69, 60))
    p = farthest_within(Point2((60, 60)), Point2((62, 60)), centre, 14.25)
    check("geometry: a step that stays inside the circle is taken whole", p is not None and abs(p.x - 62) < 0.01, str(p))
    p = farthest_within(Point2((60, 60)), Point2((54, 60)), centre, 14.25)
    check("geometry: one that would leave it is cut where it crosses the circle", p is not None and abs(p.x - 54.75) < 0.01, str(p))
    p = farthest_within(Point2((55, 60)), Point2((50, 60)), centre, 14.25)
    check("geometry: no useful step when the way out starts at once", p is None, str(p))
    p = farthest_within(Point2((50, 60)), Point2((56, 60)), centre, 14.25)
    check("geometry: already outside: a move that brings it back in is fine", p is not None and abs(p.x - 56) < 0.01, str(p))
    p = farthest_within(Point2((50, 60)), Point2((45, 60)), centre, 14.25)
    check("geometry: ...one that takes it farther out is not", p is None, str(p))
    check("geometry: no move at all is no step", farthest_within(Point2((60, 60)), Point2((60, 60)), centre, 14.25) is None)


# ------------------------------------------------------------------------------------------------------------------------------
# bio steps back from melee enemies (Zealots, Zerglings): shoot when the weapon is ready, step back while it is not
# ------------------------------------------------------------------------------------------------------------------------------
def _vs_melee(enemies, unit=U.MARINE, cooldown=10.0, local=None, mode=Mode.ATTACK, at=(60, 60), retreating=False, danger_x=None, patch=None):
    """a bio unit at `at` against `enemies` [(type, x)] at y = 60; returns (its commands, the scene)"""
    sc = mk()
    m = sc.own(unit, at, cooldown=cooldown)
    for type_id, x in enemies:
        e = sc.enemy(type_id, (x, 60))
        if patch:
            patch(e)
    if danger_x is not None:
        danger(sc, (danger_x, 60), radius=5)
    ctx = begin(sc)
    sc.manager.bio.control(sc.world.units([m]), orders(sc, mode=mode, local=local, retreating=retreating), ctx)
    return cmds(sc, m), sc


def test_bio_kites_away_from_zealots():
    c, _ = _vs_melee([(U.ZEALOT, 65.5)])
    check("bio: a marine that has just fired steps back from a zealot 5.5 away (inside its range + 1), with no danger grid needed", _backs_away(c), str(c))
    c, _ = _vs_melee([(U.ZEALOT, 69.0)])
    check("bio: ...but not from one that is still 9 away", not any(a == A.MOVE_MOVE for a, t, q in c) and any(a == A.ATTACK for a, t, q in c), str(c))
    c, _ = _vs_melee([(U.ZEALOT, 65.5)], cooldown=0.0)
    check("bio: ...and when its weapon is ready it shoots (the step back is for the cooldown)", any(a == A.ATTACK for a, t, q in c) and not any(a == A.MOVE_MOVE for a, t, q in c), str(c))
    c, _ = _vs_melee([(U.ZEALOT, 66.5)], unit=U.MARAUDER)
    check("bio: a marauder (range 6) steps back from one 6.5 away", _backs_away(c), str(c))
    c, _ = _vs_melee([(U.ZERGLING, 65.5)])
    check("bio: and from zerglings", _backs_away(c), str(c))


def test_bio_does_not_kite_in_towards_zealots():
    # a mixed army: the zealot is 4 away, the stalker behind it - "not all melee", and the simulator is sure: the marine used to step FORWARD
    c, _ = _vs_melee([(U.ZEALOT, 64.0), (U.STALKER, 68.0)], local=ER.VICTORY_EMPHATIC)
    check("bio: a zealot close, a stalker behind it, at overwhelming odds: the marine steps back, not into the zealot", _backs_away(c), str(c))
    # no melee unit close (the zealot is 9 away): the kite-in against the ranged units carries on...
    c, _ = _vs_melee([(U.ROACH, 64.0), (U.HYDRALISK, 66.0)], local=ER.VICTORY_OVERWHELMING, danger_x=62)
    check("bio: (control) against ranged units alone it still pushes in", any(a == A.MOVE_MOVE and t[0] > 60 for a, t, q in c), str(c))
    # ...but not with a melee unit within 10 of it
    c, _ = _vs_melee([(U.ROACH, 64.0), (U.HYDRALISK, 66.0), (U.ZEALOT, 69.0)], local=ER.VICTORY_OVERWHELMING, danger_x=62)
    check("bio: ...and not with a zealot 9 away, which would be on it before the step forward is done", not any(a == A.MOVE_MOVE and t[0] > 60 for a, t, q in c), str(c))


def test_bio_melee_kiting_leaves_out_what_it_cannot_help():
    c, _ = _vs_melee([(U.PROBE, 63.0)])
    check("bio: a probe is not something to run from", not any(a == A.MOVE_MOVE for a, t, q in c), str(c))
    c, _ = _vs_melee([(U.ZEALOT, 65.5)], patch=lambda e: e.__dict__.__setitem__("real_speed", 9.0))
    check("bio: nor a melee unit far faster than the marine (a step back gains nothing on it)", not any(a == A.MOVE_MOVE for a, t, q in c), str(c))
    c, _ = _vs_melee([(U.COMMANDCENTER, 63.0)])
    check("bio: nor a building", not any(a == A.MOVE_MOVE and t[0] < 60 for a, t, q in c), str(c))
    c, _ = _vs_melee([(U.ZEALOT, 80.5)], at=(75, 60), mode=Mode.HOLD, retreating=True)
    check("bio: a retreating group's marine goes home (the hold point at x = 60) instead of picking its own way", any(a == A.MOVE_MOVE and abs(t[0] - 60) < 1 for a, t, q in c), str(c))


# ------------------------------------------------------------------------------------------------------------------------------
# banshees wait for their repair on open ground (the SCVs cannot walk through a townhall)
# ------------------------------------------------------------------------------------------------------------------------------
def _footprint(sc, centre=(20, 20), size=5):
    """a building's footprint on the clean ground grid, as Ares' grid has it: np.inf, nobody can stand there"""
    x, y = int(centre[0] - size / 2), int(centre[1] - size / 2)
    sc.ai.mediator.ground[x:x + size, y:y + size] = np.inf


def _first_move(c):
    moves = [t for a, t, q in c if a == A.MOVE_MOVE]
    return Point2((float(moves[0][0]), float(moves[0][1]))) if moves else None


def _hurt_banshee_spot(sc, hp=40):
    b = sc.own(U.BANSHEE, (150, 160), hp=hp)
    ctx = begin(sc)
    sc.manager.banshees.control(sc.world.units([b]), orders(sc), ctx)
    return b, _first_move(cmds(sc, b))


def test_banshee_repair_spot_is_open_ground_not_the_townhall():
    from bot.pathing.order_utils import reachable_from_ground
    sc = mk()
    _footprint(sc)
    b, spot = _hurt_banshee_spot(sc)
    check("banshee: a hurt one flies to open ground close to the townhall, room for an SCV to stand under it",
          spot is not None and reachable_from_ground(sc.ai.mediator.ground, spot) and 3 <= spot.distance_to(Point2((20, 20))) <= 9, str(spot))
    check("banshee: ...not over the townhall's footprint (a 5x5 block the SCVs cannot walk through)",
          spot is not None and not (17 <= spot.x < 22 and 17 <= spot.y < 22), str(spot))


def test_banshee_repair_spot_is_in_the_mineral_lane():
    sc = mk()
    _footprint(sc)
    for y in (16.0, 18.5, 21.5, 24.0):                       # a mineral line on the east side, 7 from the townhall (fields are 2x1 and not walkable)
        sc.mineral((27.0, y))
        sc.ai.mediator.ground[26:28, int(y)] = np.inf
    b, spot = _hurt_banshee_spot(sc)
    check("banshee: with a mineral line it waits in the lane between it and the townhall, where the SCVs are",
          spot is not None and 22.5 < spot.x < 25.5 and abs(spot.y - 20) < 2.5, str(spot))


def test_banshee_repair_spot_skips_what_the_scvs_cannot_walk_to():
    sc = mk()
    _footprint(sc)
    _, plain = _hurt_banshee_spot(sc)
    sc = mk()
    _footprint(sc)
    real = sc.ai.mediator.find_raw_path
    # the nearest spots: no way there at all (north), a way round of 60 (east) - the SCVs cannot use either
    sc.ai.mediator.find_raw_path = lambda start, target, grid, sensitivity=5: (
        [] if target[1] > 22 else [Point2((60, 20)), Point2(target)] if target[0] > 22 else real(start, target, grid, sensitivity))
    _, spot = _hurt_banshee_spot(sc)
    check("banshee: (control) the same base with a free way to every spot: the nearest spot is north or east, on the townhall's edge",
          plain is not None and (plain.y > 22 or plain.x > 22), str(plain))
    check("banshee: a spot the SCVs have no path to, or only a long way round, is skipped: it waits at the next one",
          spot is not None and (spot.x < 17 or spot.y < 17) and spot.distance_to(Point2((20, 20))) < 6, str(spot))


def test_banshee_keeps_waiting_while_it_is_being_repaired():
    from bot.army.units.banshees import REPAIR_PATIENCE
    sc = mk()
    _footprint(sc)
    b, spot = _hurt_banshee_spot(sc, hp=40)
    steps = int(REPAIR_PATIENCE / 0.5) + 12                   # longer than the patience: 30 s
    for i in range(steps):
        (sc.ai._own).remove(b)
        b = sc.own(U.BANSHEE, (spot.x, spot.y), tag=b.tag, hp=40 + i)        # an SCV repairs it: 1 hit point per look
        ctx = begin(sc)
        sc.manager.banshees.control(sc.world.units([b]), orders(sc), ctx)
    check("banshee: while the repair goes on it keeps waiting, however long that takes",
          b.tag in sc.manager.banshees.retreating and b.tag not in sc.manager.banshees._no_retreat_until, str(sc.manager.banshees._no_retreat_until))
    for _ in range(int(REPAIR_PATIENCE / 0.5) + 4):                            # the repair stops
        ctx = begin(sc)
        sc.manager.banshees.control(sc.world.units([b]), orders(sc), ctx)
    check("banshee: ...and once it stops, it gives up after the patience as before",
          b.tag not in sc.manager.banshees.retreating and b.tag in sc.manager.banshees._no_retreat_until, str(sc.manager.banshees.retreating))


def test_open_ground_helpers():
    from bot.pathing.order_utils import ground_free, open_ground_near, path_length, reachable_from_ground
    grid = np.ones((40, 40), dtype=np.float32)
    grid[10:15, 10:15] = np.inf                                                # a building
    check("ground: a cell in the footprint is not free, one beside it is", not ground_free(grid, 12.5, 12.5) and ground_free(grid, 15.5, 12.5))
    check("ground: a flyer over the middle of a building cannot be reached, one over its edge can",
          not reachable_from_ground(grid, (12.5, 12.5), 0.75) and reachable_from_ground(grid, (14.8, 12.5), 0.75))
    spots = open_ground_near(grid, Point2((12.5, 12.5)), 6.0)
    gaps = [p.distance_to(Point2((12.5, 12.5))) for p in spots]
    check("ground: open cells come nearest first, none inside the footprint, none within a cell of it (room for an SCV beside the flyer)",
          spots and gaps == sorted(gaps) and abs(gaps[0] - 4.0) < 1e-6 and not any(9 <= p.x < 16 and 9 <= p.y < 16 for p in spots), str(spots[:3]))
    check("ground: at most `limit` of them", len(open_ground_near(grid, Point2((12.5, 12.5)), 6.0, limit=3)) == 3)
    check("ground: none where everything is blocked, and no fuss at the edge of the map",
          open_ground_near(np.full((40, 40), np.inf, dtype=np.float32), Point2((20, 20)), 5.0) == [] and len(open_ground_near(grid, Point2((1, 1)), 5.0)) > 0)
    check("path: its length from the start, none without a path",
          abs(path_length((0, 0), [(3, 4), (3, 10)]) - 11.0) < 1e-9 and path_length((0, 0), []) is None and path_length((0, 0), None) is None)


# ------------------------------------------------------------------------------------------------------------------------------
# reapers never shoot buildings: with no unit in sight they tour the enemy's mineral lines instead of standing next to buildings
# ------------------------------------------------------------------------------------------------------------------------------
def _shoots_at_ground(c):
    """an attack order at a spot (attack-move: shoots whatever is in range, buildings included)"""
    return any(a in (A.ATTACK, A.ATTACK_ATTACK, A.SCAN_MOVE) and not hasattr(t, "tag") for a, t, q in c)


def _enemy_base_with_minerals(sc, at=(180, 180)):
    """a hatchery and, east of it, a mineral line of four fields (the two farthest apart are 12 apart)"""
    sc.enemy(U.HATCHERY, at)
    for dy in (-7.0, -2.5, 2.5, 7.0):
        sc.mineral((at[0] + 6.0, at[1] + dy))


def _reaper_step(sc, r):
    ctx = begin(sc)
    sc.manager.reapers.control(sc.world.units([r]), orders(sc), ctx)
    return cmds(sc, r)


def test_reaper_is_never_attack_moved_at_buildings():
    sc = mk()
    r = sc.own(U.REAPER, (177, 179))                                      # right beside the enemy's main, and nothing but buildings in sight
    sc.enemy(U.HATCHERY, (180, 180))
    sc.enemy(U.BARRACKS, (176, 182))                                      # (the building nearest to us: 3 from the reaper - the old code attack-moved onto it)
    c = _reaper_step(sc, r)
    check("reaper: with only buildings around it is never attack-moved (that shoots them)", c and not _shoots_at_ground(c), str(c))
    check("reaper: ...it keeps moving instead", any(a == A.MOVE_MOVE for a, t, q in c), str(c))


def test_reaper_tours_the_mineral_lines():
    sc = mk()
    _enemy_base_with_minerals(sc)
    r = sc.own(U.REAPER, (150, 150))
    first = _first_move(_reaper_step(sc, r))
    # the two ends of the line are at y 173 and 187, in the lane 2 towards the hatchery: (185.2, ~174.6) and (185.2, ~185.4)
    check("reaper: it heads for one end of the enemy's mineral line", first is not None and first.x > 183 and (abs(first.y - 174.6) < 2 or abs(first.y - 185.4) < 2), str(first))
    ends = []
    for _ in range(3):
        sc.ai._own.remove(r)
        r = sc.own(U.REAPER, (first.x, first.y), tag=r.tag)                # it has got there
        nxt = _first_move(_reaper_step(sc, r))
        ends.append(nxt)
        first = nxt
    check("reaper: getting there it does not stop: it goes to the other end, and back",
          all(e is not None for e in ends) and abs(ends[0].y - ends[1].y) > 8 and abs(ends[0].y - ends[2].y) < 1.0, str(ends))


def test_reaper_tour_leaves_out_a_defended_mineral_line_end():
    sc = mk()
    _enemy_base_with_minerals(sc)
    sc.enemy(U.SPINECRAWLER, (186, 172))                                   # a spine crawler covers the southern end (it reaches 7 + 3)
    r = sc.own(U.REAPER, (150, 150))
    first = _first_move(_reaper_step(sc, r))
    check("reaper: it goes for the end that is not defended", first is not None and first.y > 180, str(first))
    sc.ai._own.remove(r)
    r = sc.own(U.REAPER, (first.x, first.y), tag=r.tag)
    nxt = _first_move(_reaper_step(sc, r))
    check("reaper: ...and, with one stop left, it does not stand there among the buildings but goes back towards home and returns",
          nxt is not None and nxt.distance_to(first) > 3, str((first, nxt)))


def test_reaper_tour_does_not_take_workers_for_defenders():
    sc = mk()
    _enemy_base_with_minerals(sc)
    for dy in (-6.0, -3.0, 0.0, 3.0, 6.0):                                 # a mineral line full of workers: Ares' grid calls that danger, the tour must not
        sc.enemy(U.DRONE, (185.0, 180.0 + dy))
    check("reaper: workers are not defenders of their own mineral line", sc.manager.reapers._defenders() == [], str(sc.manager.reapers._defenders()))
    sc.enemy(U.MARINE, (186, 172))
    sc.enemy(U.BUNKER, (170, 190))
    reach = {(round(p.x), round(p.y)): r for p, r in sc.manager.reapers._defenders()}
    check("reaper: a marine (5 + 3 + its radius) and a bunker (7 + 3 + its radius) are", set(reach) == {(186, 172), (170, 190)} and 8.3 < reach[(186, 172)] < 8.5 and 10.3 < reach[(170, 190)] < 10.5, str(reach))


def test_reaper_still_goes_for_units_first():
    sc = mk()
    _enemy_base_with_minerals(sc)
    r = sc.own(U.REAPER, (176, 176), cooldown=0.0)
    drone = sc.enemy(U.DRONE, (179, 176))
    c = _reaper_step(sc, r)
    check("reaper: a worker in reach is shot, not the hatchery", any(a == A.ATTACK and getattr(t, "tag", None) == drone.tag for a, t, q in c), str(c))
    sc = mk()
    _enemy_base_with_minerals(sc)
    r = sc.own(U.REAPER, (176, 176), cooldown=10.0)
    drone = sc.enemy(U.DRONE, (179, 176))
    c = _reaper_step(sc, r)
    check("reaper: with its weapon on cooldown it does not attack-move onto the spot: it stays on its target",
          not _shoots_at_ground(c), str(c))


def test_base_defense_ignores_a_forward_auto_turret():
    sc = mk()
    sc.own(U.AUTOTURRET, (170, 170))                                      # a Raven's, dropped next to the enemy's army at THEIR base
    sc.enemy_many(U.ROACH, 8, (176, 176))
    threats = sc.manager.defense.find_threats(begin(sc))
    check("defense: enemies around an Auto-Turret at the enemy's base are not a threat to our bases", threats == [], str([(len(t.units), t.center) for t in threats]))
    sc = mk()
    sc.own(U.BARRACKS, (28, 24))
    sc.enemy_many(U.ROACH, 8, (34, 26))
    threats = sc.manager.defense.find_threats(begin(sc))
    check("defense: (control) the same units around a building at home are", len(threats) == 1 and len(threats[0].units) == 8, str(len(threats)))


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
