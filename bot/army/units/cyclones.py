"""Cyclones: Lock-On (worth spending on real targets, skytoss first), otherwise kite like the rest of the army.

A locked-on Cyclone keeps firing at the unit up to LOCK_ON_HOLD_RANGE (15), for as long as it stays in view - it does not have to stand
in front of it. So while a lock runs it KITES: it steps out of whatever enemy fire it is standing in, but never so far that the target
leaves the lock's range (that would end it), and it follows a target that is walking away for the same reason. A lock that ended (the
target died, left view, got out of range, or the cast never took) hands the Cyclone back to the normal logic below."""
import math
from typing import Dict, List, Optional, Tuple

from cython_extensions import cy_attack_ready, cy_closest_to, cy_in_attack_range

from ares.behaviors.combat.individual import StutterUnitForward
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
    run,
)
from bot.pathing.order_utils import plain_point

LOCK_ON_TIMEOUT = 15.0   # forget a lock-on after this long - the target is presumably dead or gone
LOCK_ON_ABILITIES = {AbilityId.LOCKON_LOCKON, AbilityId.LOCKONAIR_LOCKONAIR}
LOCK_ON_HOLD_RANGE = 15.0     # once locked on, the Cyclone keeps firing at the unit up to this range (edge to edge), while it is in view
LOCK_ON_MARGIN = 1.5          # ...and stays this far inside it: the target moves too
LOCK_ON_STEP = 4.0            # the longest step it takes to follow a target that is walking out of range
LOCK_ON_MIN_STEP = 1.0        # a retreat that only gains less than this is not one that keeps the lock
LOCK_ON_CAST_SECONDS = 0.3    # nothing is ordered this soon after the cast: a move order could cancel it before it is through
LOCK_ON_CONFIRM_SECONDS = 1.5 # a cast has to show by then (the order, the buff on the target, or the ability on cooldown) or it never took


class CycloneController:
    def __init__(self, ai):
        self.ai = ai
        self.lock_ons: Dict[int, float] = {}   # enemy tag -> time we locked on, so one target is not re-locked every frame
        self.locks: Dict[int, Tuple[int, float]] = {}   # cyclone tag -> (enemy tag, time) of the lock it has running
        self.lockon_range: float = ai.game_data.abilities[AbilityId.LOCKON_LOCKON.value]._proto.cast_range

    def control(self, units: Units, orders: GroupOrders, ctx: ArmyContext) -> None:
        now = self.ai.time
        for tag in [t for t, cast_at in self.lock_ons.items() if now - cast_at > LOCK_ON_TIMEOUT]:
            del self.lock_ons[tag]
        alive = {u.tag for u in self.ai.units}      # this controller runs once per group per step - prune by DEAD units only
        for tag in [t for t in self.locks if t not in alive]:
            del self.locks[tag]
        ctx.prefetch_near(units)
        for unit in units:
            self._control_unit(unit, orders, ctx)

    # ------------------------------------------------------------------------------------------------------------
    def _control_unit(self, unit: Unit, orders: GroupOrders, ctx: ArmyContext) -> None:
        # a lock-on that is running keeps draining the target without the cyclone having to stay in front of it: kite (and do not spend
        # the ability again - a new cast would end this lock)
        locked = self._locked_target(unit)
        if locked is not None:
            # (while the cast itself is still on the unit - its order is there, or it was ordered a moment ago - a move order could
            # cancel it: nothing is ordered before it is through)
            if not unit.is_using_ability(LOCK_ON_ABILITIES) and self.ai.time - self.locks[unit.tag][1] >= LOCK_ON_CAST_SECONDS:
                self._kite_locked(unit, locked, orders, ctx)
            return
        if unit.is_using_ability(LOCK_ON_ABILITIES):        # a lock we have no record of (yet): leave it alone
            return

        targets = ctx.targets_near(unit)
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
        if winning and run(self.ai, StutterUnitForward(unit=unit, target=nearest)):
            return
        attack_unit(unit, nearest)

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
        target = self.pick_lockon_target(candidates)
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
            return                                              # nothing to run from: the lock does the work
        # in enemy fire: get out of it, but not so far that the target leaves the lock's range
        if orders.retreating:
            want = plain_point(self.ai.mediator.find_path_next_point(start=unit.position, target=orders.hold_point, grid=grid, sense_danger=True))
        else:
            want = plain_point(ctx.mediator.find_closest_safe_spot(from_pos=unit.position, grid=grid, radius=11))
        step = farthest_within(unit.position, want, target.position, hold + unit.radius + target.radius)
        if step is not None:
            move_to(unit, step)
        elif orders.retreating:
            path_move(self.ai, ctx, unit, orders.hold_point)
        else:
            kite_away(self.ai, ctx, unit)                       # no way out that keeps the lock: the Cyclone comes first

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
