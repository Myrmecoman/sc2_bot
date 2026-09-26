"""Add-ons (Reactors and Tech Labs) for the Barracks, Factories and Starports: every production building gets the one it is meant to have.

What used to leave a building bare, and what is done about it now:
  - No room for the add-on where the building stands (terrain, another building). The building lifts off - against any race, not only
    Terran and only for the wall Barracks; not while a rush is on - and lands where it and its add-on fit, asked of the game itself and not
    only of the grids. It used to stay bare for the rest of the game, and to keep the other buildings of its kind waiting behind it.
  - The game did not take the order (something the grids cannot show is in the way). Noticed after ORDER_PATIENCE, asked again, and after
    MAX_MISSES misses moved like the ones above. Nothing is ordered twice in a row any more.
  - A unit queued on a building in the step it got its add-on order (production.idle_producers leaves such a building alone).
  - A building that lifted and never lands: the spots that did not work are remembered and the next is tried, the distance between the
    columns of buildings is relaxed once, and the grids' best guess is used when the game turns every spot down.
  - Which add-on: counted on the buildings themselves (an add-on under construction and a lost building's add-on used to be counted
    twice / for ever).
Every ready building that stays bare for NAKED_WARNING seconds is logged, with the reason.
New buildings are placed where their add-on fits too (macro.smart_build)."""
import math
from collections import Counter
from typing import Dict, List, Optional, Set, Tuple

from loguru import logger

from sc2.data import Race
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

ADDON_OFFSET = Point2((2.5, -0.5))       # where an add-on stands, seen from the middle of its building
ORDER_PATIENCE = 3.0                     # an order that has not shown by then (the add-on stands, the building is busy) was not taken
MAX_MISSES = 3                           # ...asked again this many times, then the building moves
MAX_LIFTS = 3                            # a building that has been moved this often is left alone
LANDING_PATIENCE = 8.0                   # idle in the air this long after the order to land: it did not land there
LANDING_GAPS = (7.0, 5.5)                # the columns of buildings (3 wide, 2 more for the add-on) stand this far apart; relaxed once
LANDING_BATCH = 12                       # spots asked of the game at once
LANDING_BATCHES = 3                      # ...this many times over
NAKED_WARNING = 60.0                     # a building bare for this long is logged

# building, the same in the air, the add-ons it gets
PRODUCTION = (
    (UnitTypeId.BARRACKS, UnitTypeId.BARRACKSFLYING, UnitTypeId.BARRACKSREACTOR, UnitTypeId.BARRACKSTECHLAB),
    (UnitTypeId.FACTORY, UnitTypeId.FACTORYFLYING, UnitTypeId.FACTORYREACTOR, UnitTypeId.FACTORYTECHLAB),
    (UnitTypeId.STARPORT, UnitTypeId.STARPORTFLYING, UnitTypeId.STARPORTREACTOR, UnitTypeId.STARPORTTECHLAB),
)
BUILDINGS = {building for building, _, _, _ in PRODUCTION}
GROUND_OF = {flying: building for building, flying, _, _ in PRODUCTION}
FLYING = set(GROUND_OF)
KINDS = {building: (reactor, techlab) for building, _, reactor, techlab in PRODUCTION}
FLYING_OF = {building: flying for building, flying, _, _ in PRODUCTION}

# where a building in the air looks for somewhere to land: nearest first, up to 22 to the side and 7 up or down
LANDING_OFFSETS = sorted((Point2((x, y)) for x in range(-22, 22) for y in range(-7, 7)), key=lambda point: point.x ** 2 + point.y ** 2)


def points_to_build_addon(position: Point2) -> List[Point2]:
    """The four cells the add-on of a building standing at `position` covers."""
    addon_position: Point2 = position + ADDON_OFFSET
    return [(addon_position + Point2((x - 0.5, y - 0.5))).rounded for x in range(0, 2) for y in range(0, 2)]


def footprint_cells(position: Point2) -> List[Point2]:
    """The nine cells of a 3x3 building standing at `position`, and the four of its add-on."""
    return [(position + Point2((x, y))).rounded for x in range(-1, 2) for y in range(-1, 2)] + points_to_build_addon(position)


def cells_free(ai, cells: List[Point2]) -> bool:
    """Are all these cells on the map, buildable ground, and walkable now (the pathing grid is refreshed every step: our own buildings, the
    minerals and the enemy's buildings block it)?"""
    return all(ai.in_map_bounds(cell) and ai.in_placement_grid(cell) and ai.in_pathing_grid(cell) for cell in cells)


def has_room(ai, position: Point2) -> bool:
    return cells_free(ai, points_to_build_addon(position))


async def game_allows_addon(ai, position: Point2) -> bool:
    """The game's own answer whether an add-on fits next to a building at `position` (python-sc2's find_placement asks it the same way: a
    Supply Depot is as big as an add-on). It knows what the grids do not: a lowered depot, creep, ..."""
    return await ai.can_place_single(AbilityId.TERRANBUILD_SUPPLYDEPOT, position + ADDON_OFFSET)


class AddonManager:
    def __init__(self, ai):
        self.ai = ai
        self.just_ordered: Set[int] = set()              # buildings given an add-on (or a lift) order in this step: production leaves them alone
        self.ordered: Dict[int, float] = {}              # building tag -> when it was last given an order to get its add-on (or to lift)
        self.misses: Dict[int, int] = {}                 # building tag -> how often such an order was not taken
        self.lifts: Dict[int, int] = {}                  # building tag -> how often it has been lifted for lack of room
        self.landing: Dict[int, Tuple[Point2, float]] = {}   # building tag -> (where it was told to land, when)
        self.failed_landings: Dict[int, List[Point2]] = {}   # building tag -> the spots it was told to land on and did not
        self.naked_since: Dict[int, float] = {}          # building tag -> since when it has been ready and without an add-on
        self.reported: Set[int] = set()                  # ...and was logged for it
        self.why: Dict[int, str] = {}                    # building tag -> what keeps it from getting one
        self._added: Counter = Counter()                 # add-ons ordered in this step, by type

    # ------------------------------------------------------------------------------------------------------------
    async def update(self) -> None:
        """Once per step, before production."""
        ai = self.ai
        self.just_ordered = set()
        self._added = Counter()
        alive = {s.tag for s in ai.structures}
        for book in (self.ordered, self.misses, self.lifts, self.landing, self.failed_landings, self.naked_since, self.why):
            for tag in [t for t in book if t not in alive]:
                del book[tag]
        self.reported &= alive
        await self.land_flying()
        if len(ai.build_order) != 0:                     # the scripted opening first
            return
        for building in (UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT):
            for s in ai.structures(building).ready:
                if s.has_add_on:
                    self.settled(s.tag)
                    continue
                if self.landing.pop(s.tag, None) is not None and ai.rally_point is not None:
                    s(AbilityId.SMART, ai.rally_point)   # (it has landed: its units rally where the other buildings' do)
                self.watch(s)
                if s.is_idle:
                    await self.serve(s, building)

    def settled(self, tag: int) -> None:
        """The building has its add-on: what was kept about it is done with."""
        for book in (self.ordered, self.misses, self.lifts, self.landing, self.failed_landings, self.naked_since, self.why):
            book.pop(tag, None)
        self.reported.discard(tag)

    def watch(self, s: Unit) -> None:
        """Log a building that stays bare for long, with what keeps it from getting an add-on."""
        now = self.ai.time
        since = self.naked_since.setdefault(s.tag, now)
        if now - since > NAKED_WARNING and s.tag not in self.reported:
            self.reported.add(s.tag)
            logger.warning(f"[addons] {s.type_id.name} {s.tag} at ({s.position.x:.1f}, {s.position.y:.1f}) has had no add-on for "
                           f"{now - since:.0f}s: {self.why.get(s.tag, 'it is busy producing')}")

    # ------------------------------------------------------------------------------------------------------------
    async def serve(self, s: Unit, building: UnitTypeId) -> None:
        """A ready, idle building without an add-on: order it, or - when there is no room for it here - move the building."""
        ai = self.ai
        now = ai.time
        if s.tag in self.ordered:
            if now - self.ordered[s.tag] < ORDER_PATIENCE:
                return                                   # (a moment for the order to show)
            del self.ordered[s.tag]
            self.misses[s.tag] = self.misses.get(s.tag, 0) + 1    # still bare and idle: the game did not take it
        misses = self.misses.get(s.tag, 0)
        room = has_room(ai, s.position)
        if room and misses:
            room = misses < MAX_MISSES and await game_allows_addon(ai, s.position)       # it refused once: ask the game itself
        if room:
            self.order(s, building)
        else:
            self.lift(s, building)

    def choose(self, building: UnitTypeId) -> UnitTypeId:
        """The add-on the next bare building of this kind gets: Barracks a Reactor for the first half of them, Factories a Tech Lab for
        `factory_techlab_ratio` of them, Starports a Tech Lab first (build_starport_techlab_first), then the other kind."""
        ai = self.ai
        reactor, techlab = KINDS[building]
        ground = ai.structures(building)
        total = ground.amount + ai.structures(FLYING_OF[building]).amount
        reactors = sum(1 for s in ground if s.has_reactor) + self._added[reactor]
        techlabs = sum(1 for s in ground if s.has_techlab) + self._added[techlab]
        if building == UnitTypeId.BARRACKS:
            return reactor if reactors < total / 2 else techlab
        if building == UnitTypeId.FACTORY:
            return techlab if techlabs < total * ai.army_advisor.factory_techlab_ratio else reactor
        if ai.build_starport_techlab_first:
            return techlab if techlabs < total / 2 else reactor
        return reactor if reactors < total / 2 else techlab

    def order(self, s: Unit, building: UnitTypeId) -> None:
        ai = self.ai
        # no add-ons while a rush is on and the wall is open: the money and the building are for units
        if (ai.worker_rushed or ai.army_advisor.zergling_rushed) and not ai.army_advisor.is_wall_closed():
            self.why[s.tag] = "a rush is on and the wall is open"
            return
        add_on = self.choose(building)
        if not ai.can_afford(add_on):
            self.why[s.tag] = f"the {add_on.name} is not affordable yet"
            return
        s.build(add_on)
        self.ordered[s.tag] = ai.time
        self.just_ordered.add(s.tag)
        self._added[add_on] += 1
        self.why.pop(s.tag, None)

    def may_lift(self, s: Unit) -> bool:
        ai = self.ai
        if ai.enemy_race == Race.Terran:
            return True
        if ai.worker_rushed or ai.army_advisor.zergling_rushed:
            return False
        if s.position == ai.main_base_ramp.barracks_in_middle:     # the wall itself: only once the army can hold without it
            return ai.army_advisor.total_enemy_supply() < ai.supply_army
        return True

    def lift(self, s: Unit, building: UnitTypeId) -> None:
        ai = self.ai
        if self.lifts.get(s.tag, 0) >= MAX_LIFTS:
            self.why[s.tag] = "no room for an add-on here, and it has been moved often enough"
        elif not self.may_lift(s):
            self.why[s.tag] = "no room for an add-on here, and it must not lift now (rush, or the wall)"
        elif not ai.can_afford(self.choose(building)):
            self.why[s.tag] = "no room for an add-on here; it lifts once the add-on can be paid"
        else:
            s(AbilityId.LIFT)
            self.lifts[s.tag] = self.lifts.get(s.tag, 0) + 1
            self.misses.pop(s.tag, None)
            self.ordered[s.tag] = ai.time                # (asked again if it does not lift)
            self.just_ordered.add(s.tag)
            self.why[s.tag] = "lifted: no room for an add-on where it stood"

    # ------------------------------------------------------------------------------------------------------------
    async def land_flying(self) -> None:
        """Buildings in the air, idle: land them where they and their add-on fit."""
        ai = self.ai
        now = ai.time
        for s in ai.structures.of_type(FLYING):
            self.ordered.pop(s.tag, None)                # (it lifted: that order was taken)
        for s in ai.structures.of_type(FLYING).idle:
            record = self.landing.get(s.tag)
            if record is not None:
                if now - record[1] < LANDING_PATIENCE:
                    continue
                self.failed_landings.setdefault(s.tag, []).append(record[0])     # idle again long after: it did not land there
                del self.landing[s.tag]
            spot = await self.landing_spot(s)
            if spot is None:
                self.why[s.tag] = "in the air: nowhere to land with room for its add-on"
                continue
            s(AbilityId.LAND, spot)
            self.landing[s.tag] = (spot, now)

    async def landing_spot(self, s: Unit) -> Optional[Point2]:
        ai = self.ai
        ground = GROUND_OF[s.type_id]
        failed = self.failed_landings.get(s.tag, [])
        columns = [b.position.x for b in ai.structures.of_type(BUILDINGS)]
        origin = Point2((math.floor(s.position.x) + 0.5, math.floor(s.position.y) + 0.5))
        fallback: Optional[Point2] = None
        for gap in LANDING_GAPS:
            spots: List[Point2] = []
            for offset in LANDING_OFFSETS:
                spot = origin + offset
                if any(abs(x - spot.x) < gap for x in columns) or any(spot.distance_to(f) < 1.0 for f in failed):
                    continue
                if not cells_free(ai, footprint_cells(spot)):
                    continue
                spots.append(spot)
                if len(spots) == LANDING_BATCH * LANDING_BATCHES:
                    break
            if fallback is None and spots:
                fallback = spots[0]
            for i in range(0, len(spots), LANDING_BATCH):
                batch = spots[i:i + LANDING_BATCH]
                fits = await ai.can_place(ground, batch)
                batch = [spot for spot, fit in zip(batch, fits) if fit]
                if not batch:
                    continue
                room = await ai.can_place(AbilityId.TERRANBUILD_SUPPLYDEPOT, [spot + ADDON_OFFSET for spot in batch])
                for spot, fits_addon in zip(batch, room):
                    if fits_addon:
                        return spot
        return fallback                                  # the game turned every spot down: the grids' best guess
