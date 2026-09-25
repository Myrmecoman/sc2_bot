"""Liberators: siege (Defender Mode) on enemy Siege Tanks first - our tanks screen them from Marines, see tanks.py -
then on anything else worth hitting; fly with the army when there is nothing to siege.

The Defender Mode lock starts the moment the morph is ORDERED, never when LIBERATORAG happens to show up in the
observation - otherwise an unsiege order can be issued in the very next step and the unit flips straight back. It also
runs for a while after LIBERATORAG DOES show up (the morph takes longer than the lock, so the first observation of
Defender Mode can come after the lock expired), and what keeps it sieged is something inside the ZONE it was ordered to
cover - not something near the Liberator, which hovers up to a cast range away from its own zone."""
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
AG_HOLD_CHECK_RANGE = 6.0      # after the lock, stay sieged while something worthwhile is this close
AG_OFFSET = 4.0                # put the siege position this far from the target (towards us)
CAST_BUFFER = 0.25             # stay slightly inside the true ability range
MORPH_COMMAND_COOLDOWN = 0.5   # never spam morph commands
SIEGE_SEEK_RANGE = 45.0        # do not send a Liberator across the map for one visible target
_SIEGE_TANKS = {UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED}
_AG = AbilityId.MORPH_LIBERATORAGMODE
_AA = AbilityId.MORPH_LIBERATORAAMODE


class LiberatorController:
    def __init__(self, ai):
        self.ai = ai
        self.ag_cast_range: float = ai.game_data.abilities[_AG.value]._proto.cast_range
        self.ag_locked_until: Dict[int, float] = {}    # tag -> earliest time we may unsiege (set when the siege is ORDERED)
        self.ag_zone: Dict[int, Point2] = {}           # tag -> centre of the zone it was ordered to cover
        self.ag_first_seen: Dict[int, float] = {}      # tag -> when it was first observed in Defender Mode
        self.last_morph_command: Dict[int, float] = {}

    def control(self, units: Units, orders: GroupOrders, ctx: ArmyContext) -> None:
        ctx.prefetch_near(units)
        alive = {u.tag for u in self.ai.units}      # this controller runs once per group per step - prune by DEAD units only
        for table in (self.ag_locked_until, self.ag_zone, self.ag_first_seen):
            for tag in [t for t in table if t not in alive]:
                del table[tag]
        for unit in units:
            if unit.type_id == UnitTypeId.LIBERATORAG:
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
        if not self._can_morph(unit):
            return True        # a morph command is still fresh - don't fight it
        target = self._siege_target(unit)
        if target is None:
            return False
        # don't fly into an unsafe position just to siege
        if not ctx.is_safe(unit):
            return False

        siege_pos: Point2 = target.position.towards(unit.position, AG_OFFSET)
        cast_range = self.ag_cast_range - CAST_BUFFER

        if unit.distance_to(siege_pos) <= cast_range:
            if _AG not in unit.abilities:
                # in position but the morph is not available yet - do NOT move away
                return True
            unit(_AG, siege_pos)
            self.last_morph_command[unit.tag] = self.ai.time
            self.ag_locked_until[unit.tag] = self.ai.time + MIN_AG_DURATION   # the lock starts NOW
            self.ag_zone[unit.tag] = siege_pos
            return True

        # too far away: approach the siege position
        approach = siege_pos.towards(unit.position, cast_range)
        path_move(self.ai, ctx, unit, approach)
        return True

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
        """A ground unit worth a shot inside the zone this Liberator covers (plus a margin), or right next to the Liberator.
        Defender Mode only hits units, so buildings do not count. When the zone is unknown (it always is known for a
        Liberator we sieged) everything within reach of a cast counts."""
        zone = self.ag_zone.get(unit.tag)
        reach = AG_ZONE_RADIUS + AG_ZONE_MARGIN
        for e in self.ai.enemy_units:
            if e.is_memory or e.is_flying or e.type_id in ATTACK_TARGET_IGNORE_WITH_WORKERS:
                continue
            if e.distance_to(unit) <= AG_HOLD_CHECK_RANGE:
                return True
            if zone is not None:
                if e.position.distance_to(zone) <= reach:
                    return True
            elif e.distance_to(unit) <= self.ag_cast_range + reach:
                return True
        return False

    def _can_morph(self, unit: Unit) -> bool:
        last = self.last_morph_command.get(unit.tag)
        return last is None or self.ai.time - last >= MORPH_COMMAND_COOLDOWN
