"""Worker micro that is not mining: stopping Planetary Fortress rushes, protecting workers that are constructing, and
pulling workers out of harm's way - away from an Oracle in particular, which they dodge instead of huddling at the townhall it
follows them to. (Army micro lives in bot/army/.)

All of these look at enemies that are visible RIGHT NOW (`visible_enemy_units`), not the remembered ghosts Ares keeps
in `enemy_units` - reacting to a unit that left vision half a minute ago would drag workers around for nothing."""
import math
from typing import Callable, Optional, Sequence, Set

import numpy as np
from scipy.spatial.distance import cdist

from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.pathing.order_utils import is_already_moving_to, segment_walkable

WORKER_FLEE_RANGE = 7.0   # start pulling workers back before a fast threat like a reaper is already on top of them

# Oracles: the Pulsar Beam reaches 4 (and there are the two radii), and an Oracle is faster than a worker, so a worker that waits until it is
# in range is already being shot at. Workers move straight away from it (not to the townhall, which is where it follows them to) as soon as
# it is within AVOID + ALERT_MARGIN, one FLEE_STEP at a time so that they are never in its range, and stay put - not back to mining under it -
# until it is more than AVOID + RELEASE_MARGIN away or out of sight.
ORACLE_AVOID_RANGE = 5.0
ORACLE_ALERT_MARGIN = 2.5
ORACLE_RELEASE_MARGIN = 5.0
ORACLE_FLEE_STEP = 6.0
FLEE_HOME_RADIUS = 22.0          # a worker is never sent farther than this from one of our townhalls (and one that is farther is left alone)
_FLEE_TURNS = (0.0, 30.0, -30.0, 60.0, -60.0, 90.0, -90.0)          # degrees off "straight away" tried when that way is blocked
_ANY_TURN = _FLEE_TURNS + (120.0, -120.0, 150.0, -150.0, 180.0)      # ...and when there is no "away" (right under it, or pulled both ways alike)


def prevent_PF_rush(self: BotAI):
    enemy_flying_structures: Units = self.enemy_structures.of_type({UnitTypeId.COMMANDCENTERFLYING})
    if enemy_flying_structures.amount == 0 or self.workers.gathering.amount == 0:
        return

    # remove dead buildings or with dead SCV
    keys = [i for i in self.worker_assigned_to_follow.keys()]
    for i in keys:
        if enemy_flying_structures.find_by_tag(i) is None or self.workers.find_by_tag(enemy_flying_structures.find_by_tag(i)) is None:
            self.worker_assigned_to_follow.pop(i, None)

    # updating all flying buildings
    for i in enemy_flying_structures:
        if not i.tag in self.worker_assigned_to_follow.keys():
            self.worker_assigned_to_follow[i.tag] = -1

    # if no worker assigned, give one and remember it
    for i in self.structures:
        closest_enemy_struct = enemy_flying_structures.closest_to(i)
        if closest_enemy_struct.distance_to(i) > 14 or self.workers.gathering.amount == 0:
            continue
        if self.worker_assigned_to_follow[closest_enemy_struct.tag] != -1:
            self.workers.find_by_tag(self.worker_assigned_to_follow[closest_enemy_struct.tag]).move(closest_enemy_struct.position)
            continue
        closest_worker: Unit = self.workers.gathering.closest_to(closest_enemy_struct)
        closest_worker.move(closest_enemy_struct.position)
        self.worker_assigned_to_follow[closest_enemy_struct.tag] = closest_worker.tag


def defend_building_workers(self: BotAI):
    enemy_workers = self.visible_enemy_units.of_type({UnitTypeId.SCV, UnitTypeId.PROBE, UnitTypeId.DRONE})
    if enemy_workers.amount == 0 or self.workers.gathering.amount == 0:
        return

    # updating all threatened workers
    for i in self.workers:
        if not i.is_constructing_scv or enemy_workers.closest_distance_to(i) > 10:
            continue
        if not i.tag in self.worker_assigned_to_defend.keys() or self.workers.find_by_tag(self.worker_assigned_to_defend[i.tag]) is None:
            self.worker_assigned_to_defend[i.tag] = -1
    keys = [i for i in self.worker_assigned_to_defend.keys()]
    for i in keys:
        if self.workers.find_by_tag(i) is None or enemy_workers.closer_than(10, self.workers.find_by_tag(i)).amount > 1:
            if self.worker_assigned_to_defend[i] != -1 and self.workers.find_by_tag(self.worker_assigned_to_defend[i]) is not None:
                self.workers.find_by_tag(self.worker_assigned_to_defend[i]).move(self.townhalls.first)
            self.worker_assigned_to_defend.pop(i)

    # if no worker assigned, give one and remember it
    for i in self.worker_assigned_to_defend.keys():
        if self.worker_assigned_to_defend[i] != -1:
            continue
        closest_worker = self.workers.gathering.closest_to(self.workers.find_by_tag(i))
        closest_worker.attack(self.workers.find_by_tag(i).position)
        self.worker_assigned_to_defend[i] = closest_worker.tag


def point_away_from(origin: Point2, threats: Sequence[Point2], step: float, ok: Callable[[Point2], bool]) -> Optional[Point2]:
    """The point `step` from `origin` on the side away from `threats` (a nearer one counts for more), or, where `ok` refuses that, the nearest
    turn from it (30 degrees at a time, up to 90 either way: never back towards them) that `ok` accepts. None when nothing is accepted."""
    vx = vy = 0.0
    for threat in threats:
        dx, dy = origin.x - threat.x, origin.y - threat.y
        gap = math.hypot(dx, dy)
        if gap > 0.05:
            vx += dx / (gap * gap)
            vy += dy / (gap * gap)
    length = math.hypot(vx, vy)
    turns = _FLEE_TURNS
    if length < 1e-9:
        # no side is "away": right under it, or pulled both ways alike (one on each side: go across). Any free way will do.
        turns = _ANY_TURN
        vx, vy, length = 1.0, 0.0, 1.0
        for threat in threats:
            dx, dy = origin.x - threat.x, origin.y - threat.y
            gap = math.hypot(dx, dy)
            if gap > 0.05:
                vx, vy, length = -dy, dx, gap
                break
    vx, vy = vx / length, vy / length
    for turn in turns:
        angle = math.radians(turn)
        dx = vx * math.cos(angle) - vy * math.sin(angle)
        dy = vx * math.sin(angle) + vy * math.cos(angle)
        candidate = Point2((origin.x + dx * step, origin.y + dy * step))
        if ok(candidate):
            return candidate
    return None


def avoid_oracles(self: BotAI) -> Set[int]:
    """Workers keep out from under an Oracle. Each worker within ORACLE_AVOID_RANGE + ORACLE_ALERT_MARGIN of one moves ORACLE_FLEE_STEP straight
    away from it (from all of those near it, the nearer ones counting for more) - to walkable ground within FLEE_HOME_RADIUS of a townhall -
    and is then kept out of `micro_worker`'s way (`oracle_fleeing`) until the Oracle is ORACLE_AVOID_RANGE + ORACLE_RELEASE_MARGIN away or gone.
    Returns the tags of the workers dealt with this step: the other flee logic leaves those alone."""
    handled: Set[int] = set()
    fleeing: Set[int] = self.oracle_fleeing
    # (a hallucinated Oracle shoots nothing)
    oracles = [] if self.worker_rushed else [o for o in self.visible_enemy_units.of_type({UnitTypeId.ORACLE}) if not o.is_hallucination]
    if not oracles:
        fleeing.clear()
        return handled
    fleeing &= {w.tag for w in self.workers}
    # workers already committed to a specific, actively-managed task elsewhere are left alone (as in flee_worker_threats)
    workers = [w for w in self.workers if not (w.is_repairing or w.is_constructing_scv)]
    if not workers:
        return handled
    positions = [o.position for o in oracles]
    gaps = cdist(np.array([w.position_tuple for w in workers]), np.array([o.position_tuple for o in oracles]))
    alert = ORACLE_AVOID_RANGE + ORACLE_ALERT_MARGIN
    release = ORACLE_AVOID_RANGE + ORACLE_RELEASE_MARGIN
    for worker, row in zip(workers, gaps):
        nearest = row.min()
        if nearest < alert:
            def ok(point: Point2, start: Point2 = worker.position) -> bool:
                return bool(
                    self.in_map_bounds(point) and self.in_pathing_grid(point) and self.townhalls.closest_distance_to(point) <= FLEE_HOME_RADIUS
                    and segment_walkable(start, point, self.in_pathing_grid)
                )

            target = point_away_from(worker.position, [p for p, gap in zip(positions, row) if gap < alert], ORACLE_FLEE_STEP, ok)
            if target is not None:
                fleeing.add(worker.tag)
                handled.add(worker.tag)
                if not is_already_moving_to(worker, target, epsilon=1.0):
                    worker.move(target)
        elif worker.tag in fleeing:
            if nearest >= release:
                fleeing.discard(worker.tag)
            else:
                handled.add(worker.tag)          # out of its range, and stays there: `micro_worker` does not send it back to mining
    return handled


def flee_worker_threats(self: BotAI, skip: Set[int] = frozenset()):
    """Pull workers away from an immediate combat threat (reaper/hellion harass etc.) instead of
    letting them keep mining and get picked off one by one - workers can't meaningfully fight
    back against most combat units, so self-preservation is the right reaction here, not
    continuing to work as if nothing is happening."""
    if self.worker_rushed:
        return  # worker_rush_defense already has its own dedicated worker-combat logic for that case

    # (Oracles are dodged, not run away from to the townhall: see avoid_oracles)
    threats: Units = self.visible_enemy_units.filter(
        lambda u: u.can_attack_ground and u.type_id not in {UnitTypeId.PROBE, UnitTypeId.SCV, UnitTypeId.DRONE, UnitTypeId.ORACLE}
    )
    if threats.amount == 0:
        return

    # (build_order_critical_worker is deliberately NOT exempted here (only from being re-picked for a DIFFERENT
    # task, e.g. by scout()) - early_build_order() runs earlier in the same step and keeps re-issuing its own
    # move order every frame regardless, so this only overrides it while a real threat is within
    # WORKER_FLEE_RANGE, and the build-order walk resumes on its own the instant the worker is safe again.
    # Exempting it from fleeing too would leave a worker walking to a build site defenseless against anything
    # that wanders close during the walk)
    # workers already committed to a specific, actively-managed task elsewhere are left alone
    workers = [w for w in self.workers if not (w.is_repairing or w.is_constructing_scv or w.tag in skip)]
    if not workers:
        return
    # one distance table instead of a search through every threat for every worker (70 workers against a visible army is thousands of pairs)
    gaps = cdist(np.array([w.position_tuple for w in workers]), np.array([t.position_tuple for t in threats])).min(axis=1)
    for worker, gap in zip(workers, gaps):
        if gap < WORKER_FLEE_RANGE:
            safe_spot: Point2 = self.townhalls.closest_to(worker).position
            if not is_already_moving_to(worker, safe_spot):
                worker.move(safe_spot)


def worker_micro(self: BotAI):
    prevent_PF_rush(self)
    defend_building_workers(self)
    flee_worker_threats(self, skip=avoid_oracles(self))
