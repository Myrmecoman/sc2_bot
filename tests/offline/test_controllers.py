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
from sc2.data import Race
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
    shoot: no ghosts, no genuinely-ignored types (eggs, larvae), nothing it cannot hit (a marauder cannot shoot air) - but a changeling IS
    offered like any other ground unit: it is the enemy's free vision into us until it dies, and dies to one hit (see CHANGELING_TYPES,
    bot/pathing/consts.py - only HARMLESS_TO_WORKERS, a separate list, still exempts it from worker flee logic)."""
    import gamefix
    gamefix.STATS.setdefault(U.CHANGELING, (5, 0, 0, 3.15, [], [gamefix.LIGHT, gamefix.BIO], 0, 0, 0))      # (exotic types the fixture lacks)
    gamefix.STATS.setdefault(U.EGG, (200, 0, 1, 0.0, [], [gamefix.BIO], 0, 0, 0))
    sc = mk()
    marauder = sc.own(U.MARAUDER, (60, 60))
    marine = sc.own(U.MARINE, (60, 61))
    zergling = sc.enemy(U.ZERGLING, (63, 60))
    muta = sc.enemy(U.MUTALISK, (63, 62))
    changeling = sc.enemy(U.CHANGELING, (62, 60))
    egg = sc.enemy(U.EGG, (61, 60))
    ghost = sc.enemy(U.ROACH, (64, 60))
    ghost._ghost = True
    ghost.game_loop = 1
    bane = sc.enemy(U.BANELING, (65, 60))
    ctx = begin(sc)
    ctx.prefetch_near([marauder, marine])
    tags = lambda units: {u.tag for u in units}
    check("context: a marauder is offered ground units only - no air, no eggs, no ghosts, but the changeling counts",
          tags(ctx.targets_near(marauder)) == {zergling.tag, bane.tag, changeling.tag}, str(tags(ctx.targets_near(marauder))))
    check("context: a marine is offered air units too, and the changeling",
          tags(ctx.targets_near(marine)) == {zergling.tag, muta.tag, bane.tag, changeling.tag}, str(tags(ctx.targets_near(marine))))
    check("context: the egg is never offered to anyone",
          egg.tag not in tags(ctx.targets_near(marauder)) | tags(ctx.targets_near(marine)))
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


def test_cyclone_does_not_cast_lock_on_instead_of_backing_off_a_baneling():
    """Lock-On used to be tried BEFORE the baneling check ever ran, so a Cyclone with a valid lock-on target in range
    cast it and returned - skipping the "always back away from banelings, whatever else is true" rule entirely for
    the one step that mattered most (see _control_unit)."""
    from bot.ares_compat import refresh_ability_cache
    sc = mk()
    cy = sc.own(U.CYCLONE, (60, 60), cooldown=10.0)
    sc.ai.ability_grants[cy.tag] = {A.LOCKON_LOCKON}
    sc.enemy(U.ROACH, (64, 60))                 # a valid, not-yet-locked Lock-On candidate within cast range
    sc.enemy(U.BANELING, (61, 61))              # close enough to trigger kite_from_banelings
    asyncio.run(refresh_ability_cache(sc.ai, sc.ai.units))
    ctx = begin(sc)
    sc.manager.cyclones.control(sc.world.units([cy]), orders(sc, local=ER.VICTORY_EMPHATIC), ctx)
    c = cmds(sc, cy)
    check("cyclone: does not cast Lock-On while a close baneling is in range",
          not any(a in (A.LOCKON_LOCKON, A.LOCKONAIR_LOCKONAIR) for a, t, q in c), str(c))
    check("cyclone: backs away from the baneling instead", _backs_away(c), str(c))


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


def test_tank_siege_since_is_pruned_once_the_tank_is_gone():
    """siege_since (tank tag -> when it became sieged) used to only ever be cleared by observing a LIVE tank
    unsiege - a tank that died while sieged left its entry behind forever (unlike the sibling slot_index, which IS
    pruned by a global alive check in _assign_slots - see its own comment)."""
    sc = mk()
    tank = sc.own(U.SIEGETANKSIEGED, (60, 60))   # actually sieged, so _track_siege_state keeps its own entry
    sc.manager.tanks.siege_since[tank.tag] = sc.ai.time
    sc.manager.tanks.siege_since[999999] = sc.ai.time   # a tag belonging to no live unit - stands in for a dead tank
    ctx = begin(sc)
    sc.manager.tanks.control(sc.world.units([tank]), orders(sc), ctx)
    check("tanks: a dead tank's siege_since entry is pruned", 999999 not in sc.manager.tanks.siege_since, str(sc.manager.tanks.siege_since))
    check("tanks: a live tank's own entry is untouched", tank.tag in sc.manager.tanks.siege_since, str(sc.manager.tanks.siege_since))


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


def test_banshee_does_not_cloak_at_the_bare_minimum_energy():
    import asyncio
    from bot.ares_compat import refresh_ability_cache

    def scene(energy, hp=140):
        sc = mk()
        sc.ai.state.upgrades.add(UpgradeId.BANSHEECLOAK)
        b = sc.own(U.BANSHEE, (150, 160), energy=energy, hp=hp)
        sc.ai.ability_grants[b.tag] = {A.BEHAVIOR_CLOAKON_BANSHEE}
        sc.enemy(U.MARINE, (154, 160))
        danger(sc, (152, 160), radius=6, air=True)
        asyncio.run(refresh_ability_cache(sc.ai, sc.ai.units))
        ctx = begin(sc)
        sc.manager.banshees.control(sc.world.units([b]), orders(sc), ctx)
        return cmds(sc, b)

    c = scene(25.0)
    check("banshee: right at the bare minimum energy (25, what turning cloak on costs) it does not cloak - there would be nothing left to stay cloaked with",
          not any(a == A.BEHAVIOR_CLOAKON_BANSHEE for a, t, q in c) and any(a == A.MOVE_MOVE for a, t, q in c), str(c))
    c = scene(50.0)
    check("banshee: (control) with a real reserve above that it does cloak", any(a == A.BEHAVIOR_CLOAKON_BANSHEE for a, t, q in c), str(c))
    c = scene(25.0, hp=40)
    check("banshee: ...unless it is already hurt enough to be retreating anyway - then even a moment of it is worth having",
          any(a == A.BEHAVIOR_CLOAKON_BANSHEE for a, t, q in c), str(c))


def test_banshee_does_not_treat_a_defended_target_as_safe_without_enough_energy_to_cloak():
    """the mirror of test_banshee_that_can_cloak_still_goes_for_defended_targets: with only the bare minimum energy, cloaking would not
    last, so a defended target is not "safe" the way it is for a banshee with a real reserve"""
    import asyncio
    from bot.ares_compat import refresh_ability_cache
    sc = mk()
    sc.ai.state.upgrades.add(UpgradeId.BANSHEECLOAK)
    b = sc.own(U.BANSHEE, (60, 60), energy=25.0)
    sc.ai.ability_grants[b.tag] = {A.BEHAVIOR_CLOAKON_BANSHEE}
    defended = sc.enemy(U.DRONE, (68, 60))
    danger(sc, (66, 60), radius=5, air=True)
    asyncio.run(refresh_ability_cache(sc.ai, sc.ai.units))
    ctx = begin(sc)
    sc.manager.banshees.control(sc.world.units([b]), orders(sc), ctx)
    c = cmds(sc, b)
    check("banshee: with cloak researched but only the bare minimum energy, it leaves the defended worker alone (it cannot count on staying cloaked)",
          not any(getattr(t, "tag", None) == defended.tag for a, t, q in c), str(c))


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
    check("reaper: throwing it seeds the hold (it is armed a while, not gone off yet)",
          sc.manager.reapers._grenade_until.get(r.tag, 0.0) > sc.ai.time, str(sc.manager.reapers._grenade_until))


def test_reaper_does_not_advance_towards_a_target_while_its_own_grenade_is_still_armed():
    """the reported bug: 'the reaper often sends its mine then goes towards it and takes damage as it explodes' - a thrown KD8 Charge
    does not go off at once, so closing the distance to what it was aimed at (the same nearest enemy ReaperGrenade itself would pick)
    walks the reaper into its own blast."""
    sc = mk()
    r = sc.own(U.REAPER, (150, 160), cooldown=0.0)
    sc.enemy(U.MARINE, (160, 160))                                            # 10 away: outside its own 5 range, so normally worth closing in on
    ctx = begin(sc)
    sc.manager.reapers._grenade_until[r.tag] = sc.ai.time + 1.0               # a grenade it just threw is still armed
    sc.manager.reapers.control(sc.world.units([r]), orders(sc), ctx)
    c = cmds(sc, r)
    check("reaper: does not close in on the target while its own grenade is still armed", not any(a == A.ATTACK for a, t, q in c), str(c))

    sc = mk()   # (control: without the hold, it closes in on a distant target - the exact bug this guards against)
    r = sc.own(U.REAPER, (150, 160), cooldown=0.0)
    sc.enemy(U.MARINE, (160, 160))
    ctx = begin(sc)
    sc.manager.reapers.control(sc.world.units([r]), orders(sc), ctx)
    c = cmds(sc, r)
    check("reaper: (control) without a grenade armed, it does close in on a distant target", any(a == A.ATTACK for a, t, q in c), str(c))


def test_reaper_still_fights_something_already_in_range_while_its_grenade_is_armed():
    sc = mk()
    r = sc.own(U.REAPER, (150, 160), cooldown=0.0)
    marine = sc.enemy(U.MARINE, (153, 160))                                   # already within its own 5 ground range: no closer approach needed
    ctx = begin(sc)
    sc.manager.reapers._grenade_until[r.tag] = sc.ai.time + 1.0
    sc.manager.reapers.control(sc.world.units([r]), orders(sc), ctx)
    c = cmds(sc, r)
    check("reaper: still attacks a target already in range while its own grenade is armed",
          any(a == A.ATTACK and getattr(t, "tag", None) == marine.tag for a, t, q in c), str(c))


def test_reaper_resumes_chasing_once_its_grenade_has_had_time_to_go_off():
    sc = mk()
    r = sc.own(U.REAPER, (150, 160), cooldown=0.0)
    sc.enemy(U.MARINE, (160, 160))
    ctx = begin(sc)
    sc.manager.reapers._grenade_until[r.tag] = sc.ai.time - 0.1               # already expired
    sc.manager.reapers.control(sc.world.units([r]), orders(sc), ctx)
    c = cmds(sc, r)
    check("reaper: once the hold has expired, it goes back to closing in on a target normally", any(a == A.ATTACK for a, t, q in c), str(c))


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


def test_liberator_last_morph_command_is_pruned_once_the_liberator_is_gone():
    """last_morph_command was the one dict of the controller's eight left out of control()'s per-step dead-unit
    pruning loop (the other seven are all pruned there) - a silent, unbounded-growth omission, not a deliberate
    exclusion (nothing in the file explains keeping it around for a dead Liberator)."""
    sc = mk()
    lib = sc.own(U.LIBERATOR, (60, 60), role=UnitRole.ATTACKING)
    sc.manager.liberators.last_morph_command[lib.tag] = sc.ai.time
    sc.manager.liberators.last_morph_command[999999] = sc.ai.time   # stands in for a dead Liberator
    ctx = begin(sc)
    sc.manager.liberators.control(sc.world.units([lib]), orders(sc), ctx)
    check("liberators: a dead liberator's last_morph_command entry is pruned",
          999999 not in sc.manager.liberators.last_morph_command, str(sc.manager.liberators.last_morph_command))
    check("liberators: a live liberator's own entry is untouched",
          lib.tag in sc.manager.liberators.last_morph_command, str(sc.manager.liberators.last_morph_command))


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
# a cloaked, undetected enemy (an Observer, most often) is never targeted by a Cyclone - is_visible only means the POSITION is
# seen, it says nothing about the cloak status (cyclones.py only - not a shared ArmyContext change)
# ------------------------------------------------------------------------------------------------------------------------------
def test_cyclone_leaves_an_undetected_observer_alone():
    """the reported bug: a Cyclone tried to target an Observer, which cannot be locked on to or attacked at all without a detector."""
    sc = mk()
    cy = sc.own(U.CYCLONE, (60, 60))
    sc.ai.ability_grants[cy.tag] = {A.LOCKON_LOCKON, A.LOCKONAIR_LOCKONAIR}
    obs = sc.enemy(U.OBSERVER, (63, 60), cloaked=True)
    ctx = begin(sc)
    sc.manager.cyclones.control(sc.world.units([cy]), orders(sc), ctx)
    c = cmds(sc, cy)
    check("cyclone: an undetected Observer is never locked on to or attacked (it just carries on towards the actual objective)",
          not any(getattr(t, "tag", None) == obs.tag for a, t, q in c), str(c))
    from bot.ares_compat import refresh_ability_cache
    sc2 = mk()
    cy2 = sc2.own(U.CYCLONE, (60, 60))
    sc2.ai.ability_grants[cy2.tag] = {A.LOCKON_LOCKON, A.LOCKONAIR_LOCKONAIR}
    obs2 = sc2.enemy(U.OBSERVER, (63, 60), cloaked=True)
    obs2._proto.cloak = 2                                                 # CloakedDetected: a detector (Raven, turret, ...) sees it now
    asyncio.run(refresh_ability_cache(sc2.ai, sc2.ai.units))
    ctx2 = begin(sc2)
    sc2.manager.cyclones.control(sc2.world.units([cy2]), orders(sc2), ctx2)
    c2 = cmds(sc2, cy2)
    check("cyclone: (control) once detected, it is locked on to like any other target",
          any(a == A.LOCKONAIR_LOCKONAIR and getattr(t, "tag", None) == obs2.tag for a, t, q in c2), str(c2))


def test_cyclone_backs_off_instead_of_idling_or_walking_blind_into_danger():
    """reported bug: a Cyclone stood below a ramp doing nothing while enemies above shot it - idle and an easy target. With no visible
    target at all (the usual reason: the enemy holds higher ground the Cyclone has no vision onto, while Ares' grid still knows the spot
    is dangerous from earlier vision) _control_unit takes the _no_fight branch, which used to never check ctx.is_safe - every OTHER branch
    does. HOLD stood there doing nothing at all; ATTACK attack-moved straight through the danger it could not even see."""
    sc = mk()
    cy = sc.own(U.CYCLONE, (60, 60))
    sc.ai.mediator.ground[55:66, 55:66] = 60.0                            # in danger, nothing visible to fight
    ctx = begin(sc)
    sc.manager.cyclones.control(sc.world.units([cy]), orders(sc), ctx)    # Mode.ATTACK: aggressive
    c = cmds(sc, cy)
    check("cyclone: no target and in danger while attacking - it backs off instead of attack-moving blind through the danger",
          any(a == A.MOVE_MOVE for a, t, q in c) and not any(a in (A.ATTACK, A.ATTACK_ATTACK) for a, t, q in c), str(c))
    sc2 = mk()
    cy2 = sc2.own(U.CYCLONE, (60, 60))
    sc2.ai.mediator.ground[55:66, 55:66] = 60.0
    ctx2 = begin(sc2)
    sc2.manager.cyclones.control(sc2.world.units([cy2]), orders(sc2, mode=Mode.HOLD), ctx2)
    check("cyclone: (HOLD, already at its spot) it still backs off rather than standing in the danger doing nothing",
          any(a == A.MOVE_MOVE for a, t, q in cmds(sc2, cy2)), str(cmds(sc2, cy2)))
    sc3 = mk()
    cy3 = sc3.own(U.CYCLONE, (60, 60))
    ctx3 = begin(sc3)
    sc3.manager.cyclones.control(sc3.world.units([cy3]), orders(sc3), ctx3)
    check("cyclone: (control) with nothing dangerous nearby it carries on as usual (attack-moves towards the objective)",
          any(a == A.ATTACK for a, t, q in cmds(sc3, cy3)), str(cmds(sc3, cy3)))


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
    check("cyclone: safe with the target well inside 15, it does not spend a second lock (which would end the first) - only a back-off (5.25 away, under the 6 standoff)",
          not any(a in (A.LOCKON_LOCKON, A.LOCKONAIR_LOCKONAIR) for a, t, q in c), str(c))


def test_locked_cyclone_backs_off_when_locked_too_close():
    """the lock drains the target from anywhere inside its range (15): a Cyclone that ends up locked on right next to the target (the
    generic combat path does not know about the cast range, and casts fine from well inside the Cyclone's own 5 weapon range) backs off
    to the standoff instead of sitting there for the whole duration - see MIN_LOCK_STANDOFF."""
    sc, cy, marine = _locked_cyclone()
    marine = _move(sc, marine, 61.0, buffs=[BuffId.LOCKON])              # 0.25 away: about as close as it gets
    c = _next_step(sc, cy)
    moves = [t for a, t, q in c if a == A.MOVE_MOVE]
    check("cyclone: locked right next to the target and safe, it backs off - and does not spend a second lock",
          len(moves) == 1 and not any(a in (A.LOCKON_LOCKON, A.LOCKONAIR_LOCKONAIR) for a, t, q in c), str(c))
    check("cyclone: ...to exactly the standoff (6 edge to edge), not further", abs(moves[0][0] - 54.25) < 0.05, str(c))


def test_locked_cyclone_does_not_move_once_at_the_standoff():
    sc, cy, marine = _locked_cyclone()
    marine = _move(sc, marine, 66.75, buffs=[BuffId.LOCKON])             # exactly 6 away (edge to edge): close enough already
    c = _next_step(sc, cy)
    check("cyclone: right at the standoff, it does not back off any further", c == [], str(c))
    sc, cy, marine = _locked_cyclone()
    marine = _move(sc, marine, 67.25, buffs=[BuffId.LOCKON])             # 6.5 away: comfortably past the standoff, well inside the hold
    c = _next_step(sc, cy)
    check("cyclone: (control) past the standoff and well inside the hold, it stays put", c == [], str(c))


def test_locked_cyclone_does_not_back_off_into_danger():
    sc, cy, marine = _locked_cyclone()                                    # 5.25 away: under the standoff, would back off to the west
    sc.ai.mediator.ground[50:60, 50:70] = 60.0                             # ...but the way west is fire; the cell it stands on is not
    c = _next_step(sc, cy)
    check("cyclone: too close but with nowhere safe to back off to, it holds position rather than stepping into fire", c == [], str(c))


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


def test_locked_cyclone_never_stops_short_of_safety_to_keep_the_lock():
    """The way out is cut where the target would leave the lock's range - but a cut that still ends in the fire is only more time in it, for
    a lock that is about to end anyway. The lock is kept by ways out that are safe; otherwise the Cyclone goes all the way out."""
    for target_x, gap in ((69.0, 9), (72.0, 12)):
        sc, cy, marine = _locked_cyclone()
        marine = _move(sc, marine, target_x, buffs=[BuffId.LOCKON])
        sc.ai.mediator.ground[52:80, 50:70] = 60.0                            # fire from 52 on (safe ground 9 back, at 51): the cut ends in it
        c = _next_step(sc, cy)
        moves = [t for a, t, q in c if a == A.MOVE_MOVE]
        check(f"cyclone: in fire with the target {gap} away, the lock's range cuts the way out short of safe ground: all the way out, not partway",
              len(moves) == 1 and moves[0][0] < 52, str(c))
    sc, cy, marine = _locked_cyclone()
    marine = _move(sc, marine, 69.0, buffs=[BuffId.LOCKON])
    sc.ai.mediator.ground[55:80, 50:70] = 60.0                                # (safe ground at 54: the cut - 54.75 - is on it)
    c = _next_step(sc, cy)
    moves = [t for a, t, q in c if a == A.MOVE_MOVE]
    check("cyclone: (control) a cut that reaches safe ground is still taken: the lock is kept", len(moves) == 1 and 54.3 < moves[0][0] < 55.3, str(c))


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
    check("cyclone: ...but a target that carries the lock keeps its lock (it only backs off - 5.25 away, under the 6 standoff)",
          cy.tag in sc.manager.cyclones.locks and not any(a in (A.LOCKON_LOCKON, A.LOCKONAIR_LOCKONAIR) for a, t, q in c), str((c, sc.manager.cyclones.locks)))


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


# ------------------------------------------------------------------------------------------------------------------------------
# DangerMemory (units/danger_memory.py): a spot known - or known a moment ago - to be defended is remembered past whatever gave it to
# us in the first place, until it is confirmed clear (seen again, empty) or a good while passes without either
# ------------------------------------------------------------------------------------------------------------------------------
def test_danger_memory_remembers_past_its_source_and_clears_on_sight_or_timeout():
    from bot.army.units.danger_memory import DangerMemory, REMEMBER_SECONDS
    sc = mk()
    mem = DangerMemory(sc.ai)
    spot = Point2((100, 100))
    mem.refresh([(spot, 6.0)])
    check("danger memory: a spot just given to it is remembered", mem.spots() == [(spot, 6.0)], str(mem.spots()))
    mem.refresh([])                                           # (its source is gone from this reading - not seen empty either)
    check("danger memory: it is still remembered once its source drops out of the current reading", mem.spots() == [(spot, 6.0)], str(mem.spots()))
    sc.ai._fake_time += REMEMBER_SECONDS - 1
    mem.refresh([])
    check("danger memory: ...for a good while", mem.spots() == [(spot, 6.0)], str(mem.spots()))
    sc.ai._fake_time += 2
    mem.refresh([])
    check("danger memory: ...but not forever, without ever seeing it empty", mem.spots() == [], str(mem.spots()))

    mem.refresh([(spot, 6.0)])
    sc.ai.visible.add(spot)                                   # we get vision of the exact spot again...
    mem.refresh([])                                           # ...and it is not there any more: the path is cleared
    check("danger memory: seeing the spot itself empty clears it at once, before the timeout", mem.spots() == [], str(mem.spots()))

    sc.ai.visible.discard(spot)                               # (start the next check without vision of the spot already lingering from above)
    mem.refresh([(spot, 6.0)])
    sc.ai.visible.add(Point2((130, 130)))                     # vision elsewhere does not clear it
    mem.refresh([])
    check("danger memory: vision somewhere else does not clear a remembered spot", mem.spots() == [(spot, 6.0)], str(mem.spots()))

    mem.refresh([(spot, 6.0)])
    mem.refresh([(spot, 7.5)])                                # seen again (a different reach): replaces the old reading, not added to it
    check("danger memory: seeing it again refreshes it (one entry, the new reach)", mem.spots() == [(spot, 7.5)], str(mem.spots()))


def test_danger_memory_avoiding_grid():
    from bot.army.units.danger_memory import DangerMemory, AVOID_EXTRA_COST
    sc = mk()
    mem = DangerMemory(sc.ai)
    grid = np.ones((40, 40), dtype=np.float32)
    grid[10, 10] = np.inf                                     # a building: must stay impassable, not just "expensive"
    check("danger memory: nothing remembered - the very same grid, untouched (no needless copy)", mem.avoiding_grid(grid) is grid)
    mem.refresh([(Point2((20, 20)), 3.0)])
    avoided = mem.avoiding_grid(grid)
    check("danger memory: a remembered spot piles a heavy cost on top, in a disk the size of its own reach",
          avoided[20, 20] == 1.0 + AVOID_EXTRA_COST and avoided[23, 20] == 1.0 + AVOID_EXTRA_COST and avoided[25, 20] == 1.0, str(avoided[18:27, 20]))
    check("danger memory: a building's cell stays impassable, not merely expensive", avoided[10, 10] == np.inf)
    check("danger memory: the original grid - shared with everything else this step - is not itself touched", grid[20, 20] == 1.0)


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


def test_reaper_route_avoids_a_remembered_danger_spot_when_touring():
    sc = mk()
    _enemy_base_with_minerals(sc)
    marine = sc.enemy(U.MARINE, (170, 150))                                    # stands well short of the mineral line, guarding the way there
    r = sc.own(U.REAPER, (150, 150))
    _reaper_step(sc, r)                                                       # sees it: a defender, and now remembered
    check("reaper: a defender in sight is remembered", sc.manager.reapers.danger.spots() != [], str(sc.manager.reapers.danger.spots()))
    mx, my = int(marine.position.x), int(marine.position.y)
    sc.ai._enemies.remove(marine)                                             # gone from sight (and, given enough time, from Ares' own memory too)
    grids = []
    real = sc.ai.mediator.find_path_next_point
    sc.ai.mediator.find_path_next_point = lambda **kw: (grids.append(kw["grid"]), real(**kw))[1]
    try:
        _reaper_step(sc, r)
    finally:
        sc.ai.mediator.find_path_next_point = real
    check("reaper: gone from sight, the spot it stood at is still routed around", grids and grids[0][mx, my] > 1.0, str(grids[0][mx, my] if grids else None))
    check("reaper: (control) the plain grid underneath is not itself changed", sc.ai.mediator.ground[mx, my] == 1.0)


def test_reaper_forgets_a_remembered_spot_once_it_sees_it_empty_again():
    sc = mk()
    _enemy_base_with_minerals(sc)
    marine = sc.enemy(U.MARINE, (170, 150))
    r = sc.own(U.REAPER, (150, 150))
    _reaper_step(sc, r)
    mx, my = int(marine.position.x), int(marine.position.y)
    sc.ai._enemies.remove(marine)
    sc.ai.visible.add(marine.position)                                        # a fresh look at the exact spot: nothing there any more
    grids = []
    real = sc.ai.mediator.find_path_next_point
    sc.ai.mediator.find_path_next_point = lambda **kw: (grids.append(kw["grid"]), real(**kw))[1]
    try:
        _reaper_step(sc, r)
    finally:
        sc.ai.mediator.find_path_next_point = real
    check("reaper: seeing the spot itself empty, the path is cleared at once - not routed around any more",
          grids and grids[0][mx, my] == 1.0, str(grids[0][mx, my] if grids else None))


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


# ------------------------------------------------------------------------------------------------------------------------------
# Cyclone raids against Protoss (units/cyclone_raid.py): lock on, step back, again - never without a Lock On, and only at what can be reached safely
# ------------------------------------------------------------------------------------------------------------------------------
def _raider(sc, pos, lock=True, air_lock=True, **kw):
    cy = sc.own(U.CYCLONE, pos, role=UnitRole.HARASSING, **kw)
    sc.ai.ability_grants[cy.tag] = ({A.LOCKON_LOCKON} if lock else set()) | ({A.LOCKONAIR_LOCKONAIR} if air_lock else set())
    return cy


def _raid_step(sc, *raiders, **order_kw):
    from bot.ares_compat import refresh_ability_cache
    asyncio.run(refresh_ability_cache(sc.ai, sc.ai.units))
    ctx = begin(sc)
    sc.manager.cyclone_raid.control(sc.world.units(list(raiders)), orders(sc, **order_kw), ctx)
    return [cmds(sc, cy) for cy in raiders] if len(raiders) > 1 else cmds(sc, raiders[0])


def _cast_on(c, target):
    return any(a in (A.LOCKON_LOCKON, A.LOCKONAIR_LOCKONAIR) and getattr(t, "tag", None) == target.tag for a, t, q in c)


def _no_attack(c):
    return not any(a in (A.LOCKON_LOCKON, A.LOCKONAIR_LOCKONAIR, A.ATTACK, A.ATTACK_ATTACK) for a, t, q in c)


def test_raid_locks_on_to_a_lone_unit_in_range_and_walks_up_to_one_out_of_it():
    sc = mk(enemy_race=Race.Protoss)
    cy = _raider(sc, (100, 100))
    stalker = sc.enemy(U.STALKER, (106, 100))
    c = _raid_step(sc, cy)
    check("raid: a lone Stalker in cast range: Lock On", _cast_on(c, stalker), str(c))
    check("raid: ...the lock is recorded (it kites now, cyclones.py)", sc.manager.cyclones.locks.get(cy.tag, (None,))[0] == stalker.tag, str(sc.manager.cyclones.locks))
    sc = mk(enemy_race=Race.Protoss)
    cy = _raider(sc, (100, 100))
    sc.enemy(U.STALKER, (114, 100))
    c = _raid_step(sc, cy)
    moves = [t for a, t, q in c if a == A.MOVE_MOVE]
    check("raid: one 14 away: it walks to a spot just inside the cast range of it (7 - a little), not into its own range", _no_attack(c) and moves and abs(moves[0][0] - 106.85) < 0.3, str(c))
    sc = mk(enemy_race=Race.Protoss)
    cy = _raider(sc, (100, 100))
    sc.enemy(U.STALKER, (135, 100))
    c = _raid_step(sc, cy)
    check("raid: ...one 35 away is not gone for (the search heads for it, below)", _no_attack(c), str(c))


def test_raid_target_priority_units_then_batteries_then_cannons_then_workers():
    def chosen(*enemies):
        sc = mk(enemy_race=Race.Protoss)
        cy = _raider(sc, (100, 100))
        made = {name: sc.enemy(type_id, pos) for name, type_id, pos in reversed(enemies)}      # (the least wanted is made first: a tie would pick it)
        c = _raid_step(sc, cy)
        return next((name for name, e in made.items() if _cast_on(c, e)), None), c
    # (far apart, so that none of them makes the cast on another unsafe)
    everything = (("stalker", U.STALKER, (100, 106.5)), ("battery", U.SHIELDBATTERY, (106.5, 100)), ("cannon", U.PHOTONCANNON, (100, 120)),
                  ("probe", U.PROBE, (93.5, 100)), ("pylon", U.NEXUS, (93, 93)))
    name, c = chosen(*everything)
    check("raid: units first (a Stalker, before a Battery, a Cannon, a Probe)", name == "stalker", str((name, c)))
    name, c = chosen(*everything[1:])
    check("raid: then Shield Batteries", name == "battery", str((name, c)))
    name, c = chosen(*everything[2:])
    check("raid: then Photon Cannons", name == "cannon" or (name is None and any(a == A.MOVE_MOVE for a, t, q in c)), str((name, c)))
    name, c = chosen(*everything[3:])
    check("raid: workers only when there is nothing else - and never a Nexus", name == "probe", str((name, c)))
    name, c = chosen(*everything[4:])
    check("raid: a Nexus alone is not a target", name is None and _no_attack(c), str((name, c)))


def test_raid_only_attacks_with_a_lock_on_available():
    sc = mk(enemy_race=Race.Protoss)
    cy = _raider(sc, (100, 100), lock=False, air_lock=False)
    sc.enemy(U.STALKER, (106, 100))
    c = _raid_step(sc, cy)
    check("raid: no Lock On -> no attack at all, and it backs out of the Stalker's reach instead", _no_attack(c) and any(a == A.MOVE_MOVE and t[0] < 100 for a, t, q in c), str(c))
    sc = mk(enemy_race=Race.Protoss)
    cy = _raider(sc, (100, 100), lock=False, air_lock=False)
    sc.enemy(U.STALKER, (120, 100))
    c = _raid_step(sc, cy)
    check("raid: ...out of reach of everything it waits: nothing is ordered", c == [], str(c))
    sc = mk(enemy_race=Race.Protoss)
    cy = _raider(sc, (100, 100), lock=True, air_lock=False)
    sc.enemy(U.VOIDRAY, (106, 100))
    c = _raid_step(sc, cy)
    check("raid: an air target needs the AIR Lock On: with only the ground one it does not cast (and backs off)", _no_attack(c), str(c))
    sc = mk(enemy_race=Race.Protoss)
    cy = _raider(sc, (100, 100), lock=False, air_lock=True)
    voidray = sc.enemy(U.VOIDRAY, (106, 100))
    c = _raid_step(sc, cy)
    check("raid: ...and with it, it locks on to the Void Ray", any(a == A.LOCKONAIR_LOCKONAIR and t.tag == voidray.tag for a, t, q in c), str(c))


def test_raid_leaves_what_it_cannot_reach_safely():
    sc = mk(enemy_race=Race.Protoss)
    cy = _raider(sc, (100, 100))
    sc.enemy(U.STALKER, (106, 100))
    sc.enemy(U.STALKER, (106, 103))                                        # two together: each covers the spot the cast on the other is made from
    c = _raid_step(sc, cy)
    check("raid: two Stalkers side by side are not 'almost free damage': no cast, it backs off", _no_attack(c) and any(a == A.MOVE_MOVE and t[0] < 100 for a, t, q in c), str(c))
    sc = mk(enemy_race=Race.Protoss)
    cy = _raider(sc, (100, 100))
    lone = sc.enemy(U.STALKER, (106, 100))
    sc.enemy(U.STALKER, (100, 125))                                        # another one, far off: no reason to hold back
    c = _raid_step(sc, cy)
    check("raid: (control) with the second one far away the first is locked on to", _cast_on(c, lone), str(c))
    sc = mk(enemy_race=Race.Protoss)
    cy = _raider(sc, (100, 100))
    near = sc.enemy(U.STALKER, (100, 106))                                 # it covers the Cyclone where it stands (and is locked on to already: not a target)
    sc.manager.cyclones.lock_ons[near.tag] = sc.ai.time
    sc.enemy(U.STALKER, (118, 100))                                        # the spot to cast on this one from is far from the first...
    c = _raid_step(sc, cy)
    check("raid: ...but the way there starts in the reach of the first: not taken - it backs off", not any(a == A.MOVE_MOVE and t[0] > 101 for a, t, q in c) and any(a == A.MOVE_MOVE and t[1] < 100 for a, t, q in c), str(c))


def test_raid_a_cannon_may_shoot_the_cast_but_nothing_else_may():
    sc = mk(enemy_race=Race.Protoss)
    cy = _raider(sc, (100, 100))
    cannon = sc.enemy(U.PHOTONCANNON, (108, 100))
    c = _raid_step(sc, cy)
    moves = [t for a, t, q in c if a == A.MOVE_MOVE]
    check("raid: a Cannon 8 away: it walks up to the cast range (its 7 reaches the spot: a shot or two is the price)", moves and abs(moves[0][0] - 100.85) < 0.3, str(c))
    sc = mk(enemy_race=Race.Protoss)
    cy = _raider(sc, (101, 100))
    cannon = sc.enemy(U.PHOTONCANNON, (108, 100))
    c = _raid_step(sc, cy)
    check("raid: ...and in cast range it locks on to it", _cast_on(c, cannon), str(c))
    sc = mk(enemy_race=Race.Protoss)
    cy = _raider(sc, (101, 100))
    cannon = sc.enemy(U.PHOTONCANNON, (108, 100), build_progress=0.5)
    c = _raid_step(sc, cy)
    check("raid: (an unfinished Cannon shoots nobody: no reason to stay out of its range, it is a target all the same)", _cast_on(c, cannon), str(c))


def test_raid_two_cyclones_do_not_lock_on_to_the_same_unit():
    sc = mk(enemy_race=Race.Protoss)
    a, b = _raider(sc, (100, 100)), _raider(sc, (100, 101))
    stalker = sc.enemy(U.STALKER, (106, 100))
    ca, cb = _raid_step(sc, a, b)
    check("raid: two Cyclones, one Stalker: one casts, the other does not spend its lock on the same unit", _cast_on(ca, stalker) != _cast_on(cb, stalker), str((ca, cb)))


def test_raid_goes_looking_and_stops_outside_reach():
    sc = mk(enemy_race=Race.Protoss)
    cy = _raider(sc, (100, 100))
    sc.enemy(U.PHOTONCANNON, (140, 100), visible=False)                    # a Cannon we saw before (a snapshot: cannot be locked on to)
    c = _raid_step(sc, cy)
    check("raid: nothing in sight: it heads for the Cannon it knows of - stopping outside its reach with the wider margin a merely-remembered spot gets",
          _no_attack(c) and any(a == A.MOVE_MOVE and abs(t[0] - 129.625) < 0.05 for a, t, q in c), str(c))
    sc = mk(enemy_race=Race.Protoss)
    cy = _raider(sc, (100, 100))
    c = _raid_step(sc, cy)
    check("raid: nothing known at all: it heads for their natural", any(a == A.MOVE_MOVE and abs(t[0] - 150) < 1 and abs(t[1] - 150) < 1 for a, t, q in c), str(c))
    sc = mk(enemy_race=Race.Protoss)
    cy = _raider(sc, (100, 100))
    sc.enemy(U.STALKER, (125, 100))                                        # too far to go for (24 gap) - but it is where the search goes, and it can hit back
    c = _raid_step(sc, cy)
    moves = [t for a, t, q in c if a == A.MOVE_MOVE]
    check("raid: ...and it stops outside the reach of what it sees on the way (a Stalker's 6 + radii + margin)", moves and 116 < moves[0][0] < 117.5, str(c))


def test_raid_walks_towards_a_lone_worker_beyond_engage_range():
    """with nothing else around, a worker beyond RAID_ENGAGE_RANGE used to be excluded from _destination (ATTACK_TARGET_IGNORE_WITH_WORKERS,
    meant for _rank/covering, not for "is there anything at all worth walking towards") - the raider went to the enemy's natural instead
    and then just sat there, even though _pick_target locks on to a worker "when there is nothing else" once close enough."""
    sc = mk(enemy_race=Race.Protoss)
    cy = _raider(sc, (100, 100))
    probe = sc.enemy(U.PROBE, (125, 100))                                     # 24.25 away: beyond RAID_ENGAGE_RANGE (20), within RAID_SIGHT (28)
    c = _raid_step(sc, cy)
    moves = [t for a, t, q in c if a == A.MOVE_MOVE]
    check("raid: with only a distant worker known, it walks towards it (stopping short at the standoff, not overshooting to a filler point like their natural)",
          _no_attack(c) and moves and 110 < moves[0][0] < 125, str(c))


def test_raid_search_stands_off_from_a_lockable_target_instead_of_walking_onto_it():
    """approaching something worth a lock (a worker, most often - nothing else was left to walk towards) must not walk fully onto it: the
    search stops short by the same margin _pick_target casts from, exactly like it already does for anything that can hit back."""
    sc = mk(enemy_race=Race.Protoss)
    cy = _raider(sc, (100, 100))
    probe = sc.enemy(U.PROBE, (125, 100))                                     # beyond engage range: _search does the walking, not _pick_target
    c = _raid_step(sc, cy)
    moves = [t for a, t, q in c if a == A.MOVE_MOVE]
    check("raid: the search itself already stands off - it does not walk onto the worker just because nothing threatens the way there",
          moves and moves[0][0] < probe.position.x - 5.0, str(c))


def test_raid_route_avoids_a_remembered_danger_spot_when_searching():
    sc = mk(enemy_race=Race.Protoss)
    cy = _raider(sc, (100, 100))
    stalker = sc.enemy(U.STALKER, (112, 100))                                  # stands on the way to the Nexus beyond it
    sc.enemy(U.NEXUS, (140, 100))
    _raid_step(sc, cy)                                                        # sees it: remembered as dangerous
    remembered = sc.manager.cyclone_raid.danger.spots()
    check("raid: a threat on the way is remembered", len(remembered) == 1 and abs(remembered[0][0].x - 112) < 0.5, str(remembered))
    sc.ai._enemies.remove(stalker)                                            # gone from sight (and, given enough time, from Ares' own memory too)
    c = _raid_step(sc, cy)
    moves = [t for a, t, q in c if a == A.MOVE_MOVE]
    stop_at = 112 - remembered[0][1]
    check("raid: gone from sight, it still does not walk back through where it stood - it stops short of it, heading for the Nexus beyond",
          moves and abs(moves[0][0] - stop_at) < 0.5 and moves[0][0] < 108, str((moves, stop_at)))

    sc = mk(enemy_race=Race.Protoss)                                          # (control: the same walk, but the Stalker was never seen - nothing remembered)
    cy = _raider(sc, (100, 100))
    sc.enemy(U.NEXUS, (140, 100))
    c = _raid_step(sc, cy)
    moves = [t for a, t, q in c if a == A.MOVE_MOVE]
    check("raid: (control) with nothing remembered it walks straight for the Nexus", moves and moves[0][0] > 135, str(c))


def test_raid_keeps_backing_off_a_remembered_spot_once_the_threat_is_a_stale_ghost():
    """reported bug: a Cyclone stood below a ramp doing nothing while enemies above shot it. FIGHT_GHOST_MAX_AGE (12s) is short, tuned for
    the whole army's fight decisions: once a threat's own ghost is older than that, `covering` (the live reach check `_info`/`_threatens`
    uses) stops seeing it - but the Cyclone may still be standing exactly where it was shot from, and `danger.spots()` (DangerMemory, up to
    45s) still does. Without also checking that here, a Cyclone waiting out Lock On's cooldown (or with nothing worth casting on) simply
    stopped reacting once the ghost aged out - not searching (nothing new to search for), not stepping back (`covering` empty), sitting at
    the foot of the exact ramp it was shot from."""
    def scene(lock_available):
        sc = mk(enemy_race=Race.Protoss)
        cy = _raider(sc, (100, 100), lock=lock_available, air_lock=lock_available)
        stalker = sc.enemy(U.STALKER, (106, 100))
        _raid_step(sc, cy)                                                    # step 1: reacts to the live Stalker (locks on to it, or backs off)
        sc.ai._enemies.remove(stalker)
        ghost = sc.enemy(stalker.type_id, (106.0, 100.0), tag=stalker.tag)
        ghost._ghost = True
        ghost.game_loop = 1
        sc.ai.state.game_loop = 300                                          # the next step's begin() pushes its age well past FIGHT_GHOST_MAX_AGE (12s)
        return _raid_step(sc, cy)
    for label, lock in (("Lock On available", True), ("Lock On on cooldown", False)):
        c = scene(lock)
        moves = [t for a, t, q in c if a == A.MOVE_MOVE]
        check(f"raid ({label}): a stale ghost past FIGHT_GHOST_MAX_AGE still remembered by DangerMemory keeps the Cyclone backing out, not idle",
              len(moves) == 1 and moves[0][0] < 100, str(c))


def test_raid_hurt_cyclone_goes_home_and_comes_back():
    sc = mk(enemy_race=Race.Protoss)
    cy = _raider(sc, (100, 100), hp=60)
    sc.enemy(U.STALKER, (106, 100))
    c = _raid_step(sc, cy)
    check("raid: a Cyclone that is too damaged goes home to be repaired instead of locking on", _no_attack(c) and any(a == A.MOVE_MOVE and abs(t[0] - 60) < 1 for a, t, q in c) and cy.tag in sc.manager.cyclones.repair.retreating, str(c))
    sc.ai._own.remove(cy)
    cy = sc.own(U.CYCLONE, (62, 60), tag=cy.tag, role=UnitRole.HARASSING, hp=170)
    sc.ai.ability_grants[cy.tag] = {A.LOCKON_LOCKON}
    _raid_step(sc, cy)
    check("raid: ...and is back at it once it is repaired (above 90%)", cy.tag not in sc.manager.cyclones.repair.retreating, str(sc.manager.cyclones.repair.retreating))


def test_raid_a_waiting_cyclone_does_not_shoot_what_is_in_its_range():
    sc = mk(enemy_race=Race.Protoss)
    cy = _raider(sc, (100, 100), lock=False, air_lock=False)
    sc.enemy(U.PROBE, (103, 100))
    sc.enemy(U.NEXUS, (98, 106))
    c = _raid_step(sc, cy)
    check("raid: no Lock On and workers or buildings in its weapon range: it steps out of it (idle, it would shoot them)",
          _no_attack(c) and any(a == A.MOVE_MOVE for a, t, q in c), str(c))
    sc = mk(enemy_race=Race.Protoss)
    cy = _raider(sc, (100, 100), lock=False, air_lock=False)
    sc.enemy(U.PROBE, (108, 100))
    c = _raid_step(sc, cy)
    check("raid: ...out of it (8 away) it stays where it is", c == [], str(c))


# ------------------------------------------------------------------------------------------------------------------------------
# "kite in" stops 1 short of the target (edge to edge): not right up to it, where our own Siege Tanks' splash reaches
# ------------------------------------------------------------------------------------------------------------------------------
def _kite_in(unit_type, target_x, cooldown=10.0, controller="bio"):
    """a Marine (or Cyclone) at x = 60 that is winning and whose weapon is on cooldown, with a Roach at `target_x` (and the enemy fire that would make it back off)"""
    sc = mk()
    m = sc.own(unit_type, (60, 60), cooldown=cooldown)
    roach = sc.enemy(U.ROACH, (target_x, 60))
    danger(sc, (61, 60), radius=3)
    ctx = begin(sc)
    getattr(sc.manager, controller).control(sc.world.units([m]), orders(sc, local=ER.VICTORY_EMPHATIC), ctx)
    return cmds(sc, m), roach


def test_kite_in_stops_one_short_of_the_target():
    c, roach = _kite_in(U.MARINE, 64.0)
    moves = [t for a, t, q in c if a == A.MOVE_MOVE]
    check("kite in: a Marine steps forward, to a spot 1 (edge to edge) short of its target - not onto it", moves and abs(moves[0][0] - 62.25) < 0.1 and abs(moves[0][1] - 60) < 0.1, str(c))
    c, roach = _kite_in(U.MARINE, 61.5)                                    # already within 1: (0.75 apart, edge to edge)
    check("kite in: ...one that is that close already does not step in any closer (it keeps its attack order on the target)",
          not any(a == A.MOVE_MOVE for a, t, q in c) and any(a == A.ATTACK and getattr(t, "tag", None) == roach.tag for a, t, q in c), str(c))
    c, roach = _kite_in(U.MARINE, 62.0)                                    # 1.25 apart: a quarter of a step to go
    moves = [t for a, t, q in c if a == A.MOVE_MOVE]
    check("kite in: ...a gap just over 1 is closed, no further", moves and abs(moves[0][0] - 60.25) < 0.1, str(c))
    c, roach = _kite_in(U.MARINE, 61.0, cooldown=0.0)
    check("kite in: with the weapon ready it shoots, however close", any(a == A.ATTACK and getattr(t, "tag", None) == roach.tag for a, t, q in c) and not any(a == A.MOVE_MOVE for a, t, q in c), str(c))
    c, roach = _kite_in(U.CYCLONE, 64.0, controller="cyclones")
    moves = [t for a, t, q in c if a == A.MOVE_MOVE]
    check("kite in: a Cyclone as well", moves and abs(moves[0][0] - 62.25) < 0.1, str(c))


# ------------------------------------------------------------------------------------------------------------------------------
# a Cyclone that is too damaged goes home to be repaired - like a Banshee (units/repair_retreat.py)
# ------------------------------------------------------------------------------------------------------------------------------
def test_hurt_cyclone_goes_home_to_be_repaired():
    sc = mk()
    cy = sc.own(U.CYCLONE, (100, 100), hp=60)                              # a third of its 180
    sc.enemy(U.ZEALOT, (110, 100))
    c = _next_step(sc, cy)
    check("cyclone: one below 40% of its health goes home (the hold point, where the SCVs come) instead of fighting",
          any(a == A.MOVE_MOVE and abs(t[0] - 60) < 1 and abs(t[1] - 60) < 1 for a, t, q in c) and not any(a in (A.ATTACK, A.LOCKON_LOCKON) for a, t, q in c)
          and cy.tag in sc.manager.cyclones.repair.retreating, str(c))
    sc = mk()
    cy = sc.own(U.CYCLONE, (100, 100), hp=90)                              # half: not yet
    sc.enemy(U.ZEALOT, (110, 100))
    _next_step(sc, cy)
    check("cyclone: (control) at half its health it stays in the fight", cy.tag not in sc.manager.cyclones.repair.retreating, str(sc.manager.cyclones.repair.retreating))
    sc = mk()
    cy = sc.own(U.CYCLONE, (100, 100), hp=60, role=UnitRole.HARASSING)
    sc.ai.ability_grants[cy.tag] = {A.LOCKON_LOCKON}
    sc.enemy(U.STALKER, (106, 100))
    from bot.ares_compat import refresh_ability_cache
    asyncio.run(refresh_ability_cache(sc.ai, sc.ai.units))
    ctx = begin(sc)
    sc.manager.cyclone_raid.control(sc.world.units([cy]), orders(sc), ctx)
    c = cmds(sc, cy)
    check("cyclone: a raider as well - no Lock On for a Cyclone that has to go home", not any(a == A.LOCKON_LOCKON for a, t, q in c) and any(a == A.MOVE_MOVE and abs(t[0] - 60) < 1 for a, t, q in c), str(c))


def test_hurt_cyclone_waits_for_the_repair_and_gives_up_when_nobody_comes():
    from bot.army.units.repair_retreat import RepairRetreat
    patience = RepairRetreat(None, None).patience
    sc = mk()
    cy = sc.own(U.CYCLONE, (62, 60), hp=60)                                # at the hold point, hurt
    c = _next_step(sc, cy)
    check("cyclone: at the hold point it waits there (nothing is ordered)", c == [] and cy.tag in sc.manager.cyclones.repair.retreating, str(c))
    for _ in range(int(patience / 0.5) + 4):
        c = _next_step(sc, cy)
    check("cyclone: with nobody repairing it it gives up after the patience and is back at its work - and not sent home again straight away",
          cy.tag not in sc.manager.cyclones.repair.retreating and cy.tag in sc.manager.cyclones.repair.no_retreat_until, str((c, sc.manager.cyclones.repair.retreating)))
    sc = mk()
    cy = sc.own(U.CYCLONE, (62, 60), hp=60)
    _next_step(sc, cy)
    for i in range(int(patience / 0.5) + 12):                              # an SCV repairs it: a hit point per look - it keeps waiting, as long as that goes on
        sc.ai._own.remove(cy)
        cy = sc.own(U.CYCLONE, (62, 60), tag=cy.tag, hp=60 + i)
        _next_step(sc, cy)
    check("cyclone: while the repair goes on it keeps waiting", cy.tag in sc.manager.cyclones.repair.retreating and cy.tag not in sc.manager.cyclones.repair.no_retreat_until, str(sc.manager.cyclones.repair.no_retreat_until))


# ------------------------------------------------------------------------------------------------------------------------------
# a locked-on cyclone backs out of fire where it keeps the target in view (the lock ends when the target is out of view): not down a ramp
# ------------------------------------------------------------------------------------------------------------------------------
def _plateau_lock(fire_y_to=65, target_type=U.MARINE, plateau=True):
    """a Cyclone on a plateau (everything from x = 58 is a level higher than the low ground to the west) that has locked on to a target 5 east of
    it, standing in fire: the nearest safe ground is DOWN the plateau's edge to the west (5 away, 10 from the target - inside the Cyclone's
    sight, but from the low ground the target on the plateau cannot be seen); the other safe ground is to the north (5.5 away, 7 from the target)"""
    sc, cy, marine = _locked_cyclone()
    if plateau:
        sc.ai.game_info.terrain_height.data_numpy[:, 58:] = 48
    sc.ai._enemies.remove(marine)
    target = sc.enemy(target_type, (65.0, 60), tag=marine.tag, buffs=[BuffId.LOCKON])
    sc.ai.mediator.ground[56:66, 50:fire_y_to] = 60.0
    return sc, cy, target


def _way_out(sc, cy, **order_kw):
    c = _next_step(sc, cy, **order_kw)
    return [t for a, t, q in c if a == A.MOVE_MOVE], c


def test_locked_cyclone_backs_out_where_it_keeps_the_target_in_view():
    sc, cy, target = _plateau_lock()
    moves, c = _way_out(sc, cy)
    check("cyclone: in fire with a lock on, it does not back down off the plateau (from below the target cannot be seen): it goes along the top, to the safe ground in the north",
          len(moves) == 1 and abs(moves[0][0] - 60) < 0.6 and abs(moves[0][1] - 65) < 0.6, str(c))
    sc, cy, target = _plateau_lock(target_type=U.VOIDRAY)
    moves, c = _way_out(sc, cy)
    check("cyclone: (a flying target is seen over any cliff) it backs out the plain way, to the nearest safe ground", len(moves) == 1 and 54.5 < moves[0][0] < 55.6, str(c))
    sc, cy, target = _plateau_lock(plateau=False)
    moves, c = _way_out(sc, cy)
    check("cyclone: (control) on flat ground the way out is the plain one", len(moves) == 1 and 54.5 < moves[0][0] < 55.6, str(c))
    sc, cy, target = _plateau_lock(fire_y_to=80)                             # no safe ground up there within reach...
    sc.ai.mediator.ground[56:80, 50:80] = 60.0                                # ...nor to the east of it, within its own sight of the target
    moves, c = _way_out(sc, cy)
    check("cyclone: with no way out that keeps the target in view it still backs out (the Cyclone comes first)", len(moves) == 1 and 54.5 < moves[0][0] < 55.6, str(c))
    sc, cy, target = _plateau_lock()
    moves, c = _way_out(sc, cy, mode=Mode.HOLD, retreating=True)
    check("cyclone: a retreating group's Cyclone goes home (it stands on the hold point here), not to a spot that keeps the view",
          len(moves) == 1 and abs(moves[0][0] - 60) < 1 and abs(moves[0][1] - 60) < 1, str(c))


def test_locked_cyclone_view_is_only_worth_a_short_detour():
    sc, cy, target = _plateau_lock(fire_y_to=68)                              # the only way out that keeps the view is 9 away, the plain one (down the cliff) 5
    moves, c = _way_out(sc, cy)
    check("cyclone: a way out that keeps the target in view but is far longer than the plain one is a walk through the fire: not taken",
          len(moves) == 1 and 54.5 < moves[0][0] < 55.6, str(c))
    sc, cy, target = _plateau_lock()                                          # (here it is 5.25 away: 5.25 more than the plain one is not)
    moves, c = _way_out(sc, cy)
    check("cyclone: (control) one that is only a little longer is worth it: it goes along the top",
          len(moves) == 1 and abs(moves[0][0] - 60) < 0.6 and abs(moves[0][1] - 65) < 0.6, str(c))


def test_locked_cyclone_out_of_its_own_sight_is_fine_when_something_else_sees_the_target():
    # the lock ends when the target is out of view - whoever sees it: a marine on the plateau sees it, so the plain way out (down the ramp) keeps the lock
    sc, cy, target = _plateau_lock()
    sc.own(U.MARINE, (62.0, 62.0))
    moves, c = _way_out(sc, cy)
    check("cyclone: a unit of ours on the plateau watches the target: the Cyclone backs out the plain way", len(moves) == 1 and 54.5 < moves[0][0] < 55.6, str(c))
    sc, cy, target = _plateau_lock()
    sc.own(U.MARINE, (57.0, 62.0))                                            # ...one on the low ground, within its sight range of the target, does not: the cliff is in the way
    moves, c = _way_out(sc, cy)
    check("cyclone: a unit of ours below the plateau does not: it keeps its own view", len(moves) == 1 and abs(moves[0][0] - 60) < 0.6 and abs(moves[0][1] - 65) < 0.6, str(c))
    sc, cy, target = _plateau_lock()
    sc.own(U.VIKINGFIGHTER, (57.0, 62.0))                                     # a flyer sees over the cliff
    moves, c = _way_out(sc, cy)
    check("cyclone: a flyer of ours below the plateau does watch it", len(moves) == 1 and 54.5 < moves[0][0] < 55.6, str(c))
    sc, cy, target = _plateau_lock()
    sc.own(U.MARINE, (75.0, 60.0))                                            # on the plateau, but 10 from the target: beyond a Marine's sight (9)
    moves, c = _way_out(sc, cy)
    check("cyclone: a unit of ours too far from the target to see it does not count", len(moves) == 1 and abs(moves[0][0] - 60) < 0.6 and abs(moves[0][1] - 65) < 0.6, str(c))


def test_locked_cyclone_prefers_spots_within_its_own_sight():
    sc, cy, marine = _locked_cyclone()
    marine = _move(sc, marine, 68.0, buffs=[BuffId.LOCKON])                  # 8 away
    grid = sc.ai.mediator.ground
    grid[40:80, 40:80] = 60.0
    grid[57, 60] = 1.0                                                        # safe: 3 to the west, 11 from the target - past the Cyclone's sight (11)
    grid[60, 65] = 1.0                                                        # safe: 5.25 to the north (one of the search rings), 9.5 from the target - inside it
    grid[63, 60] = 1.0                                                        # safe: 3 to the east, 5 from the target - the way out would be a step towards it (and it is looked at first)
    ctx = begin(sc)
    spot = sc.manager.cyclones._spot_with_view(sc.world.units([cy])[0], marine, ctx, ctx.ground_grid)
    check("cyclone: of the spots that keep the view it takes one within its own sight, however far it is (the nearer one would be out of it) - and never one nearer the target",
          spot is not None and abs(spot.x - 60.0) < 0.3 and abs(spot.y - 65.25) < 0.3, str(spot))


def test_locked_cyclone_view_search_reaches_as_far_as_its_own_sight():
    """A single defender's own realistic danger radius (its weapon range plus Ares' own 4-cell buffer) is routinely 9-12 - farther than a
    fixed handful of cells would ever reach (found by search, not guessed - see the session notes): a disk of 10 centred 2 north of the
    Cyclone is one such case. The plain retreat (the nearest safe cell) heads north-west, well out of the target's view; the search must
    reach as far as the Cyclone's own sight to find the alternative to the east that keeps it."""
    sc, cy, marine = _locked_cyclone()
    marine = _move(sc, marine, 66.0, buffs=[BuffId.LOCKON])
    grid = sc.ai.mediator.ground
    cx, cy_, radius = 60.0, 58.0, 10.0
    for x in range(grid.shape[0]):
        for y in range(grid.shape[1]):
            if (x - cx) ** 2 + (y - cy_) ** 2 <= radius ** 2:
                grid[x, y] = 60.0
    c = _next_step(sc, cy)
    moves = [t for a, t, q in c if a == A.MOVE_MOVE]
    check("cyclone: a realistic single-defender danger radius can be farther than a handful of cells - the search still finds a spot that keeps the target in view",
          len(moves) == 1 and np.hypot(moves[0][0] - 66.0, moves[0][1] - 60.0) <= 10.5 + 1e-6, str(c))


def test_terrain_view():
    from bot.pathing.order_utils import terrain_view
    p = Point2
    flat = np.zeros((100, 100), dtype=np.uint8)
    check("view: flat ground: seen", terrain_view(flat, p((10, 10)), p((20, 10))))
    high = flat.copy()
    high[:, 50:] = 48
    check("view: from the low ground up onto the high ground: not seen", not terrain_view(high, p((40, 10)), p((60, 10))))
    check("view: from the high ground down onto the low ground: seen", terrain_view(high, p((60, 10)), p((40, 10))))
    ramp = flat.copy()
    ramp[:, 50:] = 6
    check("view: a small rise (the same level, a ramp's foot): seen", terrain_view(ramp, p((40, 10)), p((60, 10))))
    hill = flat.copy()
    hill[:, 45:47] = 40
    check("view: behind a rise higher than both: not seen", not terrain_view(hill, p((40, 10)), p((60, 10))))
    check("view: (a point off the map is clamped, nothing raises)", terrain_view(flat, p((-5, -5)), p((150, 150))))


def test_raid_geometry():
    from bot.army.units.cyclone_raid import clip_before, segment_hits_circle
    p = Point2
    check("raid geometry: a way that passes a circle within its radius hits it, one that misses does not",
          segment_hits_circle(p((0, 0)), p((10, 0)), p((5, 2)), 3) and not segment_hits_circle(p((0, 0)), p((10, 0)), p((5, 4)), 3)
          and not segment_hits_circle(p((0, 0)), p((4, 0)), p((10, 0)), 3))
    q = clip_before(p((0, 0)), p((20, 0)), [(p((15, 0)), 5)])
    check("raid geometry: clipped before it enters a circle", abs(q.x - 10) < 1e-9 and abs(q.y) < 1e-9, str(q))
    q = clip_before(p((0, 0)), p((20, 0)), [(p((15, 8)), 5), (p((12, 0)), 4)])
    check("raid geometry: ...the first of several", abs(q.x - 8) < 1e-9, str(q))
    check("raid geometry: no circle in the way: the whole way; a start inside one: no way at all",
          clip_before(p((0, 0)), p((20, 0)), [(p((15, 9)), 5)]) == p((20, 0)) and clip_before(p((0, 0)), p((20, 0)), [(p((2, 0)), 5)]) == p((0, 0)))


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
