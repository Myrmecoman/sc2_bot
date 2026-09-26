"""The reactions to what we scouted, in the whole bot on the real Ares hub (what production and macro actually order), and the production
building limits: never more than 6 Barracks, 2 Factories and 2 Starports - and more of them (up to that) when the bank piles up late.

  raven      a Dark Shrine scouted: the Starport makes a Raven first (not a Banshee)
  tank       a Roach Warren scouted: Marines are skipped while the Factory that stands ready lacks the money for a Siege Tank
  turrets    a Dark Shrine scouted: an Engineering Bay, then a missile turret in the mineral line
  starport   ... and the Starport is built now, not once a second base is up
  caps       6 Barracks / 2 Factories / 2 Starports at most, the bank builds one more at a time while it piles up"""
import _bootstrap  # noqa: F401  (repo root on sys.path - keep this first)
import asyncio
from loguru import logger
from s2clientprotocol import common_pb2
from sc2.ids.ability_id import AbilityId as A
from sc2.ids.unit_typeid import UnitTypeId as U

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


def play(setup, race=common_pb2.Zerg, minerals=500, gas=200, supply=(60, 200), frames=4):
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
        loop.run_until_complete(run_frame(game, bot, proto_gi, i, supply_used=supply[0], supply_cap=supply[1]))
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
    done = play(lambda g, cx, cy: (more_bases(g, 3), count_barracks(g, 6)), minerals=2500, supply=(180, 200))
    check("caps: six Barracks is the limit, whatever the bank", A.TERRANBUILD_BARRACKS not in done, str(sorted(a.name for a in done)))
    done = play(lambda g, cx, cy: count_barracks(g, 1), minerals=500, supply=(140, 200))
    check("bank: minerals 500 - nothing piling up yet, one base keeps its one Barracks", A.TERRANBUILD_BARRACKS not in done, str(sorted(a.name for a in done)))
    done = play(lambda g, cx, cy: count_barracks(g, 1), minerals=1500, supply=(140, 200))
    check("bank: minerals 1500 late in the game -> one more Barracks", A.TERRANBUILD_BARRACKS in done, str(sorted(a.name for a in done)))
    done = play(lambda g, cx, cy: count_barracks(g, 1), minerals=1500, supply=(60, 200))
    check("bank: ... but not early in the game", A.TERRANBUILD_BARRACKS not in done, str(sorted(a.name for a in done)))
    done = play(lambda g, cx, cy: count_barracks(g, 6), minerals=1500, supply=(140, 200))
    check("bank: ... and never a seventh", A.TERRANBUILD_BARRACKS not in done, str(sorted(a.name for a in done)))

    def gas_bank(game, cx, cy):
        count_barracks(game, 6)
        game.add(U.FACTORY, (cx + 14, cy - 6), 1)                                  # one Factory, no Starport
    done = play(gas_bank, minerals=1500, gas=500, supply=(140, 200))
    check("bank: minerals and gas both piling up -> a second Factory and the first Starport", A.TERRANBUILD_FACTORY in done and A.TERRANBUILD_STARPORT in done, str(sorted(a.name for a in done)))
    done = play(gas_bank, minerals=1500, gas=100, supply=(140, 200))
    check("bank: minerals only -> no gas buildings", A.TERRANBUILD_FACTORY not in done and A.TERRANBUILD_STARPORT not in done, str(sorted(a.name for a in done)))

    def full_house(game, cx, cy):
        count_barracks(game, 6)
        for k in range(2):
            game.add(U.FACTORY, (cx + 14 + 4 * k, cy - 6), 1)
            game.add(U.STARPORT, (cx + 14 + 4 * k, cy + 4), 1)
    done = play(full_house, minerals=3000, gas=1000, supply=(140, 200))
    check("caps: 6 Barracks, 2 Factories and 2 Starports - nothing more is built, whatever the bank",
          not ({A.TERRANBUILD_BARRACKS, A.TERRANBUILD_FACTORY, A.TERRANBUILD_STARPORT} & done), str(sorted(a.name for a in done)))

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
