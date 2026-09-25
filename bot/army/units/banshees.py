"""Banshees: worker harassment. Each banshee roams its own enemy base (the least anti-air defended ones first), kills
workers, hits-and-runs everything else, cloaks when it is in danger, and flies home to be repaired when hurt.

A target that is DEFENDED - the spot a banshee would have to shoot it from is inside enemy anti-air range - is not a target:
without this a banshee flies in, is driven out by the danger, flies back in, ... and never fires a shot. It picks another
one, or goes on to another base."""
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
        self._focus: Dict[int, Tuple[int, float]] = {}       # banshee tag -> (target tag, since when it has been going for it)
        self._last_fired: Dict[int, float] = {}

    # ------------------------------------------------------------------------------------------------------------
    def control(self, units: Units, orders: GroupOrders, ctx: ArmyContext) -> None:
        alive = {u.tag for u in units}
        for table in (self.roam, self._focus, self._last_fired):
            for tag in [t for t in list(table) if t not in alive]:
                del table[tag]
        self.retreating &= alive
        now = self.ai.time
        self._written_off = [(p, until) for p, until in self._written_off if until > now]
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
            bases, key=lambda loc: (self._is_written_off(loc, WRITE_OFF_RADIUS + 4.0), not occupied(loc),
                                    self._danger_at(loc, ctx), order[loc])
        )

    def _is_written_off(self, position: Point2, radius: float = WRITE_OFF_RADIUS) -> bool:
        return any(p.distance_to(position) <= radius for p, _ in self._written_off)

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
            return self._danger_at(loc, ctx) < BASE_TOO_DANGEROUS and not self._is_written_off(loc, WRITE_OFF_RADIUS + 4.0)

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
    def _control_unit(self, unit: Unit, orders: GroupOrders, ctx: ArmyContext) -> None:
        health = unit.health_percentage
        if unit.tag in self.retreating:
            if health >= RESUME_ABOVE_HEALTH:
                self.retreating.discard(unit.tag)
        elif health < RETREAT_BELOW_HEALTH:
            self.retreating.add(unit.tag)

        danger = self._in_danger(unit, ctx)
        if danger:
            # cloak first (a cloaked banshee that is not detected cannot be shot), then get out of the danger zone
            if not unit.is_cloaked and ctx.cloak_researched and CLOAK_ON in unit.abilities:
                unit(CLOAK_ON)
            if kite_away(self.ai, ctx, unit):
                return

        if unit.tag in self.retreating:
            path_move(self.ai, ctx, unit, orders.hold_point, grid=ctx.air_grid)
            return

        # nothing threatening and nothing to hide from: stop paying for the cloak
        if unit.is_cloaked and not danger and CLOAK_OFF in unit.abilities and not ctx.enemies_near(unit):
            unit(CLOAK_OFF)

        now = self.ai.time
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

        destination = self.roam.get(unit.tag)
        if destination is None:
            destination = orders.target
        path_move(self.ai, ctx, unit, destination, grid=ctx.air_grid)

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
