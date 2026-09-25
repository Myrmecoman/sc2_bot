"""Ravens: Interference Matrix on the units that matter (tanks, thors, colossi, ...), Auto-Turrets when there is
nothing to matrix and energy is piling up (or against Zerg), and staying alive in between."""
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
TURRET_SEARCH_RADIUS = 3        # look this many cells around the closest enemy for a turret spot
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
            return await self._turret(unit, enemies)
        # Zerg (or unknown): turrets
        return await self._turret(unit, enemies)

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

    async def _turret(self, unit: Unit, enemies: List[Unit]) -> bool:
        if TURRET not in unit.abilities:
            return False
        closest = min(enemies, key=lambda e: unit.distance_to(e))
        if unit.distance_to(closest) >= TURRET_TRIGGER_RANGE:
            return False
        spot = await self._find_turret_spot(unit, closest)
        if spot is None:
            return False
        # the placement search only knows terrain/vision rules - the spot must also be inside the Raven's own cast
        # range, or the order is silently useless and the Raven keeps re-picking it forever
        if unit.distance_to(spot) > unit.radius + self.turret_range:
            return False
        unit(TURRET, spot)
        return True

    async def _find_turret_spot(self, unit: Unit, enemy: Unit) -> Optional[Point2]:
        r = TURRET_SEARCH_RADIUS
        cells = []
        for x in range(int(enemy.position.x) - r, int(enemy.position.x) + r + 1):
            for y in range(int(enemy.position.y) - r, int(enemy.position.y) + r + 1):
                pos = Point2((x, y))
                # cheap static-grid filter first, so only a handful of candidates ever cost an API query
                if self.ai.in_map_bounds(pos) and self.ai.in_placement_grid(pos):
                    cells.append(pos)
        cells.sort(key=lambda p: unit.distance_to(p))
        for pos in cells[:TURRET_PLACEMENT_CANDIDATES]:
            if await self.ai.can_place_single(UnitTypeId.AUTOTURRET, pos):
                return pos
        return None
