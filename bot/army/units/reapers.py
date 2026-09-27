"""Reapers: the early scout/harasser. Grenades (Ares' predictive ReaperGrenade), fights on the climber grid (they can
jump cliffs), retreats when hurt, and while there is nothing else to do it hunts for the enemy base.

A reaper never shoots buildings - they are a waste of its time, and of its life. It is never attack-moved (that shoots whatever stands in
range, buildings included) and never left standing near them (an idle unit shoots them too): with no enemy unit in sight it TOURS the
enemy's mineral lines - where the workers are - going on to the next stop the moment it gets close to one.

While it is not actively fighting anything it can see, the way there routes around spots it knows - or very recently knew - to be
defended (`units/danger_memory.py`), not just the destination itself: a defender that steps out of sight for a while does not make the
ramp it stands on safe to walk back up.

A thrown KD8 Charge does not go off at once: for a short while after, the reaper holds where it is (fighting on if something is already
in range - that needs no closer approach) instead of closing in on the very thing the charge was aimed at."""
import itertools
from typing import Dict, List, Optional, Set, Tuple

from cython_extensions import cy_attack_ready, cy_closest_to, cy_in_attack_range, cy_pick_enemy_target

from ares.behaviors.combat.individual import ReaperGrenade
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.army.consts import ATTACK_TARGET_IGNORE
from bot.army.context import ArmyContext
from bot.army.orders import GroupOrders
from bot.army.positioning import TOWNHALL_TYPES
from bot.army.units.common import (
    attack_unit,
    futile_to_kite,
    kite_away,
    kite_from_banelings,
    path_move,
    run,
)
from bot.army.units.danger_memory import DangerMemory, ground_defenders

RETREAT_BELOW_HEALTH = 0.5   # pull back to heal below this - reapers regenerate quickly once out of combat
RESUME_ABOVE_HEALTH = 0.85
HIDDEN_BASE_SCOUT_INTERVAL = 30.0   # move on to the next candidate expansion this often while hunting for the enemy
MINERAL_LINE_RADIUS = 10.0   # minerals this close to an enemy townhall are its mineral line
TOUR_ARRIVED = 3.5           # a reaper this close to a stop of its tour goes on to the next one (a mineral field itself cannot be walked to)
TOUR_REFRESH = 3.0           # seconds the list of stops is kept
TOUR_LANE = 2.0              # a stop is the mineral field's end of the mineral line, this far towards the townhall: the lane the workers walk
GRENADE_HOLD_SECONDS = 2.0   # a thrown KD8 Charge arms and can go off around this long after (Ares' own PlacePredictiveAoE leads the
                             # target by 34 game loops, ~1.5s, when it places one ahead of it; a margin on top for the reaper's own
                             # reaction time) - approximate, not measured against a real game


class ReaperHarass:
    def __init__(self, ai):
        self.ai = ai
        self.retreating: Set[int] = set()
        # cycles through expansion locations looking for the enemy's actual base, used only when the early
        # worker-scout (bot/scouting.py) never confirmed it
        self._hunt_index: int = 0
        self._hunt_since: float = 0.0
        self._stop: Dict[int, int] = {}                        # reaper tag -> the stop of the tour it is on
        self._tour_cache: Tuple[float, List[Point2]] = (-1e9, [])
        self.danger = DangerMemory(ai)      # ramps and mineral lines it has seen defended recently, even once out of sight
        self._grenade_until: Dict[int, float] = {}   # reaper tag -> until when a KD8 Charge it just threw may still be armed

    def control(self, units: Units, orders: GroupOrders, ctx: ArmyContext) -> None:
        alive = {u.tag for u in units}
        self.retreating &= alive
        self._stop = {tag: stop for tag, stop in self._stop.items() if tag in alive}
        self._grenade_until = {tag: until for tag, until in self._grenade_until.items() if tag in alive}
        ctx.prefetch_near(units)
        self.danger.refresh(ground_defenders(self.ai))
        grid = ctx.climber_grid
        for unit in units:
            self._control_unit(unit, orders, ctx, grid)

    # ------------------------------------------------------------------------------------------------------------
    def _control_unit(self, unit: Unit, orders: GroupOrders, ctx: ArmyContext, grid) -> None:
        health = unit.health_percentage
        if unit.tag in self.retreating:
            if health >= RESUME_ABOVE_HEALTH:
                self.retreating.discard(unit.tag)
        elif health < RETREAT_BELOW_HEALTH:
            self.retreating.add(unit.tag)
        if unit.tag in self.retreating:
            path_move(self.ai, ctx, unit, orders.hold_point, grid=grid)
            return

        # a Reaper only hits ground, and never wastes a shot on a building
        targets = [t for t in ctx.targets_near(unit) if not t.is_structure]

        if targets and run(self.ai, ReaperGrenade(unit=unit, enemy_units=targets, retreat_target=orders.hold_point,
                                                  grid=grid)):
            self._grenade_until[unit.tag] = self.ai.time + GRENADE_HOLD_SECONDS
            return

        # banelings: always back away, whatever else is true (see kite_from_banelings)
        banelings = ctx.banelings_near(unit)
        close_banelings = ctx.close_banelings(unit)

        # a grenade it just threw is still armed, and it can go off near what it was aimed at (the same nearest enemy ReaperGrenade
        # itself picks): do not close the distance to it meanwhile. A shot already in range needs no closer approach, and is worth
        # taking; anything else waits for the fuse instead of walking into it.
        if targets and self._grenade_until.get(unit.tag, 0.0) > self.ai.time:
            if close_banelings:
                kite_from_banelings(self.ai, ctx, unit, close_banelings, orders, grid=grid)
                return
            in_range = cy_in_attack_range(unit, targets)
            if in_range:
                held_target = cy_pick_enemy_target(in_range)
                if cy_attack_ready(self.ai, unit, held_target):
                    attack_unit(unit, held_target)
                    return
            kite_away(self.ai, ctx, unit, grid)
            return

        target: Optional[Unit] = None
        if targets:
            in_range = cy_in_attack_range(unit, targets)
            target = cy_pick_enemy_target(in_range) if in_range else cy_closest_to(unit.position, targets)
            if cy_attack_ready(self.ai, unit, target):
                attack_unit(unit, target)
                return

        if close_banelings:
            kite_from_banelings(self.ai, ctx, unit, close_banelings, orders, grid=grid)
            return

        # in danger: run - unless what threatens us both outranges us AND is not slower (or is rooted), in which case
        # backing off between shots is futile and holding and trading is better (see futile_to_kite) - not with banelings
        if not (futile_to_kite(unit, target) and not banelings) and not ctx.is_safe(unit, grid):
            if kite_away(self.ai, ctx, unit, grid):
                return

        destination = self._destination(unit, ctx, grid)
        if target is not None and unit.distance_to(destination) <= 5:
            attack_unit(unit, target)        # (the unit it is after: an attack-move onto the spot would shoot the buildings around it)
        else:
            # a target still in weapon range would already have been taken above (cy_attack_ready) - by now there is nothing left to
            # fight nearby, so the route there avoids what was recently seen defended, not only what still is
            path_move(self.ai, ctx, unit, destination, grid=self.danger.avoiding_grid(grid), sense_danger=bool(targets))

    # ------------------------------------------------------------------------------------------------------------
    def _destination(self, unit: Unit, ctx: ArmyContext, grid) -> Point2:
        ai = self.ai
        enemies = [
            e for e in ai.enemy_units
            if not e.is_memory and not e.is_flying and not e.is_cloaked and not e.is_hallucination
            and e.type_id not in ATTACK_TARGET_IGNORE
        ]
        if enemies:
            return min(enemies, key=lambda e: e.distance_to(ai.start_location)).position
        # no enemy unit in sight: look for one where they are found (see _tour)
        stops = self._tour(ctx, grid)
        stop = self._stop.setdefault(unit.tag, len(self._stop)) % len(stops)      # (reapers start at different stops)
        if unit.distance_to(stops[stop]) <= TOUR_ARRIVED:
            stop = (stop + 1) % len(stops)
        self._stop[unit.tag] = stop
        return stops[stop]

    def _tour(self, ctx: ArmyContext, grid) -> List[Point2]:
        """Where a reaper with no unit to shoot goes to look for one: the two ends of the mineral line of every enemy base we know of,
        the nearest to us first - that is where the workers are, and a reaper that keeps walking along them sees and grenades them all. An
        end the enemy defends (a weapon that reaches it) is left out. With no base known: the nearest building we know of (a proxy), then
        wherever the enemy is most likely to be. Always at least two stops (a lone one gets a second, back towards home), so that there is
        always somewhere to go on to: a reaper that stops next to buildings shoots them."""
        ai = self.ai
        now = ai.time
        if now - self._tour_cache[0] < TOUR_REFRESH:
            return self._tour_cache[1]
        stops: List[Point2] = []
        bases = sorted(
            (s for s in ai.enemy_structures if s.type_id in TOWNHALL_TYPES and not s.is_flying), key=lambda s: s.distance_to(ai.start_location)
        )
        defenders = self._defenders() + self.danger.spots()
        for base in bases:
            stops.extend(stop for stop in self._mineral_line(base.position) if not self._defended(stop, defenders))
        if not stops:
            if ai.enemy_structures:
                stops.append(ai.enemy_structures.closest_to(ai.start_location).position)
            stops.append(self._search_point())
        if len(stops) == 1:
            stops.append(stops[0].towards(ai.start_location, 6.0))
        self._tour_cache = (now, stops)
        return stops

    def _defenders(self) -> List[Tuple[Point2, float]]:
        """What shoots ground units and is known to us right now (units and buildings, Ares' recent memory of them too): its position and
        how far it is a danger. `self.danger` remembers such a spot for longer still - see `_tour` and `_control_unit`."""
        return ground_defenders(self.ai)

    @staticmethod
    def _defended(stop: Point2, defenders: List[Tuple[Point2, float]]) -> bool:
        return any(stop.distance_to(position) <= reach for position, reach in defenders)

    def _mineral_line(self, base: Point2) -> List[Point2]:
        """The two ends of a base's mineral line (the two mineral fields farthest apart), moved into the lane the workers walk. Mined out:
        the townhall's own spot and one beside it."""
        minerals = [m.position for m in self.ai.mineral_field.closer_than(MINERAL_LINE_RADIUS, base)]
        if len(minerals) < 2:
            return [base, base.towards(self.ai.game_info.map_center, 7.0)]
        end_a, end_b = max(itertools.combinations(minerals, 2), key=lambda pair: pair[0].distance_to(pair[1]))
        return [end_a.towards(base, TOUR_LANE), end_b.towards(base, TOUR_LANE)]

    def _search_point(self) -> Point2:
        ai = self.ai
        if not ai.enemy_base_scouted:
            # the early worker-scout never confirmed the enemy's main (died en route, or they just aren't there) -
            # hunt expansions with our own vision instead of sitting at a possibly-empty default forever
            candidate = self._next_hunt_candidate()
            if candidate is not None:
                return candidate
        return ai.enemy_start_locations[0]

    def _next_hunt_candidate(self) -> Optional[Point2]:
        expansions = self.ai.expansion_locations_list
        if not expansions:
            return None
        if self.ai.time - self._hunt_since > HIDDEN_BASE_SCOUT_INTERVAL:
            self._hunt_since = self.ai.time
            self._hunt_index = (self._hunt_index + 1) % len(expansions)
        return expansions[self._hunt_index]

