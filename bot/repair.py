"""SCV repairs - and the rules they keep.

An SCV with a repair order on a unit follows that unit for as long as it needs repairs, wherever it goes. Left alone that sent SCVs
across the whole map behind the army (and back once the repair was over), or on long detours round cliffs to a unit hovering over
ground they cannot cross. So:

* never more than MAX_REPAIRERS (4) SCVs on one unit or building;
* never a walk longer than MAX_TRAVEL (70) to come and repair something - the GROUND PATH to it, not the straight line - and an
  SCV that has walked that far on one job (a unit that keeps moving away) goes back to mining;
* only near home: what is repaired stands within HOME_RADIUS of one of our landed townhalls, and only SCVs within LEASH of one are
  sent (an SCV that ends up farther is called back). The leash is wider than the radius so that an SCV trailing a unit that walks
  out of the radius is not sent back and picked again, over and over;
* a flying unit only while it hovers where an SCV can stand under it - not over the middle of a townhall, a mineral line or a cliff,
  where the SCV stops at the edge, out of repair range (the banshees' repair spot is open ground for that reason, units/banshees.py).

Only SCVs that are mining (or idle) are sent, never one that has a job of its own (building, scouting, walking to an expansion).
"""
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from sc2.bot_ai import BotAI
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit
from sc2.units import Units

from bot.pathing.order_utils import path_length, reachable_from_ground

MAX_REPAIRERS = 4              # never more than this many SCVs on one unit or building
MAX_TRAVEL = 70.0              # never a longer walk than this (ground path) to repair something, or on one repair job
HOME_RADIUS = 25.0             # a damaged unit or building is only repaired while it is this close to one of our (landed) townhalls
LEASH = 35.0                   # only SCVs this close to one of them are sent, and one that ends up farther is sent back to mine
STRUCTURE_BELOW = 0.9          # buildings are repaired below this share of their health...
UNIT_BELOW = 0.7               # ...army units, which take chip damage all the time, only below this
ORDER_GRACE = 1.0              # seconds a repair order may take to show up in the observation before the job counts as over
WALK_CACHE_SECONDS = 3.0       # how long a measured walk is remembered
NO_CREW_BACKOFF = 1.0          # a target nobody could be sent to is not looked at again for this long
_NOT_REPAIRED = {UnitTypeId.SCV, UnitTypeId.MULE, UnitTypeId.AUTOTURRET}


@dataclass
class RepairJob:
    target: int                # tag of what the SCV was sent to repair
    since: float               # game time it was sent
    last: Tuple[float, float]  # where it was when last looked at
    walked: float = 0.0        # how far it has walked on this job so far


def _home_distance(bases: Units, unit: Unit) -> float:
    return bases.closest_distance_to(unit)


def _release(self: BotAI, worker: Unit, bases: Units) -> None:
    """Send an SCV back to mine (the unit gets repaired again once it is back home)."""
    self.repair_jobs.pop(worker.tag, None)
    if not self.mineral_field.empty:
        worker.gather(self.mineral_field.closest_to(bases.closest_to(worker)))


def ground_walk(self: BotAI, worker: Unit, target: Unit) -> Optional[float]:
    """How far `worker` has to walk over the ground to get to `target` (its path, not the straight line); None when there is no way
    (a unit hovering over ground nobody can reach). Remembered for WALK_CACHE_SECONDS."""
    key = (worker.tag, target.tag)
    now = self.time
    hit = self.repair_walks.get(key)
    if hit is not None and now - hit[0] < WALK_CACHE_SECONDS:
        return hit[1]
    path = self.mediator.find_raw_path(
        start=worker.position, target=target.position, grid=self.mediator.get_cached_ground_grid, sensitivity=1
    )
    length = path_length(worker.position, path)
    self.repair_walks[key] = (now, length)
    return length


def _follow_jobs(self: BotAI, bases: Units, repairing: List[Unit]) -> Dict[int, List[Unit]]:
    """Update the SCVs' repair jobs (how far each has walked), end the ones that are over, and send back the ones that broke a rule:
    walked more than MAX_TRAVEL, ended up farther than LEASH from every base, or crowd a target beyond MAX_REPAIRERS. Returns the SCVs
    repairing each target, by tag (those just sent, whose order is not in the observation yet, included as long as ORDER_GRACE lasts)."""
    now = self.time
    crews: Dict[int, List[Unit]] = {}
    for worker in repairing:
        target = worker.order_target
        if isinstance(target, int):
            crews.setdefault(target, []).append(worker)
    seen_repairing = {w.tag for w in repairing}
    for tag, job in list(self.repair_jobs.items()):
        worker = self.workers.find_by_tag(tag)
        if worker is None:
            del self.repair_jobs[tag]
        elif tag not in seen_repairing or worker.order_target != job.target:
            if now - job.since > ORDER_GRACE:
                del self.repair_jobs[tag]                        # the repair is over: done, or the target is gone
            else:
                crews.setdefault(job.target, []).append(worker)   # sent a moment ago: the observation has not caught up yet
        else:
            x, y = worker.position_tuple
            job.walked += math.hypot(x - job.last[0], y - job.last[1])
            job.last = (x, y)
    for worker in repairing:
        job = self.repair_jobs.get(worker.tag)
        if _home_distance(bases, worker) > LEASH or (job is not None and job.walked > MAX_TRAVEL):
            _release(self, worker, bases)
            for crew in crews.values():
                if worker in crew:
                    crew.remove(worker)
    # a hard cap: nobody may be on the same unit beyond MAX_REPAIRERS (however it came about) - the ones farthest from it leave
    for tag, crew in crews.items():
        if len(crew) > MAX_REPAIRERS:
            target = (self.units | self.structures).find_by_tag(tag)
            crew.sort(key=lambda w: w.distance_to(target) if target is not None else 0.0, reverse=True)
            for worker in crew[:len(crew) - MAX_REPAIRERS]:
                _release(self, worker, bases)
            del crew[:len(crew) - MAX_REPAIRERS]
    return crews


def _wanted(target: Unit) -> int:
    """How many SCVs a target deserves right now (never more than MAX_REPAIRERS)."""
    if target.is_structure:
        # a flying building (a CC lifted to evade a rush) is out of danger - repairable, but no crew like something under fire
        wanted = 1 if target.is_flying else (4 if target.health_percentage < 0.5 else 2)
    else:
        wanted = 2 if target.health_percentage < 0.3 else 1
    return min(wanted, MAX_REPAIRERS)


def _targets(self: BotAI, bases: Units) -> List[Unit]:
    """What needs repairing and is worth sending SCVs to, the most damaged first: buildings (ready, below STRUCTURE_BELOW) and mechanical
    army units (below UNIT_BELOW, and standing where it is safe to send an SCV) - near home only. A flying one has to hover where an SCV
    can stand under it: over the middle of a townhall, a mineral line or a cliff it cannot be reached (the SCV stops at the edge)."""
    grid = self.mediator.get_cached_ground_grid
    targets: List[Unit] = [
        s for s in self.structures.ready
        if s.health_percentage <= STRUCTURE_BELOW and s.type_id not in _NOT_REPAIRED and _home_distance(bases, s) <= HOME_RADIUS
        and (not s.is_flying or reachable_from_ground(grid, s.position, s.radius))
    ]
    # is_mechanical is also true for SCVs/MULEs in the actual game data - excluding them is required, not a style choice, otherwise every
    # worker that takes a scratch of damage is queued as a repair target and pulls other workers off mining to chase it down
    targets.extend(
        u for u in self.units
        if u.is_mechanical and u.type_id not in _NOT_REPAIRED and u.health_percentage <= UNIT_BELOW
        and _home_distance(bases, u) <= HOME_RADIUS and self.is_unit_position_safe(u)
        and (not u.is_flying or reachable_from_ground(grid, u.position, u.radius))
    )
    targets.sort(key=lambda t: t.health_percentage)
    return targets


def manage_repairs(self: BotAI) -> None:
    """One step of repairing: keep the rules for the SCVs that are at it, then staff the targets that lack a crew."""
    bases: Units = self.townhalls.not_flying
    if bases.empty:
        return
    repairing: List[Unit] = [w for w in self.workers if w.is_repairing]
    crews = _follow_jobs(self, bases, repairing)
    if self.worker_rushed and not self.army_advisor.is_wall_closed():
        return

    now = self.time
    if len(self.repair_walks) > 400:
        self.repair_walks = {k: v for k, v in self.repair_walks.items() if now - v[0] < WALK_CACHE_SECONDS}
    self.repair_backoff = {tag: until for tag, until in self.repair_backoff.items() if until > now}

    # SCVs with a job of their own are not ours to send (the scripted build order's builder, the scout)
    busy: Set[int] = {t for t in (self.build_order_critical_worker, self.scout_worker_tag) if t is not None}
    pool: List[Unit] = [
        w for w in self.workers
        if (w.is_gathering or w.is_idle) and w.tag not in busy and w.tag not in self.repair_jobs and _home_distance(bases, w) <= LEASH
    ]
    for target in _targets(self, bases):
        missing = _wanted(target) - len(crews.get(target.tag, ()))
        if missing <= 0 or not pool or self.repair_backoff.get(target.tag, 0.0) > now:
            continue
        candidates = sorted((w for w in pool if w.distance_to(target) <= MAX_TRAVEL), key=lambda w: w.distance_to(target))
        sent = 0
        for worker in candidates[:missing + 3]:              # a few more than needed: some may have no way there
            walk = ground_walk(self, worker, target)
            if walk is None or walk > MAX_TRAVEL:
                continue
            worker(AbilityId.EFFECT_REPAIR_SCV, target)
            self.repair_jobs[worker.tag] = RepairJob(target=target.tag, since=now, last=worker.position_tuple)
            crews.setdefault(target.tag, []).append(worker)
            pool.remove(worker)
            sent += 1
            if sent >= missing:
                break
        if sent == 0:
            self.repair_backoff[target.tag] = now + NO_CREW_BACKOFF
