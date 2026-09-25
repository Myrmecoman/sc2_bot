"""Ravens: Interference Matrix on the units that matter (tanks, thors, colossi, ...), Auto-Turrets when there is
nothing to matrix and energy is piling up (or against Zerg), and staying alive in between.

An Auto-Turret goes FORWARD, in front of the Raven, towards the enemy: as damage, and as something for the enemy to shoot at instead
of our army. Not under the Raven (where a turret only helps the enemy find it): about TURRET_STANDOFF from the nearest enemy, and the
Raven flies up to drop it there - as far as TURRET_MAX_ADVANCE - when that spot is safe to drop it from."""
from typing import Dict, List, Optional

from sc2.data import Race
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.army.consts import ATTACK_TARGET_IGNORE
from bot.army.context import ArmyContext
from bot.army.orders import GroupOrders
from bot.army.units.common import attack_move, follow_point, kite_away, path_move

MATRIX = AbilityId.EFFECT_INTERFERENCEMATRIX
TURRET = AbilityId.BUILDAUTOTURRET_AUTOTURRET
MATRIX_FREE_AFTER = 10.0        # a matrixed enemy is left alone this long so two ravens do not both spend one on it
ENERGY_TO_SPEND = 125           # this much energy and nothing worth matrixing -> spend it on turrets instead of hoarding
TURRET_STANDOFF = 4.0           # a turret stands this far from the enemy nearest to the Raven: in its own range (6), not on top of them
TURRET_MIN_FORWARD = 2.0        # ...and always at least this far in front of the Raven that drops it (never under it)
TURRET_MAX_ADVANCE = 6.0        # the Raven flies at most this far towards the enemy to drop one
TURRET_SPOT_SEARCH = 2          # look this many cells around the ideal spot for one a turret can stand on
TURRET_CAST_MARGIN = 0.25       # the Raven drops it from this much inside its cast range
TURRET_TRIGGER_RANGE = 10.0     # only bother when the closest enemy is this near
TURRET_PLACEMENT_CANDIDATES = 4 # ask the game about this many of the nearest candidate cells (each is an API query)

MATRIX_TARGETS_BY_RACE = {
    Race.Terran: [UnitTypeId.SIEGETANKSIEGED, UnitTypeId.THOR, UnitTypeId.BATTLECRUISER],
    Race.Protoss: [UnitTypeId.COLOSSUS, UnitTypeId.CARRIER, UnitTypeId.ARCHON, UnitTypeId.IMMORTAL, UnitTypeId.WARPPRISM],
}


class RavenController:
    def __init__(self, ai):
        self.ai = ai
        self.matrices: Dict[int, float] = {}   # enemy tag -> time we matrixed it, so ravens don't stack on one target
        self.matrix_range: float = ai.game_data.abilities[MATRIX.value]._proto.cast_range
        self.turret_range: float = ai.game_data.abilities[TURRET.value]._proto.cast_range

    async def control(self, units: Units, orders: GroupOrders, ctx: ArmyContext) -> None:
        now = self.ai.time
        for tag in [t for t, cast_at in self.matrices.items() if now - cast_at > MATRIX_FREE_AFTER]:
            del self.matrices[tag]
        ctx.prefetch_near(units)
        for unit in units:
            if await self._try_cast(unit, ctx):
                continue
            # a Raven cannot fight back - never idle in a dangerous spot
            if kite_away(self.ai, ctx, unit):
                continue
            point = follow_point(orders)
            if orders.aggressive:
                attack_move(unit, point)
            elif unit.distance_to(point) > orders.hold_radius:
                path_move(self.ai, ctx, unit, point)

    # ------------------------------------------------------------------------------------------------------------
    async def _try_cast(self, unit: Unit, ctx: ArmyContext) -> bool:
        """True if this unit is busy with (or has just started) an ability and must not be given any other order."""
        # ordered to cast on a unit (order_target is that unit's tag): the game is walking it into range - hands off
        if isinstance(unit.order_target, int):
            return True
        # same for an Auto-Turret it is still approaching/placing (checked through the order's ability rather than a
        # remembered Point2: the position the game echoes back round-trips through float32, so equality is unreliable)
        if unit.is_using_ability(TURRET):
            return True

        enemies = [e for e in ctx.enemies_near(unit) if not e.is_memory and e.type_id not in ATTACK_TARGET_IGNORE]
        if not enemies:
            return False

        race = self.ai.enemy_race
        matrix_types = MATRIX_TARGETS_BY_RACE.get(race)
        if matrix_types is not None:
            if MATRIX in unit.abilities and unit.energy < ENERGY_TO_SPEND:
                # matrix only what is worth it; if nothing is, save the energy
                return self._matrix(unit, enemies, matrix_types)
            # no matrix available, or energy is piling up with nothing to matrix: turrets
            return await self._turret(unit, enemies, ctx)
        # Zerg (or unknown): turrets
        return await self._turret(unit, enemies, ctx)

    def _matrix(self, unit: Unit, enemies: List[Unit], priority_types: List[UnitTypeId]) -> bool:
        for type_id in priority_types:
            candidates = sorted(
                (e for e in enemies if e.type_id == type_id and e.tag not in self.matrices),
                key=lambda e: unit.distance_to(e),
            )
            for target in candidates:
                if unit.distance_to(target) <= unit.radius + target.radius + self.matrix_range:
                    unit(MATRIX, target)
                    self.matrices[target.tag] = self.ai.time
                    return True
        return False

    async def _turret(self, unit: Unit, enemies: List[Unit], ctx: ArmyContext) -> bool:
        if TURRET not in unit.abilities:
            return False
        closest = min(enemies, key=lambda e: unit.distance_to(e))
        gap = unit.distance_to(closest)
        if gap >= TURRET_TRIGGER_RANGE:
            return False
        spot = await self._find_turret_spot(unit, closest, gap)
        if spot is None:
            return False
        # the placement search only knows terrain/vision rules - the spot must also be inside the Raven's own cast range when the
        # order is given, or the order is silently useless and the Raven keeps re-picking it forever
        reach = unit.radius + self.turret_range
        if unit.distance_to(spot) <= reach:
            unit(TURRET, spot)
            return True
        # farther forward than a turret can be dropped from here: fly up to where it can be - if that is a safe place to be
        stand = spot.towards(unit.position, reach - TURRET_CAST_MARGIN)
        if not ctx.mediator.is_position_safe(grid=ctx.air_grid, position=stand):
            return False
        path_move(self.ai, ctx, unit, stand, grid=ctx.air_grid)
        return True

    async def _find_turret_spot(self, unit: Unit, enemy: Unit, gap: float) -> Optional[Point2]:
        """A place for a turret in front of the Raven, towards `enemy` (which is `gap` away): TURRET_STANDOFF from it, but at least
        TURRET_MIN_FORWARD and at most TURRET_MAX_ADVANCE ahead of the Raven - the nearest spot to that the game lets a turret stand on."""
        forward = min(TURRET_MAX_ADVANCE, max(TURRET_MIN_FORWARD, gap - TURRET_STANDOFF))
        ideal = unit.position.towards(enemy.position, forward)
        r = TURRET_SPOT_SEARCH
        cells = []
        for x in range(int(ideal.x) - r, int(ideal.x) + r + 1):
            for y in range(int(ideal.y) - r, int(ideal.y) + r + 1):
                pos = Point2((x, y))
                # in front of the Raven (not under it) and nearer to the enemy than it is - and a cheap static-grid filter, so that
                # only a handful of candidates ever cost an API query
                if (
                    unit.distance_to(pos) >= TURRET_MIN_FORWARD - 0.5
                    and pos.distance_to(enemy.position) < gap
                    and self.ai.in_map_bounds(pos) and self.ai.in_placement_grid(pos)
                ):
                    cells.append(pos)
        cells.sort(key=lambda p: p.distance_to(ideal))
        for pos in cells[:TURRET_PLACEMENT_CANDIDATES]:
            if await self.ai.can_place_single(UnitTypeId.AUTOTURRET, pos):
                return pos
        return None
