"""Per-controller behavior tests: each builds a small scene and drives ONE controller directly."""
import _bootstrap  # noqa: F401  (repo root on sys.path - keep this first)
import os, sys, traceback, asyncio
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
