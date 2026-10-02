"""The reactions to what we scouted, in the whole bot on the real Ares hub (what production and macro actually order), and the production
building limits: never more than 8 Barracks, 2 Factories and 2 Starports - and more of them (up to that) when the bank piles up late, or
(Barracks only) whenever minerals are growing faster than we can spend them, at any point in the game.

  raven      a Dark Shrine scouted: the Starport makes a Raven first (not a Banshee)
  tank       a Roach Warren scouted: Marines are skipped while the Factory that stands ready lacks the money for a Siege Tank
  skytoss    a Stargate scouted: the Factory stops at 2 tanks and makes Cyclones
  turrets    a Dark Shrine scouted: an Engineering Bay, then a missile turret in the mineral line
  starport   ... and the Starport is built now, not once a second base is up
  caps       8 Barracks / 2 Factories / 2 Starports at most, the bank builds one more at a time while it piles up
  infantry_upgrades  the Engineering Bay's weapon/armor levels wait for the 3rd base
  mineral_banking    minerals growing faster than we can spend them calls for another Barracks, not only late-game
  bunkers    one Bunker each at our closest two bases to home (main, natural) - never a third, however many bases we take
  placement  a Bunker builds in front of the townhall, not behind the mineral line; turrets build closer in now

Against Protoss (a mech-led army, army_advisor.mech_focus):
  cyclones   the Factory makes Cyclones first, a Tank once three more Cyclones than 3 x tanks are out; money is held back for them
             (Marines carry on with what is left); the Cyclone research is ordered once we make Cyclones
  buildings  one Barracks for two bases (two at three), the Starport once the Factory stands, a second Factory at three bases, an
             Armory once the Starport is up AND the first bio upgrade is done, a Tech Lab on every Factory"""
import _bootstrap  # noqa: F401  (repo root on sys.path - keep this first)
import asyncio
import math
import random as random_module
from loguru import logger
from s2clientprotocol import common_pb2
from sc2.ids.ability_id import AbilityId as A
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.ids.upgrade_id import UpgradeId

import bot.macro as macro
import bot.production as production
import gamefix_more  # noqa: F401
from dynamic import BASES, run_frame, start_game
from test_dynamic import build_game
from bot.bot import SmoothBrainBot

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail and not cond else ""))


def with_addon(game, type_id, addon_type, pos):
    building = game.add(type_id, pos, 1)
    addon = game.add(addon_type, (pos[0] + 2.5, pos[1] - 0.5), 1)
    building.add_on_tag = addon.tag
    return building


def play(setup, race=common_pb2.Zerg, minerals=500, gas=200, supply=(60, 200), frames=4, upgrades=()):
    """Build the game, let `setup(game, cx, cy)` add to it, run a few frames; returns the set of abilities the bot ordered"""
    production.made_banshee = production.made_raven = False
    logger.remove()
    errors = []
    logger.add(lambda m: errors.append(str(m)) if m.record["level"].no >= 40 else None, colorize=False)
    game = build_game(race)
    cx, cy = BASES["our_main"]
    setup(game, cx, cy)
    game.minerals, game.vespene = minerals, gas
    bot = SmoothBrainBot()
    loop = asyncio.new_event_loop()
    client, proto_gi = loop.run_until_complete(start_game(game, bot))
    bot.build_order = []                                # the scripted opening is not what is being tested
    for i in range(frames):
        loop.run_until_complete(run_frame(game, bot, proto_gi, i, supply_used=supply[0], supply_cap=supply[1], upgrades=upgrades))
    assert not errors, errors[:1]
    return {a.ability for a in client.sent_actions}


def count_barracks(game, n, busy=True):
    """n Barracks in all (the game starts with one), each with a Marine in production so that none of them is 'idle'"""
    cx, cy = BASES["our_main"]
    have = [u for u in game.units_raw if u.unit_type == U.BARRACKS.value]
    for k in range(n - len(have)):
        game.add(U.BARRACKS, (cx + 14 + 4 * k, cy - 14), 1)
    if busy:
        for u in game.units_raw:
            if u.unit_type == U.BARRACKS.value and not u.orders:
                order = u.orders.add()
                order.ability_id = A.BARRACKSTRAIN_MARINE.value


def more_bases(game, n):
    for name in ("our_nat", "our_third", "enemy_third")[:n]:
        game.add(U.COMMANDCENTER, BASES[name], 1)


def mech():
    Protoss, Zerg = common_pb2.Protoss, common_pb2.Zerg

    def names(done):
        return str(sorted(a.name for a in done))

    def factory(cyclones=0, tanks=0):
        def setup(game, cx, cy):
            with_addon(game, U.FACTORY, U.FACTORYTECHLAB, (cx + 14, cy - 6))
            for k in range(cyclones):
                game.add(U.CYCLONE, (cx + 8 + 2 * (k % 5), cy + 12 + 2 * (k // 5)), 1)
            for k in range(tanks):
                game.add(U.SIEGETANK, (cx + 8 + 2 * k, cy + 8), 1)
        return setup

    # ---- what the Factory makes: Cyclones first, a tank for every three
    done = play(factory(), race=Protoss, minerals=600, gas=400, frames=1)
    check("cyclones: Protoss, an idle Factory with a Tech Lab: a Cyclone - not a Tank", A.TRAIN_CYCLONE in done and A.FACTORYTRAIN_SIEGETANK not in done, names(done))
    done = play(factory(), race=Zerg, minerals=600, gas=400, frames=1)
    check("cyclones (control): against Zerg the Tank comes first, as it did", A.FACTORYTRAIN_SIEGETANK in done and A.TRAIN_CYCLONE not in done, names(done))
    done = play(factory(cyclones=2), race=Protoss, minerals=600, gas=400, frames=1)
    check("cyclones: two out, no tank yet: another Cyclone", A.TRAIN_CYCLONE in done and A.FACTORYTRAIN_SIEGETANK not in done, names(done))
    done = play(factory(cyclones=3), race=Protoss, minerals=600, gas=400, frames=1)
    check("cyclones: three out, no tank yet: the tank is due", A.FACTORYTRAIN_SIEGETANK in done and A.TRAIN_CYCLONE not in done, names(done))
    done = play(factory(cyclones=3, tanks=1), race=Protoss, minerals=600, gas=400, frames=1)
    check("cyclones: three out and a tank: Cyclones again (the next tank waits for six)", A.TRAIN_CYCLONE in done and A.FACTORYTRAIN_SIEGETANK not in done, names(done))
    done = play(factory(cyclones=12, tanks=1), race=Protoss, minerals=600, gas=400, frames=1)
    check("cyclones: at the cap of 12 the Factory makes tanks (up to 4) instead of nothing", A.FACTORYTRAIN_SIEGETANK in done and A.TRAIN_CYCLONE not in done, names(done))
    done = play(factory(cyclones=12, tanks=4), race=Protoss, minerals=600, gas=400, frames=1)
    check("cyclones: ...and nothing once both are at their caps", A.FACTORYTRAIN_SIEGETANK not in done and A.TRAIN_CYCLONE not in done, names(done))

    # ---- cyclones get priority over bio: money is held for them
    done = play(factory(), race=Zerg, minerals=120, gas=100)
    check("priority (control): against Zerg the Barracks spends its 50 on a Marine at once", A.BARRACKSTRAIN_MARINE in done, names(done))
    done = play(factory(), race=Protoss, minerals=120, gas=100)
    check("priority: against Protoss no Marine while the Cyclone (125) is not paid for yet", A.BARRACKSTRAIN_MARINE not in done and A.TRAIN_CYCLONE not in done, names(done))
    done = play(factory(), race=Protoss, minerals=400, gas=100)
    check("priority: ...the moment there is enough the Factory builds it", A.TRAIN_CYCLONE in done, names(done))
    done = play(factory(), race=Protoss, minerals=120, gas=20)
    check("priority: no gas for a Cyclone (50) -> nothing is held back for it, Marines carry on", A.BARRACKSTRAIN_MARINE in done, names(done))

    # ---- the buildings: 1 Barracks, the Factory, the Starport; a second Factory later; the Armory
    def bases(n, barracks=1, factories=0, starports=0, armory=False):
        def setup(game, cx, cy):
            more_bases(game, n - 1)
            count_barracks(game, barracks)
            for k in range(factories):
                game.add(U.FACTORY, (cx + 14 + 4 * k, cy - 6), 1)
            for k in range(starports):
                game.add(U.STARPORT, (cx + 14 + 4 * k, cy + 4), 1)
            if armory:
                game.add(U.ARMORY, (cx - 10, cy - 12), 1)
        return setup
    done = play(bases(2, factories=1), race=Zerg, minerals=900, gas=300)
    check("buildings (control): against Zerg two bases build a second Barracks", A.TERRANBUILD_BARRACKS in done, names(done))
    done = play(bases(2, factories=1), race=Protoss, minerals=900, gas=300)
    check("buildings: against Protoss two bases keep ONE Barracks - and the Starport goes up once the Factory stands", A.TERRANBUILD_BARRACKS not in done and A.TERRANBUILD_STARPORT in done, names(done))
    done = play(bases(2, factories=1, starports=1), race=Protoss, minerals=900, gas=300)
    check("buildings: ...one Factory for two bases", A.TERRANBUILD_FACTORY not in done, names(done))
    done = play(bases(3, factories=1, starports=1), race=Protoss, minerals=900, gas=300)
    check("buildings: three bases: a second Factory and a second Barracks", A.TERRANBUILD_FACTORY in done and A.TERRANBUILD_BARRACKS in done, names(done))
    done = play(bases(3, barracks=2, factories=2, starports=1), race=Protoss, minerals=900, gas=300)
    check("buildings: ...and no third Barracks yet", A.TERRANBUILD_BARRACKS not in done, names(done))
    done = play(bases(2, factories=1, starports=1), race=Protoss, minerals=900, gas=300, upgrades=(UpgradeId.TERRANINFANTRYWEAPONSLEVEL1,))
    check("armory: against Protoss, two bases, the Starport up, and the first bio upgrade done: an Armory for the vehicle upgrades",
          A.TERRANBUILD_ARMORY in done, names(done))
    done = play(bases(2, factories=1, starports=1), race=Protoss, minerals=900, gas=300)
    check("armory: ...not before the first bio upgrade completes (the Cyclone's own upgrades need no Armory, so there is no reason to rush it)",
          A.TERRANBUILD_ARMORY not in done, names(done))
    done = play(bases(2, factories=1), race=Protoss, minerals=900, gas=300)
    check("armory: ...not before the Starport", A.TERRANBUILD_ARMORY not in done, names(done))
    done = play(bases(2, factories=1, starports=1, armory=True), race=Protoss, minerals=900, gas=300, upgrades=(UpgradeId.TERRANINFANTRYWEAPONSLEVEL1,))
    check("armory: ...and only one", A.TERRANBUILD_ARMORY not in done, names(done))
    done = play(bases(2, factories=1, starports=1), race=Zerg, minerals=900, gas=300)
    check("armory (control): against Zerg nothing calls for one yet", A.TERRANBUILD_ARMORY not in done, names(done))

    # ---- a Tech Lab on every Factory
    def two_factories(game, cx, cy):
        with_addon(game, U.FACTORY, U.FACTORYTECHLAB, (cx + 14, cy - 6))
        game.add(U.FACTORY, (cx + 20, cy - 6), 1)
    done = play(two_factories, race=Protoss, minerals=600, gas=300)
    check("add-ons: against Protoss the second Factory gets a Tech Lab too", A.BUILD_TECHLAB_FACTORY in done and A.BUILD_REACTOR_FACTORY not in done, names(done))
    done = play(two_factories, race=Zerg, minerals=600, gas=300)
    check("add-ons (control): against Zerg it gets a Reactor", A.BUILD_REACTOR_FACTORY in done and A.BUILD_TECHLAB_FACTORY not in done, names(done))

    # ---- the Cyclone research
    done = play(factory(cyclones=1), race=Protoss, minerals=600, gas=300)
    check("research: a Cyclone out and an idle Tech Lab: the Cyclone upgrade the Tech Lab offers is researched", A.RESEARCH_CYCLONELOCKONDAMAGE in done, names(done))
    done = play(factory(), race=Protoss, minerals=600, gas=300, frames=1)
    check("research: ...but not before we make Cyclones (the first is being ordered in this very frame)", A.RESEARCH_CYCLONELOCKONDAMAGE not in done, names(done))
    done = play(factory(cyclones=1), race=Protoss, minerals=600, gas=300, upgrades=(UpgradeId.CYCLONELOCKONDAMAGEUPGRADE,))
    check("research: ...nor when it is done already", A.RESEARCH_CYCLONELOCKONDAMAGE not in done, names(done))
    done = play(factory(cyclones=1), race=Protoss, minerals=600, gas=50)
    check("research: ...nor without the gas for it", A.RESEARCH_CYCLONELOCKONDAMAGE not in done, names(done))


def upgrades():
    """The vehicle and ship upgrades (Armory) are bought - and the Armory built - once enough mech is out (custom_utils.next_mech_upgrade)"""
    Zerg = common_pb2.Zerg

    def names(done):
        return str(sorted(a.name for a in done))

    def mech(tanks=0, cyclones=0, banshees=0, armories=1, bases=2, hellions=0):
        def setup(game, cx, cy):
            more_bases(game, bases - 1)
            game.add(U.FACTORY, (cx + 14, cy - 6), 1)                       # (the Armory needs one)
            for k in range(armories):
                game.add(U.ARMORY, (cx - 10 - 4 * k, cy - 12), 1)
            for kind, count in ((U.SIEGETANK, tanks), (U.CYCLONE, cyclones), (U.BANSHEE, banshees), (U.HELLION, hellions)):
                for k in range(count):
                    game.add(kind, (cx + 8 + 2 * (k % 6), cy + 8 + 2 * (U.__members__[kind.name].value % 5 + k // 6)), 1)
        return setup

    def researched(done):
        return {a for a in done if a.name.startswith("ARMORYRESEARCH_")}
    W1, W2 = A.ARMORYRESEARCH_TERRANVEHICLEWEAPONSLEVEL1, A.ARMORYRESEARCH_TERRANVEHICLEWEAPONSLEVEL2
    done = play(mech(tanks=3), race=Zerg, minerals=900, gas=400, frames=2)
    check("upgrades: three Tanks (9 supply) and an Armory: vehicle weapons level 1", W1 in done, names(researched(done)))
    done = play(mech(tanks=2), race=Zerg, minerals=900, gas=400, frames=2)
    check("upgrades: two Tanks are not enough mech to justify them", not researched(done), names(researched(done)))
    done = play(mech(tanks=3), race=Zerg, minerals=900, gas=400, frames=2, upgrades=(UpgradeId.TERRANVEHICLEWEAPONSLEVEL1, UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL1))
    check("upgrades: level 2 wants more (15 supply): not with three Tanks", not researched(done), names(researched(done)))
    done = play(mech(tanks=5), race=Zerg, minerals=900, gas=400, frames=2, upgrades=(UpgradeId.TERRANVEHICLEWEAPONSLEVEL1, UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL1))
    check("upgrades: ...with five it is bought", W2 in done, names(researched(done)))
    done = play(mech(tanks=3), race=Zerg, minerals=1500, gas=600, frames=2, upgrades=(UpgradeId.TERRANVEHICLEWEAPONSLEVEL1, UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL1))
    check("upgrades: ...and so it is with three when the money is piling up", W2 in done, names(researched(done)))
    done = play(mech(tanks=5), race=Zerg, minerals=900, gas=400, frames=2)
    check("upgrades: level 2 only after level 1 (the Armory is asked for level 1)", W1 in done and W2 not in done, names(researched(done)))
    done = play(mech(banshees=3), race=Zerg, minerals=900, gas=400, frames=2)
    check("upgrades: ships are not vehicles: three Banshees get armor (it is for both) and no vehicle weapons",
          A.ARMORYRESEARCH_TERRANVEHICLEANDSHIPPLATINGLEVEL1 in done and W1 not in done, names(researched(done)))
    done = play(mech(banshees=3), race=Zerg, minerals=900, gas=400, frames=2, upgrades=(UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL1,))
    check("upgrades: ...and then ship weapons", A.ARMORYRESEARCH_TERRANSHIPWEAPONSLEVEL1 in done, names(researched(done)))
    done = play(mech(hellions=5), race=Zerg, minerals=900, gas=400, frames=2)
    check("upgrades: Hellions count too (5 x 2 supply)", W1 in done, names(researched(done)))

    # ---- the Armory
    done = play(mech(tanks=3, armories=0), race=Zerg, minerals=900, gas=400)
    check("armory: enough mech (9 supply) and two bases: an Armory is built, with no infantry upgrade in sight", A.TERRANBUILD_ARMORY in done, names(done))
    done = play(mech(tanks=2, armories=0), race=Zerg, minerals=900, gas=400)
    check("armory: ...not before", A.TERRANBUILD_ARMORY not in done, names(done))
    done = play(mech(tanks=4, armories=0, bases=1), race=Zerg, minerals=900, gas=400)
    check("armory: ...nor on one base", A.TERRANBUILD_ARMORY not in done, names(done))
    done = play(mech(tanks=4, armories=1), race=Zerg, minerals=900, gas=400)
    check("armory: ...and one is enough while the money is not piling up", A.TERRANBUILD_ARMORY not in done, names(done))
    done = play(mech(tanks=8, armories=1), race=Zerg, minerals=1500, gas=600)
    check("armory: a big mech army (24 supply) and the money piling up: a second, for weapons and armor at the same time", A.TERRANBUILD_ARMORY in done, names(done))
    done = play(mech(tanks=8, armories=2), race=Zerg, minerals=1500, gas=600)
    check("armory: ...and no third", A.TERRANBUILD_ARMORY not in done, names(done))


def infantry_upgrades():
    """The Engineering Bay's weapon/armor upgrades wait for the 3rd base (custom_utils.INFANTRY_UPGRADE_MIN_BASES) - unlike stim or
    cloak (a one-off buy), these come back every level and compete with actual unit production for money on every single step; a real
    game was seen where that alone stalled production to nothing."""
    Zerg = common_pb2.Zerg

    def with_ebay(bases):
        def setup(game, cx, cy):
            more_bases(game, bases - 1)
            game.add(U.ENGINEERINGBAY, (cx - 10, cy - 12), 1)
        return setup

    def researched(done):
        return {a for a in done if a.name.startswith("ENGINEERINGBAYRESEARCH_")}

    for bases in (1, 2):
        done = play(with_ebay(bases), race=Zerg, minerals=900, gas=400, frames=2)
        check(f"infantry upgrades: {bases} base(s) - not yet (they would compete with unit production every step)",
              not researched(done), str(sorted(a.name for a in done)))
    done = play(with_ebay(3), race=Zerg, minerals=900, gas=400, frames=2)
    check("infantry upgrades: three bases - now they are worth it",
          A.ENGINEERINGBAYRESEARCH_TERRANINFANTRYWEAPONSLEVEL1 in done or A.ENGINEERINGBAYRESEARCH_TERRANINFANTRYARMORLEVEL1 in done,
          str(sorted(a.name for a in done)))


def placement():
    """A Bunker builds in front of the townhall - the open side, away from the mineral line - rather than tucked
    behind the minerals like a turret (smart_build_in_front_of_base vs smart_build_behind_mineral). Turrets
    themselves now build closer in than before (6/9 instead of 9/12)."""
    Zerg = common_pb2.Zerg

    def run(setup, race=Zerg, minerals=300, gas=0):
        logger.remove()
        errors = []
        logger.add(lambda m: errors.append(str(m)) if m.record["level"].no >= 40 else None, colorize=False)
        game = build_game(race)
        cx, cy = BASES["our_main"]
        setup(game, cx, cy)
        game.minerals, game.vespene = minerals, gas
        bot = SmoothBrainBot()
        loop = asyncio.new_event_loop()
        client, proto_gi = loop.run_until_complete(start_game(game, bot))
        bot.build_order = []
        loop.run_until_complete(run_frame(game, bot, proto_gi, 0, supply_used=60, supply_cap=200))
        assert not errors, errors[:1]
        return bot, client.sent_actions

    def mineral_average(bot, cc):
        mfs = bot.mineral_field.closer_than(10, cc)
        return mfs.amount, sum(m.position.x for m in mfs) / mfs.amount, sum(m.position.y for m in mfs) / mfs.amount

    def with_natural(game, cx, cy):
        more_bases(game, 1)                 # a Bunker is never built at the main (see bunkers()) - needs a natural
        game.add_base_resources("our_nat")
    bot, actions = run(with_natural, minerals=600, gas=300)
    bunker_cmd = next((a for a in actions if a.ability == A.TERRANBUILD_BUNKER), None)
    check("placement: (premise) a bunker is actually built this step", bunker_cmd is not None,
          str(sorted(a.ability.name for a in actions)))
    if bunker_cmd is not None:
        cc = bot.townhalls.furthest_to(bot.start_location)   # the natural, not the main
        n, mx, my = mineral_average(bot, cc)
        to_minerals = (mx - cc.position.x, my - cc.position.y)
        to_bunker = (bunker_cmd.target.x - cc.position.x, bunker_cmd.target.y - cc.position.y)
        dot = to_minerals[0] * to_bunker[0] + to_minerals[1] * to_bunker[1]
        check("placement: the bunker goes on the OPPOSITE side of the townhall from the mineral line (not behind it)",
              dot < 0, f"to_minerals={to_minerals} to_bunker={to_bunker} dot={dot}")

    def with_ebay(game, cx, cy):
        game.add(U.DARKSHRINE, BASES["enemy_main"], 4)                     # triggers turrets_per_base=1 (reactions.py)
        game.add(U.ENGINEERINGBAY, (cx - 10, cy - 12), 1)
    bot, actions = run(with_ebay, race=common_pb2.Protoss, minerals=300)   # the dark-shrine reaction is Protoss-only
    turret_cmd = next((a for a in actions if a.ability == A.TERRANBUILD_MISSILETURRET), None)
    check("placement: (premise) a turret is actually built this step", turret_cmd is not None,
          str(sorted(a.ability.name for a in actions)))
    if turret_cmd is not None:
        cc = bot.townhalls.first
        dist = ((turret_cmd.target.x - cc.position.x) ** 2 + (turret_cmd.target.y - cc.position.y) ** 2) ** 0.5
        check("placement: the turret lands close to the townhall (<= 7.5) - tighter than the old 9/12",
              dist <= 7.5, str(dist))

    def with_wraparound_minerals(game, cx, cy):
        # a natural whose mineral line is NOT one tidy point: seven patches tightly clustered on one side, plus a
        # single patch almost exactly opposite them - an uneven spread a real base's mineral line can have. The
        # AVERAGE of all eight still points "away" back at the big cluster's own far side, which is exactly where
        # the lone patch sits - the premise this check exists to catch (see smart_build_in_front_of_base's docstring).
        more_bases(game, 1)
        nx, ny = BASES["our_nat"]
        # build_game() already seeded every named base (including this one) with its own standard, symmetric ring -
        # strip that out so this closure's deliberately uneven one is the only mineral line near this base
        game.units_raw = [
            p for p in game.units_raw
            if not (p.unit_type == U.MINERALFIELD.value and math.hypot(p.pos.x - nx, p.pos.y - ny) < 10)
        ]
        for deg in (-6, -4, -2, 0, 2, 4, 6):
            rad = math.radians(deg)
            game.add(U.MINERALFIELD, (nx + 7 * math.cos(rad), ny + 7 * math.sin(rad)), 3, mineral_contents=1800)
        game.add(U.MINERALFIELD, (nx - 7, ny), 3, mineral_contents=1800)   # the lone, far-side outlier

    # dead centre of the +-60 degree cone (worst case, right on the outlier) for the first try's 2 draws (position,
    # position_further), then a draw that lands at the cone's edge - clear of every patch - for every try after
    calls = [0]

    def rigged_random():
        calls[0] += 1
        return 0.5 if calls[0] <= 2 else 0.0

    original_random = random_module.random
    try:
        random_module.random = rigged_random
        bot, actions = run(with_wraparound_minerals, minerals=600, gas=300)
    finally:
        random_module.random = original_random
    bunker_cmd = next((a for a in actions if a.ability == A.TERRANBUILD_BUNKER), None)
    check("placement: (premise) a bunker is still built with an uneven, wraparound mineral line", bunker_cmd is not None,
          str(sorted(a.ability.name for a in actions)))
    if bunker_cmd is not None:
        cc = bot.townhalls.furthest_to(bot.start_location)
        nearby = bot.mineral_field.closer_than(14, cc)
        closest = min(mf.position.distance_to((bunker_cmd.target.x, bunker_cmd.target.y)) for mf in nearby)
        check("placement: ...and still lands clear of every real mineral patch, not just on the correct side of their average",
              closest >= macro.CLEAR_OF_MINERALS, f"closest={closest}")


def one_base_all_in():
    """A scouted opponent still sitting on one base well past normal expansion timing should not be matched with our
    own normal, greedy expansion pace (army_composition_advisor.enemy_likely_one_base; macro.py's
    holding_for_enemy_all_in, gating build_cc beyond our own natural)."""
    Terran = common_pb2.Terran

    def play_at(enemy_bases, target_time, minerals=900, gas=300):
        logger.remove()
        errors = []
        logger.add(lambda m: errors.append(str(m)) if m.record["level"].no >= 40 else None, colorize=False)
        game = build_game(Terran)
        cx, cy = BASES["our_main"]
        more_bases(game, 2)                                     # our own natural is already up (2 bases)
        count_barracks(game, 1)
        game.add(U.MARINE, (cx + 2, cy + 2), 1)                  # some army already, so holding_for_units never fires
        game.add(U.MARINE, (cx + 3, cy + 2), 1)
        game.add(U.COMMANDCENTER, BASES["enemy_main"], 4)        # their scouted main (the synthetic harness seeds no
        if enemy_bases >= 2:                                     # structure there on its own - only a start location)
            game.add(U.COMMANDCENTER, BASES["enemy_nat"], 4)     # the opponent's own second base
        game.minerals, game.vespene = minerals, gas
        bot = SmoothBrainBot()
        loop = asyncio.new_event_loop()
        client, proto_gi = loop.run_until_complete(start_game(game, bot))
        bot.build_order = []
        target_loop = int(target_time * 22.4)
        loop.run_until_complete(run_frame(game, bot, proto_gi, 0, frames=target_loop - game.game_loop,
                                           supply_used=60, supply_cap=200))
        assert not errors, errors[:1]
        return bot, {a.ability for a in client.sent_actions}

    def names(done):
        return str(sorted(a.name for a in done))

    bot, done = play_at(enemy_bases=1, target_time=200.0)
    check("one-base all-in: (premise) not flagged before the check window, whatever the base count",
          bot.army_advisor.enemy_likely_one_base is False, str(bot.time))
    check("one-base all-in: (control) so a 3rd base is still built normally that early",
          A.TERRANBUILD_COMMANDCENTER in done, names(done))

    bot, done = play_at(enemy_bases=1, target_time=320.0)
    check("one-base all-in: flagged once well past normal expansion timing with still only one base seen",
          bot.army_advisor.enemy_likely_one_base is True, str(bot.time))
    check("one-base all-in: ...and our own 3rd base is held off while it holds (our own natural is untouched)",
          A.TERRANBUILD_COMMANDCENTER not in done, names(done))

    bot, done = play_at(enemy_bases=2, target_time=320.0)
    check("one-base all-in (control): not flagged once a second enemy base is confirmed",
          bot.army_advisor.enemy_likely_one_base is False, str(bot.time))
    check("one-base all-in: ...and the 3rd base is built normally again",
          A.TERRANBUILD_COMMANDCENTER in done, names(done))

    bot, done = play_at(enemy_bases=1, target_time=320.0, minerals=2500)
    check("one-base all-in: ...but a mineral bank piling up past 2000 still gets spent on it anyway",
          A.TERRANBUILD_COMMANDCENTER in done, names(done))


def mineral_banking():
    """Minerals growing faster than we can spend them calls for one more Barracks (mineral-only production), at ANY
    point in the game - not only the pre-existing late-game bank (END_GAME_SUPPLY/BANK_MINERALS, still tested above
    via the `bank`/`caps` checks) - see custom_utils.mineral_income_outpacing_spend."""
    Zerg = common_pb2.Zerg

    def play_growing(start_minerals, step_minerals, steps, step_seconds=15.0, barracks=1, build_order=()):
        logger.remove()
        errors = []
        logger.add(lambda m: errors.append(str(m)) if m.record["level"].no >= 40 else None, colorize=False)
        game = build_game(Zerg)
        cx, cy = BASES["our_main"]
        count_barracks(game, barracks)
        game.minerals, game.vespene = start_minerals, 100
        bot = SmoothBrainBot()
        loop = asyncio.new_event_loop()
        client, proto_gi = loop.run_until_complete(start_game(game, bot))
        bot.build_order = list(build_order)
        done = set()
        for i in range(steps):
            game.minerals = start_minerals + step_minerals * i
            loop.run_until_complete(run_frame(game, bot, proto_gi, i, frames=int(step_seconds * 22.4),
                                               supply_used=60, supply_cap=200))
            done |= {a.ability for a in client.sent_actions}
        assert not errors, errors[:1]
        return bot, done

    def names(done):
        return str(sorted(a.name for a in done))

    # minerals climbing by 60 every 15s = 240/min, comfortably past MINERAL_BANK_RATE (150/min), bank staying well
    # under the late-game-only BANK_MINERALS (1000) throughout - this must be the new rule firing, not the old one
    bot, done = play_growing(start_minerals=500, step_minerals=60, steps=5)
    check("mineral banking: a steadily growing bank, well under the late-game threshold, still calls for another Barracks",
          A.TERRANBUILD_BARRACKS in done, names(done))

    # same bank size reached, but flat the whole time: income is not outpacing spend, so no extra Barracks from this rule
    bot, done = play_growing(start_minerals=500, step_minerals=0, steps=5)
    check("mineral banking (control): a flat bank calls for nothing", A.TERRANBUILD_BARRACKS not in done, names(done))

    # growing just as fast, but for too short a time (one step) to trust the average yet
    bot, done = play_growing(start_minerals=500, step_minerals=60, steps=1)
    check("mineral banking (control): not enough history yet to call it banking", A.TERRANBUILD_BARRACKS not in done, names(done))

    # the opening's natural: 300 -> 380 over three 15s steps is 160/min (past the 150 rate) while staying under the 400 the scripted
    # Command Center costs - the bank is that CC's money, not spare, so no extra Barracks may be bought out of it
    bot, done = play_growing(start_minerals=300, step_minerals=40, steps=3, build_order=[U.COMMANDCENTER])
    check("mineral banking: while the scripted opening still has the natural's Command Center ahead, the bank is its money - no 2nd Barracks",
          A.TERRANBUILD_BARRACKS not in done and A.TERRANBUILD_COMMANDCENTER not in done, names(done))
    bot, done = play_growing(start_minerals=300, step_minerals=40, steps=3)
    check("mineral banking (control): the very same bank with the opening done (nothing scripted left) does call for one",
          A.TERRANBUILD_BARRACKS in done, names(done))


def bunkers():
    """A Bunker at every base EXCEPT the main - never at the spawn itself, only from the second base onwards, with
    no cap on how many further bases get one (build_bunkers in macro.py). Needs only a Barracks."""
    Zerg = common_pb2.Zerg

    def names(done):
        return str(sorted(a.name for a in done))

    done = play(lambda g, cx, cy: None, race=Zerg, minerals=600)
    check("bunkers: one base (the main) only -> no Bunker, however much money is sitting around",
          A.TERRANBUILD_BUNKER not in done, names(done))

    def with_natural(game, cx, cy):
        more_bases(game, 1)                                               # our own natural
        game.add_base_resources("our_nat")                                 # smart_build_behind_mineral needs minerals
    done = play(with_natural, race=Zerg, minerals=600, gas=300)            # (600: two bases also want a 2nd Barracks/Factory this step)
    check("bunkers: a natural exists -> it gets a Bunker (the main never does, so there is no other candidate)",
          A.TERRANBUILD_BUNKER in done, names(done))
    done = play(with_natural, race=Zerg, minerals=50)
    check("bunkers (control): ...but not without enough minerals", A.TERRANBUILD_BUNKER not in done, names(done))

    def with_third_base(game, cx, cy):
        more_bases(game, 2)                                               # natural AND a third base
        game.add_base_resources("our_nat")
        nx, ny = BASES["our_nat"]
        game.add(U.BUNKER, (nx + 2, ny + 2), 1)                           # the natural already has one
    done = play(with_third_base, race=Zerg, minerals=2000)
    check("bunkers: the natural already has one and a third base exists -> the third gets one too (no cap)",
          A.TERRANBUILD_BUNKER in done, names(done))

    def every_other_base_done(game, cx, cy):
        more_bases(game, 2)                                               # natural AND a third base
        game.add_base_resources("our_nat")
        nx, ny = BASES["our_nat"]
        game.add(U.BUNKER, (nx + 2, ny + 2), 1)                           # natural
        tx, ty = BASES["our_third"]
        game.add(U.BUNKER, (tx + 2, ty + 2), 1)                           # third
    done = play(every_other_base_done, race=Zerg, minerals=5000)
    check("bunkers: every OTHER base already has one -> the main still never gets one, whatever the bank",
          A.TERRANBUILD_BUNKER not in done, names(done))


def main():
    # ---- a Dark Shrine: Raven first
    def starport(shrine):
        def setup(game, cx, cy):
            with_addon(game, U.STARPORT, U.STARPORTTECHLAB, (cx + 14, cy + 4))
            if shrine:
                game.add(U.DARKSHRINE, BASES["enemy_main"], 4)
        return setup
    # (one frame: the fake game never lets the Starport get busy, so a second frame would order the unit that comes after the first)
    done = play(starport(True), race=common_pb2.Protoss, minerals=600, gas=400, frames=1)
    check("raven: a Dark Shrine scouted -> the Starport makes a Raven", A.STARPORTTRAIN_RAVEN in done and A.STARPORTTRAIN_BANSHEE not in done, str(sorted(a.name for a in done)))
    done = play(starport(False), race=common_pb2.Protoss, minerals=600, gas=400, frames=1)
    check("raven (control): nothing scouted -> the usual Banshee first", A.STARPORTTRAIN_BANSHEE in done and A.STARPORTTRAIN_RAVEN not in done, str(sorted(a.name for a in done)))

    # ---- a Roach Warren: money is held back for the Siege Tank
    def factory(warren):
        def setup(game, cx, cy):
            with_addon(game, U.FACTORY, U.FACTORYTECHLAB, (cx + 14, cy - 6))
            if warren:
                game.add(U.ROACHWARREN, BASES["enemy_main"], 4)
        return setup
    done = play(factory(False), minerals=120, gas=200)
    check("tank (control): no Roach Warren -> the Barracks spends its 50 on a Marine at once", A.BARRACKSTRAIN_MARINE in done, str(sorted(a.name for a in done)))
    done = play(factory(True), minerals=120, gas=200)
    check("tank: a Roach Warren -> no Marine while the tank (150) is not paid for yet", A.BARRACKSTRAIN_MARINE not in done and A.FACTORYTRAIN_SIEGETANK not in done, str(sorted(a.name for a in done)))
    done = play(factory(True), minerals=360, gas=200)                # (the Command Center's Orbital and SCV take 200 of it first)
    check("tank: ...the moment there is enough the Factory builds it", A.FACTORYTRAIN_SIEGETANK in done, str(sorted(a.name for a in done)))
    done = play(factory(True), minerals=400, gas=200)
    check("tank: with plenty of money everything is bought", A.FACTORYTRAIN_SIEGETANK in done, str(sorted(a.name for a in done)))
    done = play(factory(True), minerals=120, gas=50)
    check("tank: no gas for a tank -> nothing is held back for it (Marines carry on)", A.BARRACKSTRAIN_MARINE in done, str(sorted(a.name for a in done)))

    # ---- skytoss: the Factory stops at 2 tanks and makes Cyclones instead
    def two_tanks(stargate):
        def setup(game, cx, cy):
            with_addon(game, U.FACTORY, U.FACTORYTECHLAB, (cx + 14, cy - 6))
            for k in range(2):
                game.add(U.SIEGETANK, (cx + 8 + 2 * k, cy + 8), 1)
            for k in range(9):                                     # (a mech-led army makes its third tank after nine Cyclones)
                game.add(U.CYCLONE, (cx + 8 + 2 * (k % 5), cy + 12 + 2 * (k // 5)), 1)
            if stargate:
                game.add(U.STARGATE, BASES["enemy_main"], 4)
        return setup
    done = play(two_tanks(False), race=common_pb2.Protoss, minerals=600, gas=400, frames=1)
    check("skytoss (control): no Stargate, two tanks out -> the Factory makes a third", A.FACTORYTRAIN_SIEGETANK in done, str(sorted(a.name for a in done)))
    done = play(two_tanks(True), race=common_pb2.Protoss, minerals=600, gas=400, frames=1)
    check("skytoss: a Stargate scouted, two tanks out -> no third tank, a Cyclone instead", A.FACTORYTRAIN_SIEGETANK not in done and A.TRAIN_CYCLONE in done, str(sorted(a.name for a in done)))

    # ---- a Dark Shrine: turrets, and the Starport now
    def base(shrine, ebay=False, factory_ready=True):
        def setup(game, cx, cy):
            if shrine:
                game.add(U.DARKSHRINE, BASES["enemy_main"], 4)
            if ebay:
                game.add(U.ENGINEERINGBAY, (cx - 10, cy - 12), 1)
            if factory_ready:
                game.add(U.FACTORY, (cx + 14, cy - 6), 1)
        return setup
    done = play(base(True), race=common_pb2.Protoss, minerals=600)
    check("turrets: a Dark Shrine scouted and no Engineering Bay -> one is built first", A.TERRANBUILD_ENGINEERINGBAY in done and A.TERRANBUILD_MISSILETURRET not in done, str(sorted(a.name for a in done)))
    done = play(base(True, ebay=True), race=common_pb2.Protoss, minerals=600)
    check("turrets: with the Bay up, a missile turret goes into the mineral line", A.TERRANBUILD_MISSILETURRET in done, str(sorted(a.name for a in done)))
    done = play(base(False, ebay=True), race=common_pb2.Protoss, minerals=600)
    check("turrets (control): nothing scouted -> no turret, no Bay", A.TERRANBUILD_MISSILETURRET not in done, str(sorted(a.name for a in done)))
    done = play(base(True), race=common_pb2.Protoss, minerals=600)
    check("starport: a Dark Shrine scouted -> the Starport is built at once, on one base", A.TERRANBUILD_STARPORT in done, str(sorted(a.name for a in done)))
    done = play(base(False), race=common_pb2.Protoss, minerals=600)
    check("starport (control): nothing scouted -> no Starport on one base", A.TERRANBUILD_STARPORT not in done, str(sorted(a.name for a in done)))

    # ---- the production buildings: caps, and the bank
    done = play(lambda g, cx, cy: (more_bases(g, 3), count_barracks(g, 5)), minerals=800)
    check("caps: four bases, five Barracks -> the sixth is built", A.TERRANBUILD_BARRACKS in done, str(sorted(a.name for a in done)))
    done = play(lambda g, cx, cy: (more_bases(g, 3), count_barracks(g, 7)), minerals=2500, supply=(180, 200))
    check("caps: seven Barracks and a big bank -> the eighth is still allowed", A.TERRANBUILD_BARRACKS in done, str(sorted(a.name for a in done)))
    done = play(lambda g, cx, cy: (more_bases(g, 3), count_barracks(g, 8)), minerals=2500, supply=(180, 200))
    check("caps: ...but eight Barracks is the limit, whatever the bank", A.TERRANBUILD_BARRACKS not in done, str(sorted(a.name for a in done)))
    done = play(lambda g, cx, cy: count_barracks(g, 1), minerals=500, supply=(140, 200))
    check("bank: minerals 500 - nothing piling up yet, one base keeps its one Barracks", A.TERRANBUILD_BARRACKS not in done, str(sorted(a.name for a in done)))
    done = play(lambda g, cx, cy: count_barracks(g, 1), minerals=1500, supply=(140, 200))
    check("bank: minerals 1500 late in the game -> one more Barracks", A.TERRANBUILD_BARRACKS in done, str(sorted(a.name for a in done)))
    done = play(lambda g, cx, cy: count_barracks(g, 1), minerals=1500, supply=(60, 200))
    check("bank: ... but not early in the game", A.TERRANBUILD_BARRACKS not in done, str(sorted(a.name for a in done)))
    done = play(lambda g, cx, cy: count_barracks(g, 8), minerals=1500, supply=(140, 200))
    check("bank: ... and never a ninth", A.TERRANBUILD_BARRACKS not in done, str(sorted(a.name for a in done)))

    def gas_bank(game, cx, cy):
        count_barracks(game, 6)
        game.add(U.FACTORY, (cx + 14, cy - 6), 1)                                  # one Factory, no Starport
    done = play(gas_bank, minerals=1500, gas=500, supply=(140, 200))
    check("bank: minerals and gas both piling up -> a second Factory and the first Starport", A.TERRANBUILD_FACTORY in done and A.TERRANBUILD_STARPORT in done, str(sorted(a.name for a in done)))
    done = play(gas_bank, minerals=1500, gas=100, supply=(140, 200))
    check("bank: minerals only -> no gas buildings", A.TERRANBUILD_FACTORY not in done and A.TERRANBUILD_STARPORT not in done, str(sorted(a.name for a in done)))

    def full_house(game, cx, cy):
        count_barracks(game, 8)
        for k in range(2):
            game.add(U.FACTORY, (cx + 14 + 4 * k, cy - 6), 1)
            game.add(U.STARPORT, (cx + 14 + 4 * k, cy + 4), 1)
    done = play(full_house, minerals=3000, gas=1000, supply=(140, 200))
    check("caps: 8 Barracks, 2 Factories and 2 Starports - nothing more is built, whatever the bank",
          not ({A.TERRANBUILD_BARRACKS, A.TERRANBUILD_FACTORY, A.TERRANBUILD_STARPORT} & done), str(sorted(a.name for a in done)))

    mech()
    upgrades()
    infantry_upgrades()
    one_base_all_in()
    mineral_banking()
    bunkers()
    placement()

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
