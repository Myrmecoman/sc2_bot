"""Add-ons (Reactors and Tech Labs) in the whole bot on the real Ares hub: a production building that cannot get its add-on where it stands
is moved instead of staying bare, and new buildings are placed where the add-on fits (bot/addons.py, macro.find_production_spot).

  room       a Factory with room gets its Tech Lab at once - and no unit is queued on it in that same step
  no room    a Factory whose add-on spot is blocked lifts (against every race - it used to only against Terran), and does not keep the
             Factory that has room from getting its Tech Lab (the first bare building used to stop the loop)
  rush       ...but not while a rush is on (unless the enemy is Terran, as before); the Barracks of the wall only when the army can hold
  refused    an order the game did not take is noticed, asked again, and then the building is moved - or not, when the game says the
             spot is free after all
  landing    a building in the air lands where it and its add-on fit (asked of the game); a spot that did not work is not tried again;
             when the game turns every spot down it lands on the grids' best guess
  placement  a new production building goes where its add-on fits, if there is such a place; else where it fits
  add-on     which add-on: counted on the buildings (a Tech Lab under construction is not counted twice)
  rally      the army's rally point moves to a new base when it is placed, not when it is finished
  log        a building that stays bare is logged after a minute, with the reason"""
import _bootstrap  # noqa: F401  (repo root on sys.path - keep this first)
import asyncio
from loguru import logger
from s2clientprotocol import common_pb2
from sc2.ids.ability_id import AbilityId as A
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

import bot.addons as addons
import bot.production as production
import gamefix_more  # noqa: F401
from dynamic import BASES, run_frame, start_game
from test_dynamic import build_game
from bot.bot import SmoothBrainBot

RESULTS = []
Protoss, Zerg, Terran = common_pb2.Protoss, common_pb2.Zerg, common_pb2.Terran
CX, CY = BASES["our_main"]
FACTORY_AT = (CX + 14, CY + 2)                # (38.5, 26.5)
ADDON_FOR = lambda pos: (pos[0] + 2.5, pos[1] - 0.5)


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail and not cond else ""))


def block_addon_cells(game, pos):
    """the ground under the add-on of a building at pos is not buildable / walkable (cliff, another building...)"""
    x0, y0 = int(pos[0] + 1.5), int(pos[1] - 1.5)
    game.pathing[y0:y0 + 2, x0:x0 + 2] = 0
    game.placement[y0:y0 + 2, x0:x0 + 2] = 0


class Run:
    """A game with our main base, a Barracks with its Reactor (out of the way) and whatever `setup(game)` adds; frames are run one by one"""

    def __init__(self, setup, race=Protoss, minerals=600, gas=300, supply=(60, 200)):
        production.made_banshee = production.made_raven = False
        logger.remove()
        self.errors, self.warnings = [], []
        logger.add(lambda m: self.errors.append(str(m)) if m.record["level"].no >= 40 else None, colorize=False)
        logger.add(lambda m: self.warnings.append(str(m)) if 30 <= m.record["level"].no < 40 else None, colorize=False)
        self.game = build_game(race)
        barracks = next(u for u in self.game.units_raw if u.unit_type == U.BARRACKS.value)
        reactor = self.game.add(U.BARRACKSREACTOR, (barracks.pos.x + 2.5, barracks.pos.y - 0.5), 1)
        barracks.add_on_tag = reactor.tag
        self.things = setup(self.game) or {}
        self.game.minerals, self.game.vespene = minerals, gas
        self.supply = supply
        self.bot = SmoothBrainBot()
        self.loop = asyncio.new_event_loop()
        self.client, self.proto_gi = self.loop.run_until_complete(start_game(self.game, self.bot))
        self.bot.build_order = []                        # the scripted opening is not what is being tested
        self.i = 0
        self.placement = lambda ability, position: True   # the game's answer to "can this be placed here"

        async def query(ability, positions, *a, **k):
            return [bool(self.placement(ability, p)) for p in positions]
        self.client._query_building_placement_fast = query

    def frame(self, frames=2):
        """run one frame; the abilities ordered in it, as (ability, unit tag, target)"""
        start = len(self.client.sent_actions)
        self.loop.run_until_complete(run_frame(self.game, self.bot, self.proto_gi, self.i, frames=frames,
                                               supply_used=self.supply[0], supply_cap=self.supply[1]))
        self.i += 1
        return [(a.ability, a.unit.tag, a.target) for a in self.client.sent_actions[start:]]

    def frames(self, n, frames=2):
        out = []
        for _ in range(n):
            out.extend(self.frame(frames))
        return out


def of(orders, tag, *abilities):
    return [o for o in orders if o[1] == tag and (not abilities or o[0] in abilities)]


def factory(pos=FACTORY_AT, with_room=True):
    def setup(game):
        if not with_room:
            block_addon_cells(game, pos)
        f = game.add(U.FACTORY, pos, 1)
        return {"factory": f.tag}
    return setup


def test_room():
    run = Run(factory())
    orders = run.frame()
    tag = run.things["factory"]
    check("room: a bare Factory with room gets its Tech Lab (Protoss: every Factory a Tech Lab)", of(orders, tag, A.BUILD_TECHLAB_FACTORY), str(orders))
    check("room: ...and no unit is queued on it in that same step", not of(orders, tag, A.TRAIN_CYCLONE, A.FACTORYTRAIN_HELLION, A.FACTORYTRAIN_SIEGETANK), str(of(orders, tag)))
    check("room: ...and it is not lifted", not of(orders, tag, A.LIFT))
    orders = run.frame()
    check("room: the next step it is not ordered a second time (the order is given a moment to show)", not of(orders, tag, A.BUILD_TECHLAB_FACTORY), str(orders))
    check("room: no warning, no error", not run.errors, str(run.errors[:1]))
    run = Run(factory(), race=Zerg)
    orders = run.frame()
    check("room: (Zerg: half of the Factories a Tech Lab, the first one) the same", of(orders, run.things["factory"], A.BUILD_TECHLAB_FACTORY), str(orders))
    run = Run(factory(), minerals=20, gas=0)
    orders = run.frames(3)
    check("room: nothing to pay it with: nothing is ordered, and no unit either", not [o for o in of(orders, run.things["factory"]) if o[0] != A.SMART], str(of(orders, run.things["factory"])))


def test_no_room():
    for race, name in ((Protoss, "Protoss"), (Zerg, "Zerg"), (Terran, "Terran")):
        run = Run(factory(with_room=False), race=race)
        orders = run.frame()
        tag = run.things["factory"]
        check(f"no room ({name}): the Factory lifts to land where its add-on fits", of(orders, tag, A.LIFT), str(orders))
        check(f"no room ({name}): ...and is not ordered an add-on that cannot be built", not of(orders, tag, A.BUILD_TECHLAB_FACTORY, A.BUILD_REACTOR_FACTORY))

    # two Factories, the one without room first in the list: the other one still gets its Tech Lab (the loop used to stop at the first)
    def two(game):
        blocked = game.add(U.FACTORY, FACTORY_AT, 1)
        block_addon_cells(game, FACTORY_AT)
        free = game.add(U.FACTORY, (FACTORY_AT[0] + 8, FACTORY_AT[1]), 1)
        return {"blocked": blocked.tag, "free": free.tag}
    run = Run(two, race=Protoss)
    orders = run.frame()
    check("no room: the Factory without room lifts...", of(orders, run.things["blocked"], A.LIFT), str(orders))
    check("no room: ...and the one with room still gets its Tech Lab", of(orders, run.things["free"], A.BUILD_TECHLAB_FACTORY), str(orders))
    orders = run.frames(2)
    check("no room: (nothing is ordered twice)", len(of(orders, run.things["free"], A.BUILD_TECHLAB_FACTORY)) == 0 and len(of(orders, run.things["blocked"], A.LIFT)) == 0, str(orders))


def test_rush_and_wall():
    rich = dict(minerals=5000, gas=1000)                   # (the worker-rush defense spends a lot in every step: enough is left)
    run = Run(factory(with_room=False), race=Protoss, **rich)
    run.bot.worker_rushed = True
    orders = run.frames(3)
    tag = run.things["factory"]
    check("rush: against a worker rush a Factory without room stays where it is (units come first)", not of(orders, tag, A.LIFT), str(orders))
    run = Run(factory(with_room=False), race=Zerg, **rich)
    run.bot.army_advisor.zergling_rushed = True
    orders = run.frames(3)
    check("rush: ...and against a Zergling rush", not of(orders, run.things["factory"], A.LIFT), str(orders))
    run = Run(factory(with_room=False), race=Zerg, **rich)
    orders = run.frames(3)
    check("rush: (control) the same Factory without a rush lifts", of(orders, run.things["factory"], A.LIFT), str(orders))
    run = Run(factory(with_room=False), race=Terran, **rich)
    run.bot.army_advisor.zergling_rushed = True
    orders = run.frames(2)
    check("rush: (against Terran it lifts as before)", of(orders, run.things["factory"], A.LIFT), str(orders))
    run = Run(factory(), race=Protoss, **rich)
    run.bot.worker_rushed = True
    orders = run.frames(2)
    check("rush: a rush without the wall closed: no add-on either (money and building are for units)", not of(orders, run.things["factory"], A.BUILD_TECHLAB_FACTORY), str(orders))
    run = Run(factory(), race=Zerg, **rich)
    run.bot.army_advisor.zergling_rushed = True
    orders = run.frames(2)
    check("rush: ...nor against a Zergling rush", not of(orders, run.things["factory"], A.BUILD_TECHLAB_FACTORY), str(orders))

    # the Barracks of the wall: only when the army can hold without it
    def wall(game):
        return {}
    for army, expect in ((48, True), (0, False)):
        run = Run(wall, race=Protoss, supply=(12 + army, 200))
        wall_pos = run.bot.main_base_ramp.barracks_in_middle
        barracks = run.game.add(U.BARRACKS, (wall_pos.x, wall_pos.y), 1)
        real = addons.has_room
        addons.has_room = lambda ai, position: False if position == wall_pos else real(ai, position)
        try:
            orders = run.frames(2)
        finally:
            addons.has_room = real
        check(f"wall: the wall Barracks without room {'lifts when the army is bigger than what the enemy is known to have' if expect else 'stays (no army to hold without it)'}",
              bool(of(orders, barracks.tag, A.LIFT)) == expect, str(of(orders, barracks.tag)))


def test_refused():
    # the grids say there is room, the game does not: the first order is not taken (nothing appears), the game is asked, the building moves
    run = Run(factory(), race=Protoss)
    run.placement = lambda ability, position: not (ability == A.TERRANBUILD_SUPPLYDEPOT and abs(position.x - ADDON_FOR(FACTORY_AT)[0]) < 1.5 and abs(position.y - ADDON_FOR(FACTORY_AT)[1]) < 1.5)
    tag = run.things["factory"]
    first = run.frame()
    check("refused: the first order is given (the grids see nothing in the way)", of(first, tag, A.BUILD_TECHLAB_FACTORY), str(first))
    later = run.frame(frames=int(addons.ORDER_PATIENCE * 22.4) + 4)
    check("refused: it never showed: the game is asked and says no - the Factory lifts", of(later, tag, A.LIFT) and not of(later, tag, A.BUILD_TECHLAB_FACTORY), str(later))

    # the game says the spot is free: the order is given again (a unit in the way, a moment's delay), up to MAX_MISSES times, then the building moves
    run = Run(factory(), race=Protoss)
    tag = run.things["factory"]
    counts = []
    for k in range(addons.MAX_MISSES + 1):
        orders = run.frame(frames=int(addons.ORDER_PATIENCE * 22.4) + 4)
        counts.append((len(of(orders, tag, A.BUILD_TECHLAB_FACTORY)), len(of(orders, tag, A.LIFT))))
    check(f"refused: the game says the spot is free - the order is repeated {addons.MAX_MISSES - 1} more times, then the Factory lifts",
          counts == [(1, 0)] * addons.MAX_MISSES + [(0, 1)], str(counts))


def flying_factory(game, pos=(FACTORY_AT[0], FACTORY_AT[1] + 12)):
    f = game.add(U.FACTORYFLYING, pos, 1)
    return {"flyer": f.tag}


def test_landing():
    run = Run(flying_factory, race=Protoss)
    tag = run.things["flyer"]
    orders = run.frame()
    land = of(orders, tag, A.LAND)
    check("landing: a Factory in the air, idle: told to land", len(land) == 1, str(orders))
    first = land[0][2]
    check("landing: ...where the ground can take it and its add-on", addons.cells_free(run.bot, addons.footprint_cells(Point2(first))), str(first))
    check("landing: ...only once", not of(run.frame(), tag, A.LAND))

    # the game does not want it there: the next spot
    run = Run(flying_factory, race=Protoss)
    run.placement = lambda ability, position: not (ability == A.TERRANBUILD_FACTORY and position.distance_to(Point2(first)) < 0.5)
    second = of(run.frame(), run.things["flyer"], A.LAND)
    check("landing: a spot the game turns down for the building is not used", len(second) == 1 and Point2(second[0][2]).distance_to(Point2(first)) > 0.5, str(second))
    run = Run(flying_factory, race=Protoss)
    run.placement = lambda ability, position: not (ability == A.TERRANBUILD_SUPPLYDEPOT and position.distance_to(Point2(ADDON_FOR(first))) < 0.5)
    third = of(run.frame(), run.things["flyer"], A.LAND)
    check("landing: ...nor one where the game says the add-on does not fit", len(third) == 1 and Point2(third[0][2]).distance_to(Point2(first)) > 0.5, str(third))
    run = Run(flying_factory, race=Protoss)
    run.placement = lambda ability, position: False
    fourth = of(run.frame(), run.things["flyer"], A.LAND)
    check("landing: when the game turns every spot down it lands on the grids' best guess (it does not hover for ever)", len(fourth) == 1 and Point2(fourth[0][2]).distance_to(Point2(first)) < 1, str(fourth))

    # it is still in the air long after the order: the spot did not work
    run = Run(flying_factory, race=Protoss)
    tag = run.things["flyer"]
    a = of(run.frame(), tag, A.LAND)
    b = of(run.frame(frames=int(addons.LANDING_PATIENCE * 22.4) + 4), tag, A.LAND)
    check("landing: idle in the air long after the order: not the same spot again",
          len(a) == 1 and len(b) == 1 and Point2(a[0][2]).distance_to(Point2(b[0][2])) > 0.5, str((a, b)))

    # it lands: told to rally where the other production buildings do, and its add-on is ordered
    run = Run(flying_factory, race=Protoss)
    tag = run.things["flyer"]
    spot = of(run.frame(), tag, A.LAND)[0][2]
    proto = next(u for u in run.game.units_raw if u.tag == tag)
    proto.unit_type, proto.pos.x, proto.pos.y, proto.is_flying = U.FACTORY.value, spot.x, spot.y, False
    orders = run.frame()
    rally = of(orders, tag, A.SMART)
    check("landing: landed, it is told to rally where the other production buildings do", len(rally) == 1 and Point2(rally[0][2]).distance_to(run.bot.rally_point) < 0.1, str(orders))
    check("landing: ...and gets its add-on there", of(orders, tag, A.BUILD_TECHLAB_FACTORY), str(of(orders, tag)))

    # the columns of buildings stay 7 apart
    def beside(game):
        game.add(U.FACTORY, FACTORY_AT, 1)
        return flying_factory(game, pos=(FACTORY_AT[0] + 1, FACTORY_AT[1] + 4))
    run = Run(beside, race=Protoss)
    spot = of(run.frame(), run.things["flyer"], A.LAND)
    check("landing: not within 7 (sideways) of the buildings that stand", len(spot) == 1 and abs(spot[0][2].x - FACTORY_AT[0]) >= 7, str(spot))


def test_placement():
    from bot.macro import smart_build
    Run_ = Run

    def build_spot(run):
        run.client.sent_actions.clear()
        run.loop.run_until_complete(smart_build(run.bot, U.FACTORY))
        run.loop.run_until_complete(run.bot._do_actions(run.bot.actions))         # (what a step does at its end)
        run.bot.actions.clear()
        built = [a for a in run.client.sent_actions if a.ability == A.TERRANBUILD_FACTORY]
        return built[0].target if built else None

    def frame_one(run):
        run.frame()                                      # (units and money seen)
        run.client.sent_actions.clear()

    run = Run_(lambda game: {}, race=Protoss)
    frame_one(run)
    barracks = next(u for u in run.game.units_raw if u.unit_type == U.BARRACKS.value)
    first = build_spot(run)
    check("placement: a new Factory goes in line with the Barracks", first is not None and abs(first.x - barracks.pos.x) < 0.1 and abs(abs(first.y - barracks.pos.y) - 3) < 0.1, str(first))
    # no room for its add-on there (the game says no for the depot-sized add-on): the next place with room
    run = Run_(lambda game: {}, race=Protoss)
    frame_one(run)
    run.placement = lambda ability, position: not (ability == A.TERRANBUILD_SUPPLYDEPOT and position.distance_to(Point2(ADDON_FOR((first.x, first.y)))) < 0.5)
    second = build_spot(run)
    check("placement: a place whose add-on has no room is passed over for the next one", second is not None and Point2(second).distance_to(first) > 1, str((first, second)))
    check("placement: ...and that one is a place in line as well", second is not None and (abs(second.x - barracks.pos.x) < 0.1 or abs(abs(second.x - barracks.pos.x) - 7) < 0.1 or abs(abs(second.x - barracks.pos.x) - 14) < 0.1), str(second))
    # no room for an add-on anywhere: it is built where it fits (it lifts and lands later)
    run = Run_(lambda game: {}, race=Protoss)
    frame_one(run)
    run.placement = lambda ability, position: ability != A.TERRANBUILD_SUPPLYDEPOT
    third = build_spot(run)
    check("placement: no place has room for an add-on: it is built where the first place is (it would lift and land later)", third is not None and Point2(third).distance_to(first) < 0.1, str((first, third)))
    # nowhere at all
    run = Run_(lambda game: {}, race=Protoss)
    frame_one(run)
    run.placement = lambda ability, position: False
    check("placement: no place at all: nothing is built", build_spot(run) is None)
    # the game is asked twice, not once for every place
    run = Run_(lambda game: {}, race=Protoss)
    frame_one(run)
    calls = []
    original = run.client._query_building_placement_fast

    async def counting(ability, positions, *a, **k):
        calls.append(ability)
        return await original(ability, positions, *a, **k)
    run.client._query_building_placement_fast = counting
    build_spot(run)
    check("placement: the game is asked about all the places at once (2 questions, then the placement itself)", len(calls) <= 4, str(calls))


def test_choice_of_add_on():
    def two(game):
        a = game.add(U.FACTORY, FACTORY_AT, 1)
        techlab = game.add(U.FACTORYTECHLAB, ADDON_FOR(FACTORY_AT), 1, build_progress=0.4)      # under construction
        a.add_on_tag = techlab.tag
        a.orders.add().ability_id = A.BUILD_TECHLAB_FACTORY.value
        b = game.add(U.FACTORY, (FACTORY_AT[0] + 8, FACTORY_AT[1]), 1)
        return {"b": b.tag}
    run = Run(two, race=Protoss)
    orders = run.frame()
    check("add-on: a Tech Lab under construction on the first Factory is not counted twice: the second Factory (Protoss: a Tech Lab each) gets its Tech Lab too",
          of(orders, run.things["b"], A.BUILD_TECHLAB_FACTORY) and not of(orders, run.things["b"], A.BUILD_REACTOR_FACTORY), str(orders))

    def orphan(game):                                   # a Tech Lab that lost its Factory does not count as one we have
        game.add(U.FACTORYTECHLAB, (FACTORY_AT[0] + 20, FACTORY_AT[1]), 1)
        return factory()(game)
    run = Run(orphan, race=Zerg)
    orders = run.frame()
    check("add-on: (Zerg: half of them a Tech Lab) a Tech Lab standing alone is not one we have: the Factory gets a Tech Lab",
          of(orders, run.things["factory"], A.BUILD_TECHLAB_FACTORY), str(orders))

    def sp(game):
        s = game.add(U.STARPORT, (FACTORY_AT[0], FACTORY_AT[1] + 6), 1)
        return {"starport": s.tag}
    run = Run(sp, race=Zerg)
    orders = run.frame()
    check("add-on: the Starport gets its Tech Lab first", of(orders, run.things["starport"], A.BUILD_TECHLAB_STARPORT), str(orders))


def test_rally_at_placement():
    from bot.custom_utils import get_rally_point
    run = Run(lambda game: {}, race=Zerg)
    main = run.bot.townhalls.closest_to(run.bot.start_location)
    asyncio.run(run.bot.on_building_construction_complete(main))         # (the starting base: it appears finished, this is the only event it gets;
    asyncio.run(run.bot.on_building_construction_complete(main))         # the real game sends it at the first step, this harness does not)
    check("rally: the starting base is registered by its completion event, once", run.bot.base_build_order == [main.tag], str(run.bot.base_build_order))
    run.frames(2)
    main_point = get_rally_point(run.bot)
    natural = BASES["our_nat"]
    run.game.add(U.COMMANDCENTER, natural, 1, build_progress=0.05)         # just placed: the SCV has only begun
    run.frames(2)
    towards = run.bot.enemy_start_locations[0] - Point2(natural)
    expected = Point2(natural) + towards.normalized * 10
    rally = get_rally_point(run.bot)
    new_base = run.bot.townhalls.closest_to(Point2(natural))
    check("rally: a new Command Center that was just placed is our newest base: the rally point is its defend point (not the main's)",
          rally.distance_to(expected) < 0.5 and rally.distance_to(main_point) > 3, f"{rally} vs {expected} / main {main_point}")
    check("rally: ...it is in the list of our bases after the main, once", run.bot.base_build_order == [main.tag, new_base.tag], str(run.bot.base_build_order))
    for u in run.game.units_raw:
        if u.unit_type == U.COMMANDCENTER.value and abs(u.pos.x - natural[0]) < 0.1:
            u.build_progress = 1.0
    run.frames(2)
    check("rally: (finished) still once in the list, still the rally point", run.bot.base_build_order == [main.tag, new_base.tag]
          and get_rally_point(run.bot).distance_to(expected) < 0.5, str(run.bot.base_build_order))
    # the production buildings that stand ready are told to rally there
    smart = [(a.unit.tag, a.target) for a in run.client.sent_actions if a.ability == A.SMART and a.target is not None and Point2(a.target).distance_to(expected) < 0.5]
    check("rally: the ready production buildings were told to rally to the new base as soon as it was placed", len(smart) >= 1, str(smart[:2]))
    # a new base that is lost while it builds: back to the one before
    run.game.units_raw[:] = [u for u in run.game.units_raw if not (u.unit_type == U.COMMANDCENTER.value and abs(u.pos.x - natural[0]) < 0.1)]
    run.frames(2)
    check("rally: (the new base destroyed) the rally point goes back to the main's", get_rally_point(run.bot).distance_to(main_point) < 0.5, str(get_rally_point(run.bot)))


def test_rally_uses_the_bases_own_ramp_when_it_has_one():
    """A natural/third close enough to a real ramp of its own (this map has one at (65, 63.5) - see the probe referenced in
    project_sc2_bot_bio_ramp_rally.md) defends there instead of a blind "10 cells towards the enemy" guess, which has no idea whether
    that spot is even on the same plateau as the base - the same class of bug as bio's forward nudge landing it below the main's ramp
    (Positioning.bio_position), just for the rally point of a base that is not the main."""
    from bot.custom_utils import get_rally_point
    run = Run(lambda game: {}, race=Zerg)
    main = run.bot.townhalls.closest_to(run.bot.start_location)
    asyncio.run(run.bot.on_building_construction_complete(main))
    run.frames(2)
    near_ramp = (70.0, 63.5)                                            # 5 from the ramp's top_center (65.0, 63.5)
    run.game.add(U.COMMANDCENTER, near_ramp, 1, build_progress=0.05)    # just placed, like the natural in test_rally_at_placement
    run.frames(2)
    rally = get_rally_point(run.bot)
    check("rally: a base close enough to a real ramp defends there instead of a blind directional point",
          rally.distance_to(Point2((65.0, 63.5))) < 1.0, str(rally))


def test_warning_for_a_bare_building():
    run = Run(factory(with_room=False), race=Zerg)
    run.bot.army_advisor.zergling_rushed = True         # (no room, and it must not lift: it stays bare)
    run.frames(3)
    check("log: not yet a warning at the start", not run.warnings, str(run.warnings[:1]))
    run.frame(frames=int((addons.NAKED_WARNING + 5) * 22.4))
    run.frame()
    ours = [w for w in run.warnings if "[addons]" in w]
    check("log: a Factory that has stayed bare for a minute is logged, with the reason", len(ours) == 1 and "no room" in ours[0] and "FACTORY" in ours[0], str(ours))
    run.frame()
    check("log: ...once", len([w for w in run.warnings if "[addons]" in w]) == 1)


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    for test in tests:
        print("---", test.__name__)
        try:
            test()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            RESULTS.append((test.__name__, False, repr(e)))
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    raise SystemExit(1 if failed else 0)
