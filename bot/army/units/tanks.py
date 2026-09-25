"""Siege Tanks: dig in early at assigned slots while holding, siege close to targets while attacking, and screen
sieged Liberators from Marines. All the numbers below are the ones the previous tank controller was tuned with."""
from typing import Dict, List, Optional, Tuple

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.army.consts import ATTACK_TARGET_IGNORE_WITH_WORKERS, STAGING_ARRIVAL_RANGE
from bot.army.context import ArmyContext
from bot.army.orders import GroupOrders
from bot.army.positioning import TANK_SPACING, Positioning
from bot.army.units.common import attack_move, kite_away, path_move
from bot.pathing.order_utils import spread_out_point

TANK_HOLD_ARRIVAL_RANGE = 4.0  # close enough to its slot to dig in proactively
MIN_SIEGE_DURATION = 3.0       # once sieged, stay that way at least this long - stops flip-flopping (and wasting the morph time) when a target briefly leaves range
SIEGE_ENGAGE_RANGE = 11.0      # siege once an enemy is within this, not the full 13 sieged range
ENEMY_HOLD_RANGE = 14.0        # ...and only unsiege once nothing shootable is within this
# Buildings are big: measured centre to centre a Hatchery can be 16.6 away and still be inside a sieged tank's range 13 (range is
# taken edge to edge), so the two numbers above - tuned on units - are applied to a building's NEAREST EDGE. Otherwise a tank
# that is happily shelling a building unsieges the moment the centre distance passes 14.
TANK_SEARCH_RADIUS = 18.0      # ...which means looking farther than the usual fight radius: 13 + tank 0.9 + biggest building 2.8 + margin
LIBERATOR_GUARD_RADIUS = 9.0   # how close a tank should sit to a sieged Liberator to meaningfully screen it from Marines
LIBERATOR_GUARD_MAX = 2        # never pile more tanks than this onto guarding one Liberator


class TankController:
    def __init__(self, ai, positioning: Positioning):
        self.ai = ai
        self.positioning = positioning
        self.siege_since: Dict[int, float] = {}   # tank tag -> game time it became sieged, cleared once it unsieges
        self.slot_index: Dict[Tuple[str, int], int] = {}   # (group label, tank tag) -> stable index into that group's slot line

    # ------------------------------------------------------------------------------------------------------------
    def control(self, units: Units, orders: GroupOrders, ctx: ArmyContext) -> None:
        if not units:
            return
        ctx.prefetch_near(units)
        guard_point = self._liberator_guard_point()
        slots: Optional[List[Point2]] = None
        if not orders.aggressive:
            self._assign_slots(units, orders.label)
            slots = self.positioning.tank_slots(
                orders.hold_point, max(self.slot_index[(orders.label, u.tag)] for u in units) + 1, orders.front
            )
        for unit in units:
            self._track_siege_state(unit)
            if orders.aggressive:
                self._attack(unit, units, orders, ctx, guard_point)
            else:
                slot = slots[self.slot_index[(orders.label, unit.tag)]] if slots else orders.hold_point
                self._hold(unit, units, ctx, guard_point if guard_point is not None else slot)

    # ------------------------------------------------------------------------------------------------------------
    # attacking: siege near targets, otherwise march with the army (or guard an exposed Liberator)
    # ------------------------------------------------------------------------------------------------------------
    def _attack(self, unit: Unit, units: Units, orders: GroupOrders, ctx: ArmyContext,
                guard_point: Optional[Point2]) -> None:
        closest = self._closest_target_distance(unit, ctx)

        if unit.type_id == UnitTypeId.SIEGETANK and closest is not None and closest <= SIEGE_ENGAGE_RANGE:
            self._siege(unit)
            return
        # the army is stopping at a staging point short of static defense: dig in there, in range of it
        if (
            unit.type_id == UnitTypeId.SIEGETANK
            and orders.staging is not None
            and unit.position.distance_to(orders.staging) <= STAGING_ARRIVAL_RANGE
        ):
            self._siege(unit)
            return
        if unit.type_id == UnitTypeId.SIEGETANKSIEGED:
            # ALWAYS finish here while sieged, whether or not it actually unsieges this step: a sieged tank cannot
            # move or attack-move (the engine fires on its own), so falling through to the movement code below
            # would just issue orders it cannot execute
            if self._can_unsiege(unit, ctx):
                self._unsiege(unit)
            return

        # no target and in danger: run away
        if not ctx.is_safe(unit):
            kite_away(self.ai, ctx, unit)
            return

        # head for the fight - or for an under-protected sieged Liberator, which is rooted and defenseless against the
        # Marines that would otherwise kill it - spread out so we're not stacked on one tile (our own splash, AOE)
        destination = guard_point if guard_point is not None else orders.target
        point = spread_out_point(unit, units, destination, radius=TANK_SPACING, nudge=TANK_SPACING,
                                 walkable=self.ai.in_pathing_grid)
        attack_move(unit, point)

    # ------------------------------------------------------------------------------------------------------------
    # holding: dig in at the slot, proactively, before anything shows up
    # ------------------------------------------------------------------------------------------------------------
    def _hold(self, unit: Unit, units: Units, ctx: ArmyContext, effective_pos: Point2) -> None:
        closest = self._closest_target_distance(unit, ctx)
        safe = ctx.is_safe(unit)
        at_hold_point = unit.position.distance_to(effective_pos) <= TANK_HOLD_ARRIVAL_RANGE

        if unit.type_id == UnitTypeId.SIEGETANKSIEGED:
            # only unsiege if we actually need to move - the slot shifted (gated, so a barely-sieged tank does not
            # pop straight back up over a minor reposition)
            if not at_hold_point and self._can_unsiege(unit, ctx):
                self._unsiege(unit)
            return

        if unit.type_id == UnitTypeId.SIEGETANK and safe:
            close_enough_to_fight = closest is not None and closest <= SIEGE_ENGAGE_RANGE
            if close_enough_to_fight or at_hold_point:
                self._siege(unit)
                return

        if not safe:
            kite_away(self.ai, ctx, unit)
            return

        point = spread_out_point(unit, units, effective_pos, radius=TANK_SPACING, nudge=TANK_SPACING,
                                 walkable=self.ai.in_pathing_grid)
        path_move(self.ai, ctx, unit, point)

    # ------------------------------------------------------------------------------------------------------------
    def _assign_slots(self, units: Units, label: str) -> None:
        """Stable slot per tank within its group. This controller runs once per group per step, so bookkeeping is
        keyed by group and only ever pruned by tanks that are DEAD (or have moved to another group) - never by
        "not in this call's units", which would erase every other group's slots."""
        alive = {u.tag for u in self.ai.units}
        here = {u.tag for u in units}
        for key in [k for k in self.slot_index if k[1] not in alive or (k[0] == label and k[1] not in here)]:
            del self.slot_index[key]
        used = {index for (lab, _), index in self.slot_index.items() if lab == label}
        for unit in sorted(units, key=lambda u: u.tag):
            if (label, unit.tag) in self.slot_index:
                continue
            index = 0
            while index in used:
                index += 1
            self.slot_index[(label, unit.tag)] = index
            used.add(index)

    def _track_siege_state(self, unit: Unit) -> None:
        if unit.type_id == UnitTypeId.SIEGETANKSIEGED:
            self.siege_since.setdefault(unit.tag, self.ai.time)
        else:
            self.siege_since.pop(unit.tag, None)

    def _can_unsiege(self, unit: Unit, ctx: ArmyContext) -> bool:
        """Stay sieged while there is anything to shoot - a ground unit within ENEMY_HOLD_RANGE, or a visible building whose
        nearest edge is - and for at least MIN_SIEGE_DURATION."""
        closest = self._closest_target_distance(unit, ctx)
        if closest is not None and closest <= ENEMY_HOLD_RANGE:
            return False
        held_since = self.siege_since.get(unit.tag)
        return held_since is None or self.ai.time - held_since >= MIN_SIEGE_DURATION

    @classmethod
    def _closest_target_distance(cls, unit: Unit, ctx: ArmyContext) -> Optional[float]:
        """How far the nearest thing this tank could shoot is: centre to centre for units, edge to edge for buildings (which
        are big, see ENEMY_HOLD_RANGE). None when there is nothing."""
        best: Optional[float] = None
        for e in cls._ground_enemies(unit, ctx):
            distance = unit.distance_to(e)
            if e.is_structure:
                distance -= unit.radius + e.radius
            if best is None or distance < best:
                best = distance
        return best

    @staticmethod
    def _ground_enemies(unit: Unit, ctx: ArmyContext) -> List[Unit]:
        """Everything a tank could shoot: tanks cannot hit air at all, sieged or not - so a lifted structure is excluded too -
        and a building only counts while it is actually visible (an old snapshot cannot be targeted)."""
        return [
            e for e in ctx.enemies_within(unit, TANK_SEARCH_RADIUS)
            if not e.is_flying and not e.is_memory and e.type_id not in ATTACK_TARGET_IGNORE_WITH_WORKERS
            and (not e.is_structure or e.is_visible)
        ]

    def _liberator_guard_point(self) -> Optional[Point2]:
        """Position of the sieged (Defender Mode) Liberator that most needs tank cover right now - fewer than
        LIBERATOR_GUARD_MAX tanks already near it - or None. A rooted Liberator cannot fight or flee a Marine closing
        in, so a tank standing nearby to kill that Marine first is what keeps the trade in our favor."""
        liberators = self.ai.units(UnitTypeId.LIBERATORAG)
        if not liberators:
            return None
        tanks = self.ai.units.of_type({UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED})
        for liberator in liberators:
            if tanks.closer_than(LIBERATOR_GUARD_RADIUS, liberator).amount < LIBERATOR_GUARD_MAX:
                return liberator.position
        return None

    @staticmethod
    def _siege(unit: Unit) -> None:
        if not unit.is_using_ability(AbilityId.SIEGEMODE_SIEGEMODE):
            unit(AbilityId.SIEGEMODE_SIEGEMODE)

    @staticmethod
    def _unsiege(unit: Unit) -> None:
        if not unit.is_using_ability(AbilityId.UNSIEGE_UNSIEGE):
            unit(AbilityId.UNSIEGE_UNSIEGE)
