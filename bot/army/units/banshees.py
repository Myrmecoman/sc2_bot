"""Banshees: worker harassment. Each banshee roams its own enemy base (the least anti-air defended ones first), kills
workers, hits-and-runs everything else, cloaks when it is in danger, and flies home to be repaired when hurt.

A target that is DEFENDED - the spot a banshee would have to shoot it from is inside enemy anti-air range - is not a target:
without this a banshee flies in, is driven out by the danger, flies back in, ... and never fires a shot. It picks another
one, or goes on to another base.

A banshee never just waits. Over its base with nothing to shoot (only buildings, the workers dead, nobody there at all) it moves on
to the next base after IDLE_PATIENCE, and when no base has anything for it, it rejoins the army for a while. A hurt one waits at a
townhall - where the SCVs are - for its repair, and goes back to work if nobody comes (no SCVs, no gas for the repair)."""
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
from cython_extensions import cy_attack_ready, cy_closest_to, cy_in_attack_range, cy_pick_enemy_target

from ares.behaviors.combat.individual import StutterUnitBack
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.army.consts import ENEMY_WORKER_TYPES
from bot.army.context import ArmyContext
from bot.army.orders import GroupOrders
from bot.army.positioning import TOWNHALL_TYPES, Positioning
from bot.army.units.common import attack_unit, kite_away, path_move, run

RETREAT_BELOW_HEALTH = 0.4     # fly home to be repaired below this...
RESUME_ABOVE_HEALTH = 0.9      # ...and go back out once repaired above this
BASE_DANGER_RADIUS = 8         # cells around a townhall inspected for anti-air influence when choosing a harass base
BASE_REEVALUATE_SECONDS = 15.0
BASE_TOO_DANGEROUS = 30.0      # anti-air influence at the mineral line above which a base is not worth flying into
MAX_HARASS_BASES = 4           # main, natural, third, fourth (ordered from the enemy's point of view)
STANDOFF_MARGIN = 0.5          # a banshee shoots from this much inside its weapon range
TARGET_PATIENCE = 6.0          # seconds a banshee may go for one target without firing a single shot...
WRITE_OFF_SECONDS = 25.0       # ...before that target, and whatever stands near it, is written off for this long
WRITE_OFF_RADIUS = 8.0
IDLE_PATIENCE = 6.0            # seconds a banshee may hover over its base with nothing to shoot before it moves on to another one
ARRIVED_RADIUS = 10.0          # "over its base": this close to the spot it was sent to
RECALL_SECONDS = 20.0          # with every base written off it rejoins the army for this long, then tries the bases again
REPAIR_WAIT_RADIUS = 6.0       # "waiting for its repair": this close to the townhall it flew home to
REPAIR_PATIENCE = 25.0         # seconds a hurt banshee waits there before it goes back to work unrepaired...
RETREAT_COOLDOWN = 60.0        # ...and is not sent home again for this long
MIN_CLOAKED_ENERGY = 3.0       # a cloaked banshee with more than this is only in danger where a detector sees it
CLOAK_START_ENERGY = 25.0      # energy needed to switch the cloak on
CLOAK_ON = AbilityId.BEHAVIOR_CLOAKON_BANSHEE
CLOAK_OFF = AbilityId.BEHAVIOR_CLOAKOFF_BANSHEE


class BansheeHarass:
    def __init__(self, ai, positioning: Positioning):
        self.ai = ai
        self.positioning = positioning
        self.roam: Dict[int, Point2] = {}         # banshee tag -> enemy base it is harassing
        self.retreating: Set[int] = set()         # banshees flying home to be repaired
        self._last_assignment: float = -1e9
        self._written_off: List[Tuple[Point2, float]] = []   # (position, until): defended or unreachable spots nobody goes for
        self._dull_bases: List[Tuple[Point2, float]] = []    # (base, until): bases a banshee hovered over with nothing to shoot
        self._focus: Dict[int, Tuple[int, float]] = {}       # banshee tag -> (target tag, since when it has been going for it)
        self._last_fired: Dict[int, float] = {}
        self._idle_since: Dict[int, float] = {}              # banshee tag -> since when it has hovered over its base with nothing to shoot
        self._recalled_until: Dict[int, float] = {}          # banshee tag -> it is with the army (no base is worth a visit) until then
        self._repair_wait_since: Dict[int, float] = {}       # banshee tag -> since when it has waited at home for its repair
        self._no_retreat_until: Dict[int, float] = {}        # banshee tag -> it gave up waiting for a repair: not sent home before then

    # ------------------------------------------------------------------------------------------------------------
    def control(self, units: Units, orders: GroupOrders, ctx: ArmyContext) -> None:
        alive = {u.tag for u in units}
        for table in (self.roam, self._focus, self._last_fired, self._idle_since, self._recalled_until, self._repair_wait_since,
                      self._no_retreat_until):
            for tag in [t for t in list(table) if t not in alive]:
                del table[tag]
        self.retreating &= alive
        now = self.ai.time
        self._written_off = [(p, until) for p, until in self._written_off if until > now]
        self._dull_bases = [(p, until) for p, until in self._dull_bases if until > now]
        ctx.prefetch_near(units)
        self._assign_bases(units, ctx)
        for unit in units:
            self._control_unit(unit, orders, ctx)

    # ------------------------------------------------------------------------------------------------------------
    # which base does each banshee harass
    # ------------------------------------------------------------------------------------------------------------
    def _candidate_bases(self, ctx: ArmyContext) -> List[Point2]:
        """Enemy bases ordered by how attractive they are: known-occupied first, then the least defended against air,
        then closest to the enemy's main (which is also where the workers are)."""
        bases = [loc for loc, _ in ctx.mediator.get_enemy_expansions][:MAX_HARASS_BASES]
        structures = self.ai.enemy_structures
        townhalls = structures.of_type(TOWNHALL_TYPES) if structures else structures

        def occupied(loc: Point2) -> bool:
            return bool(townhalls) and townhalls.closer_than(10, loc).amount > 0

        order = {loc: i for i, loc in enumerate(bases)}
        return sorted(
            bases, key=lambda loc: (self._is_written_off(loc, WRITE_OFF_RADIUS + 4.0) or self._is_dull(loc), not occupied(loc),
                                    self._danger_at(loc, ctx), order[loc])
        )

    def _is_written_off(self, position: Point2, radius: float = WRITE_OFF_RADIUS) -> bool:
        return any(p.distance_to(position) <= radius for p, _ in self._written_off)

    def _is_dull(self, base: Point2) -> bool:
        """A base a banshee has just found nothing to shoot at (kept apart from `_written_off`, which also keeps banshees from shooting
        at what stands near a spot: workers that show up there a moment later must not be ignored for that.)"""
        return any(p.distance_to(base) <= 1.0 for p, _ in self._dull_bases)

    @staticmethod
    def _danger_at(position: Point2, ctx: ArmyContext) -> float:
        """Anti-air influence around a base (from the Ares air grid: enemy AA units, turrets, spores, cannons)."""
        grid = ctx.air_grid
        r = BASE_DANGER_RADIUS
        x, y = int(position.x), int(position.y)
        window = grid[max(0, x - r): x + r + 1, max(0, y - r): y + r + 1]
        finite = window[np.isfinite(window)]
        return float(finite.max()) if finite.size else 0.0

    def _assign_bases(self, units: Units, ctx: ArmyContext) -> None:
        now = self.ai.time
        unassigned = [u for u in units if u.tag not in self.roam]
        stale = now - self._last_assignment >= BASE_REEVALUATE_SECONDS
        if not unassigned and not stale:
            return
        candidates = self._candidate_bases(ctx)
        if not candidates:
            return
        self._last_assignment = now
        taken = {tag: loc for tag, loc in self.roam.items()}

        def worth_going(loc: Point2) -> bool:
            return (self._danger_at(loc, ctx) < BASE_TOO_DANGEROUS and not self._is_written_off(loc, WRITE_OFF_RADIUS + 4.0)
                    and not self._is_dull(loc))

        for unit in units:
            current = self.roam.get(unit.tag)
            if current is not None and worth_going(current):
                continue
            used = {loc for tag, loc in taken.items() if tag != unit.tag}
            free = [loc for loc in candidates if loc not in used and worth_going(loc)]
            # every base is defended or written off: the least dangerous one, wherever that is - never just "stay"
            pick = free[0] if free else min(candidates, key=lambda loc: self._danger_at(loc, ctx))
            self.roam[unit.tag] = pick
            taken[unit.tag] = pick

    # ------------------------------------------------------------------------------------------------------------
    # per-banshee control
    # ------------------------------------------------------------------------------------------------------------
    def _repair_spot(self, unit: Unit, orders: GroupOrders) -> Point2:
        """Where a hurt banshee waits for its repair: over the nearest townhall, which is where the SCVs are (they only repair units
        near a base, see bot/macro.py). The army's hold point can be farther from any base than that."""
        bases = self.ai.townhalls.not_flying
        return bases.closest_to(unit).position if bases else orders.hold_point

    def _update_retreat(self, unit: Unit, orders: GroupOrders, now: float) -> None:
        """Hurt banshees go home, and come out again repaired - or unrepaired, when nobody repairs them (see REPAIR_PATIENCE)."""
        tag = unit.tag
        health = unit.health_percentage
        if tag in self.retreating:
            if health >= RESUME_ABOVE_HEALTH:
                self.retreating.discard(tag)
                self._repair_wait_since.pop(tag, None)
            elif unit.distance_to(self._repair_spot(unit, orders)) > REPAIR_WAIT_RADIUS:
                self._repair_wait_since.pop(tag, None)                   # still on its way
            elif now - self._repair_wait_since.setdefault(tag, now) > REPAIR_PATIENCE:
                self.retreating.discard(tag)
                self._repair_wait_since.pop(tag, None)
                self._no_retreat_until[tag] = now + RETREAT_COOLDOWN
        elif health < RETREAT_BELOW_HEALTH and now >= self._no_retreat_until.get(tag, 0.0):
            self.retreating.add(tag)

    def _destination(self, unit: Unit, orders: GroupOrders, ctx: ArmyContext, now: float) -> Point2:
        """Where a banshee with nothing to shoot goes: the base it was sent to - or, once it has hovered there for IDLE_PATIENCE with
        nothing to do, the next one, and when no base is worth a visit the army, for a while."""
        tag = unit.tag
        if self._recalled_until.get(tag, 0.0) > now:
            return self._army_point(orders)
        destination = self.roam.get(tag)
        if destination is None:
            return orders.target
        if unit.distance_to(destination) > ARRIVED_RADIUS:
            self._idle_since.pop(tag, None)
            return destination
        if now - self._idle_since.setdefault(tag, now) < IDLE_PATIENCE:
            return destination
        # over its base for a while and nothing to shoot: buildings only, the workers gone, or nobody there at all
        self._idle_since.pop(tag, None)
        self._dull_bases.append((destination, now + WRITE_OFF_SECONDS))
        self.roam.pop(tag, None)
        self._assign_bases(Units([unit], self.ai), ctx)
        pick = self.roam.get(tag)
        if pick is None or self._is_dull(pick) or self._is_written_off(pick, WRITE_OFF_RADIUS + 4.0):
            self.roam.pop(tag, None)
            self._recalled_until[tag] = now + RECALL_SECONDS
            return self._army_point(orders)
        return pick

    @staticmethod
    def _army_point(orders: GroupOrders) -> Point2:
        return orders.anchor if orders.anchor is not None else orders.hold_point

    def _control_unit(self, unit: Unit, orders: GroupOrders, ctx: ArmyContext) -> None:
        now = self.ai.time
        self._update_retreat(unit, orders, now)

        danger = self._in_danger(unit, ctx)
        if danger:
            # cloak first (a cloaked banshee that is not detected cannot be shot), then get out of the danger zone
            if not unit.is_cloaked and ctx.cloak_researched and CLOAK_ON in unit.abilities:
                unit(CLOAK_ON)
            if kite_away(self.ai, ctx, unit):
                return

        if unit.tag in self.retreating:
            self._idle_since.pop(unit.tag, None)
            path_move(self.ai, ctx, unit, self._repair_spot(unit, orders), grid=ctx.air_grid)
            return

        # nothing threatening and nothing to hide from: stop paying for the cloak
        if unit.is_cloaked and not danger and CLOAK_OFF in unit.abilities and not ctx.enemies_near(unit):
            unit(CLOAK_OFF)

        if unit.weapon_cooldown > 0:
            self._last_fired[unit.tag] = now
        # never shoot buildings, only units - and only units that can be shot at: not the defended ones
        targets = [
            t for t in ctx.targets_near(unit)
            if not t.is_structure and not self._is_written_off(t.position) and self._can_hit_safely(unit, t, ctx)
        ]
        if unit.tag in self.retreating or not targets:
            self._focus.pop(unit.tag, None)
        if targets:
            self._idle_since.pop(unit.tag, None)
            workers = [t for t in targets if t.type_id in ENEMY_WORKER_TYPES]
            pool = workers if workers else targets
            in_range = cy_in_attack_range(unit, pool)
            target: Unit = cy_pick_enemy_target(in_range) if in_range else cy_closest_to(unit.position, pool)
            self._check_patience(unit, target, now)
            if cy_attack_ready(self.ai, unit, target):
                attack_unit(unit, target)
                return
            # on cooldown: stay out of harm's way instead of trading (Ares StutterUnitBack = shoot when ready, else
            # step to safety), and close in when it is safe to
            if run(self.ai, StutterUnitBack(unit=unit, target=target, kite_via_pathing=True, grid=ctx.air_grid)):
                return
            attack_unit(unit, target)
            return

        path_move(self.ai, ctx, unit, self._destination(unit, orders, ctx, now), grid=ctx.air_grid)

    @staticmethod
    def _can_hit_safely(unit: Unit, target: Unit, ctx: ArmyContext) -> bool:
        """Could this banshee shoot `target` without standing inside enemy anti-air range? The spot it would shoot from is
        just inside its weapon range, on the side it comes from. A cloaked banshee - or one that can cloak the moment it
        gets into danger (see _control_unit) - is only ever in danger where a detector sees it (see _in_danger), so for it
        every target counts; a detector that keeps spotting it is what TARGET_PATIENCE is for."""
        if unit.is_cloaked and unit.energy > MIN_CLOAKED_ENERGY:
            return True
        if ctx.cloak_researched and CLOAK_ON in unit.abilities and unit.energy >= CLOAK_START_ENERGY:
            return True
        reach = max(1.0, unit.ground_range - STANDOFF_MARGIN)
        standoff = target.position.towards(unit.position, reach) if unit.distance_to(target) > reach else unit.position
        return ctx.mediator.is_position_safe(grid=ctx.air_grid, position=standoff)

    def _check_patience(self, unit: Unit, target: Unit, now: float) -> None:
        """A banshee that has been going for the same target for TARGET_PATIENCE seconds without firing once is blocked by
        something the danger grid does not show (a detector it keeps being spotted by, a defender that keeps arriving,
        terrain...): write the target - and what stands around it - off for a while, so it picks another."""
        focus = self._focus.get(unit.tag)
        if focus is None or focus[0] != target.tag:
            self._focus[unit.tag] = (target.tag, now)
            return
        fired_since = self._last_fired.get(unit.tag, -1e9) >= focus[1]
        if not fired_since and now - focus[1] > TARGET_PATIENCE:
            self._written_off.append((target.position, now + WRITE_OFF_SECONDS))
            self._focus.pop(unit.tag, None)

    @staticmethod
    def _in_danger(unit: Unit, ctx: ArmyContext) -> bool:
        if ctx.is_safe(unit):
            return False
        if unit.is_cloaked and unit.energy > MIN_CLOAKED_ENERGY:
            # invisible to everything except detectors: only in danger if one of them is actually looking at us
            return bool(ctx.mediator.get_is_detected(unit=unit, by_enemy=True))
        return True
