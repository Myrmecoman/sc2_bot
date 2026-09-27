"""Cyclones: Lock-On (worth spending on real targets, skytoss first), otherwise kite like the rest of the army.

A locked-on Cyclone keeps firing at the unit up to LOCK_ON_HOLD_RANGE (15), for as long as it stays in view - it does not have to stand
in front of it. So while a lock runs it KITES: it steps out of whatever enemy fire it is standing in, but never so far that the target
leaves the lock's range (that would end it), and it follows a target that is walking away for the same reason. A lock that ended (the
target died, left view, got out of range, or the cast never took) hands the Cyclone back to the normal logic below."""
import math
from typing import Dict, List, Optional, Set, Tuple

from cython_extensions import cy_attack_ready, cy_closest_to, cy_in_attack_range

from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.army.consts import ATTACK_TARGET_IGNORE_WITH_WORKERS, KITE_IN_RESULT, LOCAL_FIGHT_RADIUS, SKYTOSS_TYPES
from bot.army.context import ArmyContext
from bot.army.orders import GroupOrders
from bot.army.units.common import (
    all_melee,
    attack_move,
    attack_unit,
    follow_point,
    futile_to_kite,
    kite_away,
    kite_from_banelings,
    move_to,
    path_move,
    stutter_forward,
)
from bot.army.units.repair_retreat import RepairRetreat
from bot.pathing.order_utils import plain_point, segment_walkable, terrain_view

LOCK_ON_TIMEOUT = 15.0   # forget a lock-on after this long - the target is presumably dead or gone
LOCK_ON_ABILITIES = {AbilityId.LOCKON_LOCKON, AbilityId.LOCKONAIR_LOCKONAIR}
LOCK_ON_HOLD_RANGE = 15.0     # once locked on, the Cyclone keeps firing at the unit up to this range (edge to edge), while it is in view
LOCK_ON_MARGIN = 1.5          # ...and stays this far inside it: the target moves too
LOCK_ON_STEP = 4.0            # the longest step it takes to follow a target that is walking out of range
LOCK_ON_MIN_STEP = 1.0        # a retreat that only gains less than this is not one that keeps the lock
MIN_LOCK_STANDOFF = 6.0        # the lock drains the target from anywhere inside LOCK_ON_HOLD_RANGE: never worth standing closer than this
                                # (the Cyclone's own weapon only reaches 5 - the generic combat path, or a coincidental close cast, can
                                # otherwise leave it locked on right next to the target for the whole duration)
LOCK_ON_CAST_SECONDS = 0.3    # nothing is ordered this soon after the cast: a move order could cancel it before it is through
LOCK_ON_CONFIRM_SECONDS = 1.5 # a cast has to show by then (the order, the buff on the target, or the ability on cooldown) or it never took
# The lock ends when the target is out of view - whoever sees it. A Cyclone that backs out of fire keeps it in view when it can, unless something
# else of ours watches it anyway: the way out must not lead down a ramp or behind a cliff (from a lower level the target cannot be seen), and it
# must stay inside the Cyclone's own sight (11 - the lock goes on to 15).
VIEW_RING_FRACTIONS = (0.3, 0.5, 0.7, 0.85, 1.0)  # how far from where it stands the other ways out are looked for, as a fraction of its
                                 # own sight range - a fixed distance either falls well short of a single structure's own danger radius
                                 # (a Cannon's 7 range + Ares' 4-cell buffer is already 11, more than the Cyclone's whole sight) or searches
                                 # past where a spot could ever pass the sight check below anyway, whatever the actual danger turns out to be
VIEW_DIRECTIONS = 12            # ...in this many directions, at each
CYCLONE_SIGHT = 11.0            # (when the game data does not say)
OTHER_SIGHT = 9.0               # ...nor for the other units of ours
SIGHT_MARGIN = 0.5
CLOSER_TOLERANCE = 0.5          # a way out is never a step towards the target (through the fire) - not by more than this


class CycloneController:
    def __init__(self, ai):
        self.ai = ai
        self.lock_ons: Dict[int, float] = {}   # enemy tag -> time we locked on, so one target is not re-locked every frame
        self.locks: Dict[int, Tuple[int, float]] = {}   # cyclone tag -> (enemy tag, time) of the lock it has running
        self.lockon_range: float = ai.game_data.abilities[AbilityId.LOCKON_LOCKON.value]._proto.cast_range
        self._watchers: Dict[int, Set[int]] = {}      # enemy tag -> the units of ours that can see it (this step)
        # a hurt Cyclone goes home to be repaired, like a Banshee (units/repair_retreat.py): to the army's hold point, where the SCVs come
        self.repair = RepairRetreat(ai, lambda unit, orders, ctx: orders.hold_point)

    def begin_step(self, units: Units, ctx: ArmyContext) -> None:
        """Forget the locks that are over (also for the raiding Cyclones, cyclone_raid.py, which share this state)."""
        now = self.ai.time
        for tag in [t for t, cast_at in self.lock_ons.items() if now - cast_at > LOCK_ON_TIMEOUT]:
            del self.lock_ons[tag]
        alive = {u.tag for u in self.ai.units}      # this controller runs once per group per step - prune by DEAD units only
        for tag in [t for t in self.locks if t not in alive]:
            del self.locks[tag]
        self.repair.forget(alive)
        self._watchers = {}
        ctx.prefetch_near(units)

    def control(self, units: Units, orders: GroupOrders, ctx: ArmyContext) -> None:
        self.begin_step(units, ctx)
        for unit in units:
            self._control_unit(unit, orders, ctx)

    # ------------------------------------------------------------------------------------------------------------
    def _control_unit(self, unit: Unit, orders: GroupOrders, ctx: ArmyContext) -> None:
        if self.handle_running_lock(unit, orders, ctx) or self.repair_trip(unit, orders, ctx):
            return

        # is_visible only means the position is in vision, not that the unit can be seen through cloak - a permanently-cloaked one
        # (an Observer) or a cloaked/burrowed one with no detector over it is reported all the same, just untargetable
        targets = [e for e in ctx.targets_near(unit) if e.can_be_attacked]
        if self._try_lock_on(unit, targets):
            return

        if not targets:
            self._no_fight(unit, orders, ctx)
            return

        in_range = cy_in_attack_range(unit, targets)
        # banelings: always back away, whatever else is true (see kite_from_banelings, and BioController for the details)
        banelings = ctx.banelings_near(unit)
        close_banelings = ctx.close_banelings(unit)
        if not orders.aggressive and in_range and not close_banelings:
            # holding: keep firing at whatever is already in range, exactly like a stationary defender would
            attack_unit(unit, cy_closest_to(unit.position, in_range))
            return

        nearest: Unit = cy_closest_to(unit.position, targets)
        if cy_attack_ready(self.ai, unit, nearest):
            attack_unit(unit, nearest)
            return

        if close_banelings:
            kite_from_banelings(self.ai, ctx, unit, close_banelings, orders)
            return

        advance = orders.advance_result(unit)          # the fight this unit is in, judged as an advance (see BioController)
        winning = (
            advance is not None
            and advance >= KITE_IN_RESULT
            and not banelings
            and not all_melee([e for e in ctx.enemies_near(unit) if not e.is_memory and e.distance_to(unit) <= LOCAL_FIGHT_RADIUS])
        )
        # not worth backing off when the nearest threat outranges us and is not slower (kiting cannot create
        # distance), or when we are locally crushing the fight anyway - neither holds with banelings about
        if not (futile_to_kite(unit, nearest) and not banelings) and not winning and not ctx.is_safe(unit):
            if orders.retreating:
                path_move(self.ai, ctx, unit, orders.hold_point)
                return
            if kite_away(self.ai, ctx, unit):
                return
        if winning and stutter_forward(self.ai, unit, nearest):
            return
        attack_unit(unit, nearest)

    def repair_trip(self, unit: Unit, orders: GroupOrders, ctx: ArmyContext) -> bool:
        """A Cyclone that is too damaged goes home to be repaired and waits there (also the raiding ones, cyclone_raid.py): True when it is on
        such a trip, nothing else may be ordered for it. Where it is going to and when it comes back: see RepairRetreat."""
        home = self.repair.update(unit, orders, ctx)
        if home is None:
            return False
        if unit.distance_to(home) > self.repair.wait_radius:
            path_move(self.ai, ctx, unit, home)
        return True

    def handle_running_lock(self, unit: Unit, orders: GroupOrders, ctx: ArmyContext) -> bool:
        """A lock-on that is running keeps draining the target without the cyclone having to stay in front of it: it kites (and does not spend
        the ability again - a new cast would end this lock). True when the unit has a lock going or a cast under way: nothing else may be
        ordered for it this step."""
        locked = self._locked_target(unit)
        if locked is not None:
            # (while the cast itself is still on the unit - its order is there, or it was ordered a moment ago - a move order could
            # cancel it: nothing is ordered before it is through)
            if not unit.is_using_ability(LOCK_ON_ABILITIES) and self.ai.time - self.locks[unit.tag][1] >= LOCK_ON_CAST_SECONDS:
                self._kite_locked(unit, locked, orders, ctx)
            return True
        return unit.is_using_ability(LOCK_ON_ABILITIES)        # a lock we have no record of (yet): leave it alone

    # ------------------------------------------------------------------------------------------------------------
    def _try_lock_on(self, unit: Unit, targets: List[Unit]) -> bool:
        """Spend Lock-On on a fresh, worthwhile target (never a worker). True if the command was issued."""
        if not unit.abilities:
            return False
        candidates = [
            e for e in targets
            if e.type_id not in ATTACK_TARGET_IGNORE_WITH_WORKERS
            and e.tag not in self.lock_ons
            and unit.distance_to(e) <= unit.radius + e.radius + self.lockon_range
        ]
        if not candidates:
            return False
        return self.cast_lock_on(unit, self.pick_lockon_target(candidates))

    def cast_lock_on(self, unit: Unit, target: Unit) -> bool:
        """Order the lock on `target` (the air or the ground one) and record it. False when the game does not offer that ability now."""
        ability = AbilityId.LOCKONAIR_LOCKONAIR if target.is_flying else AbilityId.LOCKON_LOCKON
        if ability not in unit.abilities:
            return False
        unit(ability, target)
        self.lock_ons[target.tag] = self.ai.time
        self.locks[unit.tag] = (target.tag, self.ai.time)
        return True

    # ------------------------------------------------------------------------------------------------------------
    # a lock that is running
    # ------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _gap(unit: Unit, target: Unit) -> float:
        """Distance between the two, edge to edge (the way the game measures range)."""
        return unit.distance_to(target) - unit.radius - target.radius

    def _lock_shows(self, unit: Unit, target: Unit) -> bool:
        """Is there a sign that the cast took: the Cyclone is still at it, the target carries the lock, or the ability is on cooldown?
        Any one will do (which of them the game shows is not something to bet the whole feature on)."""
        ability = AbilityId.LOCKONAIR_LOCKONAIR if target.is_flying else AbilityId.LOCKON_LOCKON
        return unit.is_using_ability(LOCK_ON_ABILITIES) or target.has_buff(BuffId.LOCKON) or ability not in unit.abilities

    def _locked_target(self, unit: Unit) -> Optional[Unit]:
        """The enemy this Cyclone has locked on to, while that lock can still be running; None once it cannot: too long ago, the target is
        dead or out of view (a remembered ghost is out of view), it got out of the lock's range, or the cast never took."""
        record = self.locks.get(unit.tag)
        if record is None:
            return None
        tag, since = record
        now = self.ai.time
        target = self.ai.enemy_units.find_by_tag(tag)
        if (
            now - since > LOCK_ON_TIMEOUT
            or target is None or target.is_memory
            or self._gap(unit, target) > LOCK_ON_HOLD_RANGE
            or (now - since > LOCK_ON_CONFIRM_SECONDS and not self._lock_shows(unit, target))
        ):
            del self.locks[unit.tag]
            if target is not None and now - since <= LOCK_ON_CONFIRM_SECONDS + 1.0:
                self.lock_ons.pop(tag, None)                    # a cast that did not take may be tried again
            return None
        return target

    def _kite_locked(self, unit: Unit, target: Unit, orders: GroupOrders, ctx: ArmyContext) -> None:
        hold = LOCK_ON_HOLD_RANGE - LOCK_ON_MARGIN
        grid = ctx.grid_for(unit)
        if ctx.is_safe(unit):
            gap = self._gap(unit, target)
            if gap > hold:
                # the target is walking away and the lock ends at 15: follow it - through safe ground only
                step = unit.position.towards(target.position, min(gap - hold + 2.0, LOCK_ON_STEP))
                if ctx.mediator.is_position_safe(grid=grid, position=step):
                    move_to(unit, step)
            elif gap < MIN_LOCK_STANDOFF:
                # too close for no reason: the lock does not need it, and it is well inside the Cyclone's own weapon range (5)
                step = target.position.towards(unit.position, MIN_LOCK_STANDOFF + unit.radius + target.radius)
                if ctx.mediator.is_position_safe(grid=grid, position=step):
                    move_to(unit, step)
            return                                              # nothing to run from: the lock does the work
        # in enemy fire: get out of it, but not so far that the target leaves the lock's range
        if orders.retreating:
            want = plain_point(self.ai.mediator.find_path_next_point(start=unit.position, target=orders.hold_point, grid=grid, sense_danger=True))
        else:
            want = plain_point(ctx.mediator.find_closest_safe_spot(from_pos=unit.position, grid=grid, radius=11))
        step = farthest_within(unit.position, want, target.position, hold + unit.radius + target.radius)
        if step is not None and not orders.retreating and not self._keeps_view(unit, step, target):
            # the plain way out loses the target (down a ramp, behind a cliff, out of sight): another that is safe and keeps it in view, if any
            step = self._spot_with_view(unit, target, ctx, grid) or step
        if step is not None:
            move_to(unit, step)
        elif orders.retreating:
            path_move(self.ai, ctx, unit, orders.hold_point)
        else:
            kite_away(self.ai, ctx, unit)                       # no way out that keeps the lock: the Cyclone comes first

    def _sees(self, spot: Point2, target: Unit) -> bool:
        """Would a unit at `spot` see the target past the terrain? (Flying units are seen over every cliff.)"""
        return target.is_flying or terrain_view(self.ai.game_info.terrain_height.data_numpy, spot, target.position)

    @staticmethod
    def _sight(unit: Unit) -> float:
        return (unit.sight_range or CYCLONE_SIGHT) - SIGHT_MARGIN

    def _keeps_view(self, unit: Unit, spot: Point2, target: Unit) -> bool:
        """Will the target still be in view when the Cyclone stands at `spot`? Yes when it is inside its own sight and not hidden by the terrain,
        or when something else of ours can see it (a lock ends when the target is out of view, whoever sees it)."""
        if spot.distance_to(target.position) <= self._sight(unit) and self._sees(spot, target):
            return True
        watchers = self._watchers.get(target.tag)
        if watchers is None:
            watchers = self._watchers[target.tag] = {
                other.tag for other in self.ai.all_own_units
                if other.distance_to(target) <= (other.sight_range or OTHER_SIGHT) and (other.is_flying or self._sees(other.position, target))
            }
        return bool(watchers - {unit.tag})

    def _spot_with_view(self, unit: Unit, target: Unit, ctx: ArmyContext, grid) -> Optional[Point2]:
        """The nearest spot a Cyclone in fire can back out to - safe, inside the lock's range, on the ground it can walk, and not nearer to the
        target than it is - from which it sees the target itself: inside its sight (11, the lock goes on to 15) and not hidden by the terrain.
        None when there is no such spot (then it backs out the plain way and gives the lock up)."""
        ai = self.ai
        limit = LOCK_ON_HOLD_RANGE - LOCK_ON_MARGIN + unit.radius + target.radius
        here = unit.position.distance_to(target.position)
        for reach in (self._sight(unit) * f for f in VIEW_RING_FRACTIONS):
            for k in range(VIEW_DIRECTIONS):
                angle = 2.0 * math.pi * k / VIEW_DIRECTIONS
                spot = Point2((unit.position.x + reach * math.cos(angle), unit.position.y + reach * math.sin(angle)))
                gap = spot.distance_to(target.position)
                if gap > min(limit, self._sight(unit)) or gap < here - CLOSER_TOLERANCE or not (ai.in_map_bounds(spot) and ai.in_pathing_grid(spot)):
                    continue
                if not ctx.mediator.is_position_safe(grid=grid, position=spot) or not self._sees(spot, target):
                    continue
                if not segment_walkable(unit.position, spot, ai.in_pathing_grid):
                    continue
                return spot                                            # (the rings come nearest first)
        return None

    def _no_fight(self, unit: Unit, orders: GroupOrders, ctx: ArmyContext) -> None:
        point = follow_point(orders, walkable=self.ai.in_pathing_grid)
        if orders.aggressive:
            attack_move(unit, point)
        elif unit.distance_to(point) > orders.hold_radius:
            path_move(self.ai, ctx, unit, point)

    @staticmethod
    def pick_lockon_target(enemies: List[Unit]) -> Unit:
        """Prefer high-value skytoss air if any is lockable, else the lowest effective HP like the other classes."""
        priority = [e for e in enemies if e.type_id in SKYTOSS_TYPES]
        pool = priority if priority else enemies
        return min(pool, key=lambda e: (e.health + e.shield, e.tag))


def farthest_within(start: Point2, want: Point2, center: Point2, limit: float) -> Optional[Point2]:
    """The farthest point on the way from `start` to `want` that is still within `limit` of `center` (`want` itself when it is). None when
    not even a useful first step is possible: the way out of the circle starts at once, or `start` is already outside it and `want`
    does not bring it back in."""
    dx, dy = want.x - start.x, want.y - start.y
    length = math.hypot(dx, dy)
    if length < 0.1:
        return None
    fx, fy = start.x - center.x, start.y - center.y
    if fx * fx + fy * fy > limit * limit:
        return want if math.hypot(want.x - center.x, want.y - center.y) < math.hypot(fx, fy) else None
    a, b, c = length * length, 2 * (fx * dx + fy * dy), fx * fx + fy * fy - limit * limit
    t = min(1.0, (-b + math.sqrt(max(0.0, b * b - 4 * a * c))) / (2 * a))      # where the way crosses the circle
    if t * length < LOCK_ON_MIN_STEP:
        return None
    return Point2((start.x + dx * t, start.y + dy * t))
