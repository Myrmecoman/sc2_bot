"""Cyclone raids: against Protoss the Cyclones do not wait for the army - they go and hurt the enemy: lock on, step back out of reach, and again.

A Lock On is cast from 7 and keeps working up to 15 (cyclones.py), so a Cyclone that casts and walks away has done its damage for nothing:
nothing a Protoss has reaches 15. The raid is the rhythm around that:

* Lock On available: it picks the best target in sight and goes and casts - units first (they are what the army has to fight), then Shield
  Batteries (they keep everything else alive), then Photon Cannons (they stop the army from walking in), and workers only when there is nothing
  else. Only a target that can be reached safely: nothing else that can hit the Cyclone may cover the spot the cast is made from or the way to
  it (the target itself is at the edge of its range, or beyond it, when the cast goes off). A unit in the middle of a Stalker ball is not
  "almost free damage" - a lone one, or a Cannon or Battery, is.
* Lock On not available: no attack at all. It stays out of reach of everything that can hit it, and waits for the cooldown - and out of its own
  weapon range of everything else: an idle Cyclone shoots whatever is within reach (workers, buildings), and only a move order stops that.
* A lock that is running: the usual lock kiting (cyclones.py) - out of the fire, but not out of the lock's range.
* Nothing in sight to hit: it walks towards what is known of the enemy (a Cannon or Battery, an army, a Nexus), stopping outside the reach of
  whatever it sees on the way. One that is too damaged goes home to be repaired (cyclones.py, RepairRetreat).

Reach is worked out from the enemies' weapons (range, both radii, a margin), not from Ares' danger grid: the grid marks a disk of 4 more around
everything, and around every worker as well, which would make every mineral line "dangerous" and every cast position too.

Searching for something to hit also avoids spots it knows - or very recently knew - to be defended (`units/danger_memory.py`), even once
they are out of sight: without this, backing off from a ramp's defenders for a moment and finding it empty on the next look would send it
straight back up the same ramp. The same memory also covers standing IN one: a ghost only counts as a live threat (`covering`, below) for
FIGHT_GHOST_MAX_AGE (12s) - short, tuned for the whole army's fight decisions - while `danger.spots()` holds a spot for up to 45s on its
own. Without also checking it here, a Cyclone that took a hit, backed off only partway, and then found itself waiting out Lock On's
cooldown (or standing right where a fresh cast would want to be) would just sit there once the ghost aged out - not searching (there is
nothing new to search for), not stepping back (`covering` is now empty), doing nothing at the foot of the exact ramp it was shot from."""
import math
from types import SimpleNamespace
from typing import Dict, List, Optional, Tuple

import numpy as np

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.army.consts import ATTACK_TARGET_IGNORE, ATTACK_TARGET_IGNORE_WITH_WORKERS, ENEMY_WORKER_TYPES, FIGHT_GHOST_MAX_AGE, MELEE_RANGE_THRESHOLD
from bot.army.context import ArmyContext
from bot.army.orders import GroupOrders
from bot.army.units.common import move_to, path_move, step_back_from
from bot.army.units.cyclones import LOCK_ON_ABILITIES, CycloneController
from bot.army.units.danger_memory import DangerMemory, ground_defenders

RAID_SIGHT = 28.0             # enemies this close are looked at, for targets and for what can hit the Cyclone
RAID_ENGAGE_RANGE = 20.0      # a target is gone for when it is at most this far (edge to edge); what is farther is what the search heads for
RAID_MARGIN = 1.5             # the Cyclone keeps this far outside the reach of whatever can hit it...
RAID_MELEE_EXTRA = 2.0        # ...and this much farther from what has to be right on it to hit (it closes in while the Cyclone casts)
RAID_CAST_SLACK = 0.6         # a cast is made this far inside the cast range: the target moves too
RAID_IDLE_MARGIN = 0.5        # a Cyclone that waits keeps this far outside its own weapon range of everything it could shoot
MEMORY_SECONDS = 30.0         # an enemy army seen this recently is still where the search heads for
# what a Lock On is worth casting on, best first: units are rank 0, workers WORKER_RANK, everything else is left alone
RAID_STRUCTURES = {U.SHIELDBATTERY: 1, U.PHOTONCANNON: 2}
WORKER_RANK = 3
# things that are not worth a lock (and cannot hurt the Cyclone either)
RAID_IGNORE = frozenset({U.INTERCEPTOR, U.ADEPTPHASESHIFT, U.DISRUPTORPHASED})


class CycloneRaid:
    def __init__(self, ai, cyclones: CycloneController):
        self.ai = ai
        self.cyclones = cyclones            # the Lock On state (who has locked on to whom) is shared with the Cyclones of the army
        self._memo: Dict[int, Tuple[Unit, Optional[int], float]] = {}   # enemy -> (enemy, its rank, its reach), worked out once per step
        self.danger = DangerMemory(ai)       # ramps and approaches it has seen defended recently, even once out of sight

    def control(self, units: Units, orders: GroupOrders, ctx: ArmyContext) -> None:
        self._memo = {}
        self.cyclones.begin_step(units, ctx)
        self.danger.refresh(ground_defenders(self.ai))
        for unit in units:
            self._control_unit(unit, orders, ctx)

    # ------------------------------------------------------------------------------------------------------------
    def _control_unit(self, unit: Unit, orders: GroupOrders, ctx: ArmyContext) -> None:
        if self.cyclones.handle_running_lock(unit, orders, ctx):
            return

        if self.cyclones.repair_trip(unit, orders, ctx):          # (a hurt raider goes home to be repaired, like any Cyclone)
            return

        pool: List[Unit] = list(ctx.enemies_within(unit, RAID_SIGHT))
        ranks: List[Optional[int]] = []
        threats: List[Unit] = []                # what can hit the Cyclone...
        for enemy in pool:
            rank, enemy_reach = self._info(enemy, unit)
            ranks.append(rank)
            if enemy_reach > 0:
                threats.append(enemy)
        xy = np.array([e.position_tuple for e in threats], dtype=float).reshape(-1, 2)      # ...where it stands, how far from there the Cyclone is inside
        reach = np.array([self._info(e, unit)[1] for e in threats], dtype=float)           # its reach, and who it is
        tags = np.array([e.tag for e in threats], dtype=np.int64)
        covering = [threats[k] for k in np.nonzero(np.hypot(xy[:, 0] - unit.position.x, xy[:, 1] - unit.position.y) <= reach)[0]]
        # standing inside a spot remembered (not just currently) defended, with nothing precise enough left in `covering` to explain it -
        # a real Unit's .position is all step_back_from reads, so a plain stand-in does the same job for a remembered spot
        covering = covering + [SimpleNamespace(position=p) for p, r in self.danger.spots() if unit.position.distance_to(p) <= r]

        if any(ability in unit.abilities for ability in LOCK_ON_ABILITIES):
            picked = self._pick_target(unit, pool, ranks, xy, reach, tags)
            if picked is not None:
                target, cast_from, in_range = picked
                if in_range:
                    if self.cyclones.cast_lock_on(unit, target):
                        return
                else:
                    move_to(unit, cast_from)
                    return
            if covering:
                step_back_from(self.ai, ctx, unit, covering, orders)
            else:
                threat_circles = [(Point2((float(x), float(y))), float(r)) for (x, y), r in zip(xy, reach)]
                # what is remembered but not already precisely accounted for above (still live, or a fresh ghost: `threats` already covers
                # it, with the raid's own weapon-based reach - adding a second, coarser circle for the very same enemy would only make the
                # cast/search geometry less precise for no reason)
                remembered = [(p, r) for p, r in self.danger.spots() if not any(p.distance_to(t) <= 1.0 for t, _ in threat_circles)]
                # and anything else still worth a lock (a worker, most often - nothing else was left to walk towards): stop short of it by
                # the same margin _pick_target casts from, so the search arrives already standing off instead of walking onto it and only
                # backing out afterwards. A melee or short-ranged one is already covered above by its own (usually tighter) threat circle;
                # this only ever matters for what does not otherwise threaten the Cyclone back.
                cast_standoff = self.cyclones.lockon_range - RAID_CAST_SLACK
                standoff = [(e.position, cast_standoff) for e, rank in zip(pool, ranks) if rank is not None]
                self._search(unit, pool, threat_circles + remembered + standoff, orders, ctx)
            return

        # no Lock On: nothing is attacked. Out of reach of everything, and waiting for it
        if covering:
            step_back_from(self.ai, ctx, unit, covering, orders)
        else:
            self._keep_out_of_own_range(unit, pool, orders, ctx)

    # ------------------------------------------------------------------------------------------------------------
    # what can hit the Cyclone
    # ------------------------------------------------------------------------------------------------------------
    def _info(self, enemy: Unit, unit: Unit) -> Tuple[Optional[int], float]:
        """(what a Lock On on this enemy is worth, how far from it the Cyclone is inside its reach - 0 when it cannot hit the Cyclone), the one
        and the other worked out once per enemy and step: every enemy is looked at by every raider, and each is a dozen reads of a protobuf."""
        entry = self._memo.get(id(enemy))
        if entry is None:
            entry = self._memo[id(enemy)] = (enemy, self._rank(enemy), self._reach(enemy, unit) if self._threatens(enemy, unit) else 0.0)
        return entry[1], entry[2]

    @staticmethod
    def _threatens(enemy: Unit, unit: Unit) -> bool:
        if enemy.is_hallucination or enemy.type_id in RAID_IGNORE or enemy.type_id in ENEMY_WORKER_TYPES:
            return False
        if enemy.is_memory and enemy.age > FIGHT_GHOST_MAX_AGE:
            return False
        if not (enemy.can_attack_air if unit.is_flying else enemy.can_attack_ground):
            return False
        return not (enemy.is_structure and (not enemy.is_ready or not enemy.is_powered))

    @staticmethod
    def _reach(enemy: Unit, unit: Unit) -> float:
        """How far from the enemy's CENTRE the Cyclone is inside what it has to keep out of: its range, both radii, and the margin."""
        weapon = enemy.air_range if unit.is_flying else enemy.ground_range
        reach = weapon + enemy.radius + unit.radius + RAID_MARGIN
        if enemy.ground_range <= MELEE_RANGE_THRESHOLD:
            reach += RAID_MELEE_EXTRA
        return reach

    # ------------------------------------------------------------------------------------------------------------
    # the target
    # ------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _rank(enemy: Unit) -> Optional[int]:
        """How much a Lock On on this enemy is worth (0 is best); None: not a target."""
        if enemy.is_memory or enemy.is_hallucination or not enemy.is_visible or (enemy.is_cloaked and not enemy.is_revealed):
            return None
        if enemy.type_id in RAID_IGNORE:
            return None
        if enemy.is_structure:
            return RAID_STRUCTURES.get(enemy.type_id)
        if enemy.type_id in ENEMY_WORKER_TYPES:
            return WORKER_RANK
        return None if enemy.type_id in ATTACK_TARGET_IGNORE_WITH_WORKERS else 0

    def _pick_target(
        self, unit: Unit, pool: List[Unit], ranks: List[Optional[int]], xy: np.ndarray, reach: np.ndarray, tags: np.ndarray
    ) -> Optional[Tuple[Unit, Point2, bool]]:
        """(target, where to cast from, is the Cyclone in cast range there already) of the best target that can be reached safely, or None.
        `xy`, `reach` and `tags` are the enemies that can hit the Cyclone: where they stand, how far from there it is inside their reach, who."""
        cast_range = self.cyclones.lockon_range
        candidates = []
        for enemy, rank in zip(pool, ranks):
            if rank is None or enemy.tag in self.cyclones.lock_ons:
                continue
            ability = AbilityId.LOCKONAIR_LOCKONAIR if enemy.is_flying else AbilityId.LOCKON_LOCKON
            if ability not in unit.abilities:
                continue
            gap = unit.distance_to(enemy) - unit.radius - enemy.radius
            if gap > RAID_ENGAGE_RANGE:
                continue
            in_range = gap <= cast_range
            cast_from = unit.position if in_range else enemy.position.towards(unit.position, enemy.radius + unit.radius + cast_range - RAID_CAST_SLACK)
            candidates.append(((rank, unit.distance_to(cast_from), enemy.tag), enemy, cast_from, in_range))
        candidates.sort(key=lambda c: c[0])
        for _, enemy, cast_from, in_range in candidates:
            # the target itself may hit back (a Cannon reaches 7): a shot or two while the cast goes off is the price. Anything else that
            # can hit the Cyclone must be out of reach of the spot, and of the way there
            others = tags != enemy.tag
            if not others.any():
                return enemy, cast_from, in_range
            if _any_within(xy[others], reach[others], cast_from):
                continue
            if not in_range and _any_within_reach_of_segment(xy[others], reach[others], unit.position, cast_from):
                continue
            return enemy, cast_from, in_range
        return None

    # ------------------------------------------------------------------------------------------------------------
    # nothing to hit: go and look
    # ------------------------------------------------------------------------------------------------------------
    def _search(self, unit: Unit, pool: List[Unit], circles: List[Tuple[Point2, float]], orders: GroupOrders, ctx: ArmyContext) -> None:
        destination = self._destination(unit, ctx)
        point = clip_before(unit.position, destination, circles)
        if point.distance_to(unit.position) > 1.0:
            path_move(self.ai, ctx, unit, point)
        else:
            self._keep_out_of_own_range(unit, pool, orders, ctx)          # (it has got there: it waits)

    def _keep_out_of_own_range(self, unit: Unit, pool: List[Unit], orders: GroupOrders, ctx: ArmyContext) -> None:
        """A Cyclone that is waiting steps out of its own weapon range of whatever it could shoot: idle, it would fire on workers and buildings."""
        reach = unit.ground_range + RAID_IDLE_MARGIN
        close = [
            e for e in pool
            if not e.is_memory and e.is_visible and not e.is_hallucination and e.type_id not in RAID_IGNORE
            and (unit.can_attack_air if e.is_flying else unit.can_attack_ground)
            and unit.distance_to(e) - unit.radius - e.radius <= reach
        ]
        if close:
            step_back_from(self.ai, ctx, unit, close, orders)

    def _destination(self, unit: Unit, ctx: ArmyContext) -> Point2:
        """The nearest thing worth going to: a known Cannon or Battery, an enemy army (seen a moment ago), a Nexus - and when nothing is
        known, their natural."""
        ai = self.ai
        points: List[Point2] = [s.position for s in ai.enemy_structures if s.type_id in RAID_STRUCTURES or s.type_id == U.NEXUS]
        points += [
            e.position for e in ai.enemy_units
            # ATTACK_TARGET_IGNORE, not the WITH_WORKERS version: a worker IS worth walking towards - _pick_target/_rank locks on to one
            # "when there is nothing else" (WORKER_RANK), which never gets the chance if nothing ever walks close enough to find one
            if not e.is_structure and not e.is_hallucination and e.type_id not in ATTACK_TARGET_IGNORE and e.type_id not in RAID_IGNORE
            and (not e.is_memory or e.age <= MEMORY_SECONDS)
        ]
        if not points:
            return ctx.mediator.get_enemy_nat
        return min(points, key=lambda p: p.distance_to(unit.position))


# ---- geometry ------------------------------------------------------------------------------------------------------
def _any_within(xy: np.ndarray, reach: np.ndarray, p: Point2) -> bool:
    """Is `p` inside any of the circles (centres `xy`, radii `reach`)?"""
    return bool((np.hypot(xy[:, 0] - p.x, xy[:, 1] - p.y) <= reach).any())


def _any_within_reach_of_segment(xy: np.ndarray, reach: np.ndarray, a: Point2, b: Point2) -> bool:
    """Does the straight way from a to b come closer than the radius to any of the circles' centres? (segment_hits_circle, for many)"""
    dx, dy = b.x - a.x, b.y - a.y
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 < 1e-9 else np.clip(((xy[:, 0] - a.x) * dx + (xy[:, 1] - a.y) * dy) / length2, 0.0, 1.0)
    return bool((np.hypot(a.x + dx * t - xy[:, 0], a.y + dy * t - xy[:, 1]) < reach).any())


def segment_hits_circle(a: Point2, b: Point2, centre: Point2, radius: float) -> bool:
    """Does the straight way from a to b come closer than `radius` to `centre`?"""
    dx, dy = b.x - a.x, b.y - a.y
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 < 1e-9 else max(0.0, min(1.0, ((centre.x - a.x) * dx + (centre.y - a.y) * dy) / length2))
    return math.hypot(a.x + dx * t - centre.x, a.y + dy * t - centre.y) < radius


def clip_before(a: Point2, b: Point2, circles: List[Tuple[Point2, float]]) -> Point2:
    """The farthest point on the way from a to b before it enters any of the circles ((centre, radius) pairs): b itself when none is in the
    way, a when it starts inside one."""
    dx, dy = b.x - a.x, b.y - a.y
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return a
    ux, uy = dx / length, dy / length
    reach = length
    for centre, radius in circles:
        fx, fy = a.x - centre.x, a.y - centre.y
        c = fx * fx + fy * fy - radius * radius
        if c <= 0:
            return a
        half = fx * ux + fy * uy
        discriminant = half * half - c
        if discriminant < 0:
            continue
        t = -half - math.sqrt(discriminant)          # where the way first crosses the circle
        if 0 <= t < reach:
            reach = t
    return Point2((a.x + ux * reach, a.y + uy * reach))
