"""Hidden-base hunting: when we know of no enemy structure at all, fan a few fast units out to every base location we
have not seen yet.

Scouts get the SCOUTING role for the duration of the sweep, so the army manager never recalls them mid-run (the
"scouts get called straight back by the army manager" problem this replaces). They go back to the main army when the
sweep has had time to work, or the moment an enemy structure becomes known.
"""
from typing import List, Set

from ares.consts import UnitRole
from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.army.context import ArmyContext

SWEEP_COOLDOWN = 90.0          # never start a new sweep sooner than this after the last one
SWEEP_HOLD = 30.0              # how long scouts are protected from the army manager - long enough to reach and check a base
MAX_SCOUTS = 6                 # never strip more than this many units from the army for one sweep
MAX_SCOUT_FRACTION = 0.25      # ...nor more than this share of the ground army
IDLE_AT_ENEMY_BASE_MIN_TIME = 300.0   # before this, an empty-looking enemy main is almost always just "haven't looked yet"
BEHIND_BASE_OFFSET = 9.0       # scouts continue this far past a base, away from the map centre, to see its back side

# fast, expendable units make the best scouts - tanks, medivacs, liberators, ravens never do
SCOUT_TYPES = (U.HELLION, U.HELLIONTANK, U.CYCLONE, U.MARINE, U.MARAUDER, U.THOR)
_SPEED_ORDER = {t: i for i, t in enumerate(SCOUT_TYPES)}


class HiddenBaseScouting:
    def __init__(self, ai):
        self.ai = ai
        self.scout_tags: Set[int] = set()
        self.started_at: float = -1e9
        self.last_sweep: float = -1e9

    # ------------------------------------------------------------------------------------------------------------
    def should_sweep(self, ctx: ArmyContext) -> bool:
        ai = self.ai
        if ai.time - self.last_sweep < SWEEP_COOLDOWN or ai.enemy_structures:
            return False
        # trigger 1: our army stands at the enemy's start location and there is nothing there
        idle_at_enemy_base = (
            not ai.visible_enemy_units
            and ai.units
            and ai.units.closest_distance_to(ai.enemy_start_locations[0]) < 3
        )
        if idle_at_enemy_base and ai.time >= IDLE_AT_ENEMY_BASE_MIN_TIME and ai.enemy_race in {Race.Zerg, Race.Protoss}:
            return True
        # trigger 2: nothing better to spend supply on and still no idea where any enemy building is (Terran can
        # tuck a lone base away too, e.g. by flying a Command Center out)
        return ai.supply_left <= 0

    def unscouted_bases(self, ctx: ArmyContext) -> List[Point2]:
        """Base locations not currently visible, nearest to the enemy main first - that is where a hidden base is
        most likely to be. Our own bases are never worth a trip."""
        ai = self.ai
        ours = [t.position for t in ai.townhalls]
        result: List[Point2] = []
        for loc, _ in ctx.mediator.get_enemy_expansions:
            if ai.is_visible(loc) or any(loc.distance_to(o) < 8 for o in ours):
                continue
            result.append(loc)
        return result

    # ------------------------------------------------------------------------------------------------------------
    def start_sweep(self, ctx: ArmyContext, army_pool: Units) -> None:
        ai = self.ai
        bases = self.unscouted_bases(ctx)
        ground = [u for u in army_pool if u.type_id in _SPEED_ORDER and u.can_attack_ground]
        ground.sort(key=lambda u: (_SPEED_ORDER[u.type_id], u.tag))
        max_scouts = max(1, min(MAX_SCOUTS, int(len(ground) * MAX_SCOUT_FRACTION), len(bases) or MAX_SCOUTS))
        chosen = ground[:max_scouts]
        self.last_sweep = ai.time
        self.started_at = ai.time
        self.scout_tags = set()
        centre = ai.game_info.map_center
        for unit, base in zip(chosen, bases):
            ctx.mediator.assign_role(tag=unit.tag, role=UnitRole.SCOUTING)
            unit.attack(base)
            unit.attack(base.towards(centre, -BEHIND_BASE_OFFSET), queue=True)
            self.scout_tags.add(unit.tag)

        # Vikings sweep the map corners, splitting the four corners between them (lifted buildings)
        vikings = [u for u in army_pool if u.type_id == U.VIKINGFIGHTER]
        corners = getattr(ai, "map_corners", [])
        for i, viking in enumerate(vikings[:2]):
            if not corners:
                break
            ctx.mediator.assign_role(tag=viking.tag, role=UnitRole.SCOUTING)
            first = True
            for k in range(len(corners)):
                viking.attack(corners[(k + i * 2) % len(corners)], queue=not first)
                first = False
            self.scout_tags.add(viking.tag)

    # ------------------------------------------------------------------------------------------------------------
    def update(self, ctx: ArmyContext, army_pool: Units) -> None:
        """Called every step: release scouts when they are done, and start a sweep when the situation calls for one."""
        ai = self.ai
        if self.scout_tags:
            alive = {u.tag for u in ai.units}
            self.scout_tags &= alive
            done = ai.time - self.started_at >= SWEEP_HOLD or bool(ai.enemy_structures) or not self.scout_tags
            if done:
                for tag in self.scout_tags:
                    ctx.mediator.assign_role(tag=tag, role=UnitRole.ATTACKING)
                self.scout_tags = set()
            return
        if army_pool and self.should_sweep(ctx):
            self.start_sweep(ctx, army_pool)
