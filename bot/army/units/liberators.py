"""Liberators: siege (Defender Mode) on enemy Siege Tanks first - our tanks screen them from Marines, see tanks.py -
then on anything else worth hitting; fly with the army when there is nothing to siege.

The Defender Mode lock starts the moment the morph is ORDERED, never when LIBERATORAG happens to show up in the
observation - otherwise an unsiege order can be issued in the very next step and the unit flips straight back. It also
runs for a while after LIBERATORAG DOES show up (the morph takes longer than the lock, so the first observation of
Defender Mode can come after the lock expired), and what keeps it sieged is something inside the ZONE it was ordered to
cover - not something near the Liberator, which hovers up to a cast range away from its own zone. Nothing outside the zone keeps it
sieged: once the shooting window is over and the zone is empty, it comes down.

It never waits on the list of abilities the game says a unit can use: whether that list carries the morph under the id used here is
unproven, and a Liberator that hovers in position for an ability that never shows up is a Liberator that never sieges. The order is
simply given; if the unit does not turn into a Defender Mode Liberator after a few tries, that target is given up on for a while."""
from typing import Dict, Optional

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.army.consts import ATTACK_TARGET_IGNORE_WITH_WORKERS
from bot.army.context import ArmyContext
from bot.army.orders import GroupOrders
from bot.army.units.common import attack_move, follow_point, kite_away, path_move

MIN_AG_DURATION = 3.0          # once we COMMAND the siege it cannot be unsieged until this much game time has passed
MIN_AG_SHOOTING = 3.0          # ...nor until it has been seen in Defender Mode for this long: it has to get a chance to fire
AG_ZONE_RADIUS = 5.0           # radius of the zone a sieged Liberator covers
AG_ZONE_MARGIN = 1.5           # enemies this far outside the zone still count: they are about to walk in (or just walked out)
AG_OFFSET = 4.0                # put the siege position this far from the target (towards us)
AG_DEFAULT_CAST_RANGE = 10.0   # how far from itself a Liberator can put its zone; the game data's number is used when it is bigger
SIEGE_MORPH_TIMEOUT = 6.0      # a siege order that has not turned the unit into a Defender Mode Liberator by then is counted as failed
SIEGE_RETRY_LIMIT = 3          # failed orders before that target is given up on...
SIEGE_APPROACH_PATIENCE = 15.0 # ...and so is a siege that this many seconds of trying have not got in position
SIEGE_GIVE_UP_SECONDS = 20.0   # a Liberator that gave up leaves sieging alone for this long
CAST_BUFFER = 0.25             # stay slightly inside the true ability range
MORPH_COMMAND_COOLDOWN = 0.5   # never spam morph commands
SIEGE_SEEK_RANGE = 45.0        # do not send a Liberator across the map for one visible target
_SIEGE_TANKS = {UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED}
_AG = AbilityId.MORPH_LIBERATORAGMODE
_AA = AbilityId.MORPH_LIBERATORAAMODE


class LiberatorController:
    def __init__(self, ai):
        self.ai = ai
        self.ag_cast_range: float = max(AG_DEFAULT_CAST_RANGE, ai.game_data.abilities[_AG.value]._proto.cast_range)
        self.ag_locked_until: Dict[int, float] = {}    # tag -> earliest time we may unsiege (set when the siege is ORDERED)
        self.ag_zone: Dict[int, Point2] = {}           # tag -> centre of the zone it was ordered to cover
        self.ag_first_seen: Dict[int, float] = {}      # tag -> when it was first observed in Defender Mode
        self.last_morph_command: Dict[int, float] = {}
        self.siege_ordered_at: Dict[int, float] = {}   # tag -> when the last siege order was given (until the unit is seen in Defender Mode)
        self.siege_orders: Dict[int, int] = {}         # tag -> siege orders given in the current attempt
        self.siege_started: Dict[int, float] = {}      # tag -> since when it has been trying to siege something
        self.no_siege_until: Dict[int, float] = {}     # tag -> it gave up on sieging: it leaves it alone until then

    def control(self, units: Units, orders: GroupOrders, ctx: ArmyContext) -> None:
        ctx.prefetch_near(units)
        alive = {u.tag for u in self.ai.units}      # this controller runs once per group per step - prune by DEAD units only
        for table in (self.ag_locked_until, self.ag_zone, self.ag_first_seen, self.siege_ordered_at, self.siege_orders,
                      self.siege_started, self.no_siege_until):
            for tag in [t for t in table if t not in alive]:
                del table[tag]
        for unit in units:
            if unit.type_id == UnitTypeId.LIBERATORAG:
                self._end_attempt(unit)                      # it worked: the attempt is over
                self._maybe_leave_ag(unit, ctx)
                continue
            self.ag_first_seen.pop(unit.tag, None)        # back in fighter mode: the next siege starts its own clock
            if self._try_siege(unit, ctx):
                continue
            # nothing to siege: behave like any other air support unit - stay safe, stay with the army
            if kite_away(self.ai, ctx, unit):
                continue
            point = follow_point(orders)
            if orders.aggressive:
                attack_move(unit, point)
            elif unit.distance_to(point) > orders.hold_radius:
                path_move(self.ai, ctx, unit, point)

    # ------------------------------------------------------------------------------------------------------------
    # target selection
    # ------------------------------------------------------------------------------------------------------------
    def _siege_target(self, unit: Unit) -> Optional[Unit]:
        """Enemy Siege Tanks have absolute priority; otherwise the nearest non-worker ground unit. Only what we can
        see right now - a remembered ghost is not worth a siege."""
        visible = [
            e for e in self.ai.enemy_units
            if not e.is_memory and not e.is_flying and unit.distance_to(e) <= SIEGE_SEEK_RANGE
        ]
        tanks = [e for e in visible if e.type_id in _SIEGE_TANKS]
        if tanks:
            return min(tanks, key=lambda e: unit.distance_to(e))
        others = [e for e in visible if e.type_id not in ATTACK_TARGET_IGNORE_WITH_WORKERS]
        if others:
            return min(others, key=lambda e: unit.distance_to(e))
        return None

    # ------------------------------------------------------------------------------------------------------------
    # fighter -> defender mode
    # ------------------------------------------------------------------------------------------------------------
    def _try_siege(self, unit: Unit, ctx: ArmyContext) -> bool:
        """True when the Liberator has been given a siege-related order (or must be left alone this step)."""
        now = self.ai.time
        if not self._can_morph(unit):
            return True        # a morph command is still fresh - don't fight it
        if now - self.siege_ordered_at.get(unit.tag, -1e9) < SIEGE_MORPH_TIMEOUT:
            return True        # ordered a moment ago and the unit has not shown up in Defender Mode yet: it is deploying
        if self.no_siege_until.get(unit.tag, 0.0) > now:
            return False
        target = self._siege_target(unit)
        if target is None:
            self._end_attempt(unit)
            return False
        # don't fly into an unsafe position just to siege
        if not ctx.is_safe(unit):
            return False
        if now - self.siege_started.setdefault(unit.tag, now) > SIEGE_APPROACH_PATIENCE:
            return self._give_up(unit, now)

        siege_pos: Point2 = target.position.towards(unit.position, AG_OFFSET)
        cast_range = self.ag_cast_range - CAST_BUFFER

        if unit.distance_to(siege_pos) <= cast_range:
            if self.siege_orders.get(unit.tag, 0) >= SIEGE_RETRY_LIMIT:
                return self._give_up(unit, now)        # ordered again and again, and it never turned into a Defender Mode Liberator
            unit(_AG, siege_pos)
            self.siege_orders[unit.tag] = self.siege_orders.get(unit.tag, 0) + 1
            self.siege_ordered_at[unit.tag] = now
            self.last_morph_command[unit.tag] = now
            self.ag_locked_until[unit.tag] = now + MIN_AG_DURATION   # the lock starts NOW
            self.ag_zone[unit.tag] = siege_pos
            return True

        # too far away: approach the siege position
        approach = siege_pos.towards(unit.position, cast_range)
        path_move(self.ai, ctx, unit, approach)
        return True

    def _end_attempt(self, unit: Unit) -> None:
        for table in (self.siege_ordered_at, self.siege_orders, self.siege_started):
            table.pop(unit.tag, None)

    def _give_up(self, unit: Unit, now: float) -> bool:
        """This siege is not happening (no Defender Mode after several orders, or it never got in position): leave sieging alone for a
        while, so the Liberator goes back to being an air-support unit instead of hovering over a spot forever."""
        self._end_attempt(unit)
        self.ag_zone.pop(unit.tag, None)
        self.ag_locked_until.pop(unit.tag, None)
        self.no_siege_until[unit.tag] = now + SIEGE_GIVE_UP_SECONDS
        return False

    # ------------------------------------------------------------------------------------------------------------
    # defender -> fighter mode
    # ------------------------------------------------------------------------------------------------------------
    def _maybe_leave_ag(self, unit: Unit, ctx: ArmyContext) -> None:
        """Hard locks first: nothing may cause an unsiege before the order-time lock expires, nor before it has been seen
        in Defender Mode for MIN_AG_SHOOTING. After that, stay sieged while something worthwhile is in its zone (or right
        next to it), otherwise go back to fighter mode."""
        now = self.ai.time
        first_seen = self.ag_first_seen.setdefault(unit.tag, now)
        locked_until = self.ag_locked_until.get(unit.tag)
        if locked_until is not None and now < locked_until:
            return
        if now - first_seen < MIN_AG_SHOOTING:
            return
        if self._something_to_shoot(unit):
            return
        if not self._can_morph(unit):
            return
        unit(_AA)
        self.last_morph_command[unit.tag] = now
        self.ag_locked_until.pop(unit.tag, None)
        self.ag_zone.pop(unit.tag, None)

    def _something_to_shoot(self, unit: Unit) -> bool:
        """A ground unit worth a shot inside the zone this Liberator covers (plus a margin) - and nothing else: whatever walks about
        outside the zone, however close to the Liberator, is no reason to stay sieged (a sieged Liberator only shoots into its zone, and
        cannot get away). Defender Mode only hits units, so buildings do not count. When the zone is unknown (it always is known for a
        Liberator we sieged) everything within reach of a cast counts."""
        zone = self.ag_zone.get(unit.tag)
        reach = AG_ZONE_RADIUS + AG_ZONE_MARGIN
        for e in self.ai.enemy_units:
            if e.is_memory or e.is_flying or e.type_id in ATTACK_TARGET_IGNORE_WITH_WORKERS:
                continue
            if zone is not None:
                if e.position.distance_to(zone) <= reach:
                    return True
            elif e.distance_to(unit) <= self.ag_cast_range + reach:
                return True
        return False

    def _can_morph(self, unit: Unit) -> bool:
        last = self.last_morph_command.get(unit.tag)
        return last is None or self.ai.time - last >= MORPH_COMMAND_COOLDOWN
