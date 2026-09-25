"""Where the army stands and where it goes: hold/rally point, tank siege slots, attack and diversion targets."""
from typing import List, Optional, Tuple

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2
from sc2.units import Units

from bot.army.consts import (
    MAXED_SUPPLY_CAP,
    MAXED_SUPPLY_LEFT,
    STAGING_MIN_TANKS,
    STAGING_STANDOFF,
    STAGING_TRIGGER_RANGE,
)
from bot.custom_utils import get_rally_point
from bot.pathing.order_utils import plain_point

TANK_SPACING = 3.0            # lateral gap between two tanks' siege slots (splash radius) - same value the tanks were tuned with
TANK_BACK_OFFSET = 3.0        # tanks sit this far behind the hold point, on the side away from the enemy
BIO_FRONT_OFFSET = 2.0        # bio holds this far in front of the hold point, towards the enemy
APPROACH_DISTANCE = 18.0      # how far up the enemy's ground path from the hold point the "approach point" is
APPROACH_REFRESH = 20.0       # seconds between recomputing the approach path (terrain rarely changes)
DIVERSION_TARGET_SPACING = 15.0   # how far apart two locations must be to count as "different bases"
GIVE_UP_RADIUS = 12.0             # a target the army got stuck on rules out everything this close to it as well
STAGING_MAX_PULL_BACK = 8.0       # how much farther from the defense than STAGING_STANDOFF the staging point may end up, to be standable

# things a tank line should stage against: they outrange nothing a sieged tank can reach from 12.5
STAGING_STRUCTURE_TYPES = frozenset({U.PHOTONCANNON, U.SPINECRAWLER, U.PLANETARYFORTRESS, U.BUNKER})

TOWNHALL_TYPES = frozenset({
    U.COMMANDCENTER, U.COMMANDCENTERFLYING, U.ORBITALCOMMAND, U.ORBITALCOMMANDFLYING, U.PLANETARYFORTRESS,
    U.NEXUS, U.HATCHERY, U.LAIR, U.HIVE,
})


class Positioning:
    def __init__(self, ai):
        self.ai = ai
        self._approach: Optional[Point2] = None
        self._approach_for: Optional[Point2] = None
        self._approach_time: float = -1e9
        self._given_up: List[Tuple[Point2, float]] = []   # (position, until): targets the army got stuck on

    # ------------------------------------------------------------------------------------------------------------
    # hold point and its geometry
    # ------------------------------------------------------------------------------------------------------------
    def hold_point(self) -> Point2:
        """Where the army waits when it is not attacking: production rally point = the point that best defends
        our newest base (see custom_utils.get_rally_point)."""
        return get_rally_point(self.ai)

    def approach_point(self, hold_point: Point2) -> Point2:
        """A point on the enemy's most likely ground route to the hold point, `APPROACH_DISTANCE` before it -
        the direction the fight will come from. Falls back to the straight line to the enemy start."""
        now = self.ai.time
        if (
            self._approach is not None
            and self._approach_for is not None
            and self._approach_for.distance_to(hold_point) < 4.0
            and now - self._approach_time < APPROACH_REFRESH
        ):
            return self._approach
        approach: Optional[Point2] = None
        try:
            # structural path (no enemy influence) from their base to our hold point, listed enemy -> us
            path = self.ai.mediator.find_raw_path(
                start=self.ai.enemy_start_locations[0],
                target=hold_point,
                grid=self.ai.mediator.get_cached_ground_grid,
                sensitivity=6,
            )
            if path:
                for point in reversed(path):
                    if point.distance_to(hold_point) >= APPROACH_DISTANCE:
                        approach = plain_point(point)       # Ares' path cells are numpy ints
                        break
        except Exception:  # noqa: BLE001 - positioning must never take a step down; fall back to a straight line
            approach = None
        if approach is None:
            approach = hold_point.towards(self.ai.enemy_start_locations[0], APPROACH_DISTANCE)
        self._approach, self._approach_for, self._approach_time = approach, hold_point, now
        return approach

    def front_vector(self, hold_point: Point2) -> Point2:
        """Unit vector from the hold point towards where the enemy will come from."""
        toward = self.approach_point(hold_point) - hold_point
        return toward.normalized if toward.length > 0.01 else Point2((1.0, 0.0))

    def bio_position(self, hold_point: Point2) -> Point2:
        return self._pathable(hold_point + self.front_vector(hold_point) * BIO_FRONT_OFFSET, hold_point)

    def tank_slots(self, hold_point: Point2, count: int, front: Optional[Point2] = None) -> List[Point2]:
        """Siege positions in a shallow line behind the hold point, perpendicular to the approach direction:
        0, +1, -1, +2, -2 ... spacings from the centre, so the line grows outwards from the middle. `front` is the
        approach direction if the caller already has it (it is the same for every group in a step)."""
        if front is None:
            front = self.front_vector(hold_point)
        lateral = Point2((-front.y, front.x))
        base = hold_point - front * TANK_BACK_OFFSET
        slots: List[Point2] = []
        for i in range(count):
            k = ((i + 1) // 2) * (1 if i % 2 == 1 else -1)
            slots.append(self._pathable(base + lateral * (k * TANK_SPACING), hold_point))
        return slots

    def _pathable(self, position: Point2, fallback: Point2) -> Point2:
        try:
            if self.ai.in_map_bounds(position) and self.ai.in_pathing_grid(position):
                return position
        except Exception:  # noqa: BLE001
            pass
        return fallback

    # ------------------------------------------------------------------------------------------------------------
    # attack / diversion targets
    # ------------------------------------------------------------------------------------------------------------
    def give_up(self, position: Point2, seconds: float) -> None:
        """The army got stuck on its way to `position`: rule it (and whatever stands close to it) out for a while."""
        now = self.ai.time
        self._given_up = [(p, until) for p, until in self._given_up if until > now]
        self._given_up.append((position, now + seconds))

    def is_given_up(self, position: Point2) -> bool:
        return self._given_up_until(position) > self.ai.time

    def _given_up_until(self, position: Point2) -> float:
        """When the army may try `position` again (0 if it never had to give it up)."""
        return max((until for p, until in self._given_up if p.distance_to(position) <= GIVE_UP_RADIUS), default=0.0)

    def attack_target(self) -> Point2:
        """Where the main army marches: the enemy base closest to us (clear outside-in), then the closest other known
        enemy structure, then their start location (a blind guess until something has been scouted). A building that is
        flying is only chased when nothing on the ground is left - ground units cannot walk to it, and it is usually
        hovering over terrain nobody can stand on - and anything the army already got stuck on is skipped (unless
        that is everything there is: then the one it gave up on longest ago)."""
        structures: Units = self.ai.enemy_structures
        origin = self.ai.start_location
        candidates: List[Point2] = []
        if structures:
            ground = [s for s in structures if not s.is_flying] or list(structures)
            townhalls = sorted((s for s in ground if s.type_id in TOWNHALL_TYPES), key=lambda s: s.position.distance_to(origin))
            townhall_tags = {s.tag for s in townhalls}
            others = sorted((s for s in ground if s.tag not in townhall_tags), key=lambda s: s.position.distance_to(origin))
            candidates = [s.position for s in townhalls] + [s.position for s in others]
        candidates.append(self.ai.enemy_start_locations[0])
        for candidate in candidates:
            if not self.is_given_up(candidate):
                return candidate
        # everything there is has been given up: try again the one given up longest ago (each of them may have opened up)
        return min(candidates, key=self._given_up_until)

    def diversion_target(self, main_target: Point2) -> Optional[Point2]:
        """A different enemy location than wherever the main army is headed, so a small detachment can force the
        enemy to split their defense. Prefers bases we know are occupied."""
        enemy_home = self.ai.enemy_start_locations[0]
        structures: Units = self.ai.enemy_structures
        if enemy_home.distance_to(main_target) > DIVERSION_TARGET_SPACING and not self.is_given_up(enemy_home):
            # the main force is not heading home - home is probably the softer target right now
            return enemy_home
        candidates: List[Point2] = []
        for loc, _ in self.ai.mediator.get_enemy_expansions:
            if loc.distance_to(main_target) <= DIVERSION_TARGET_SPACING or self.is_given_up(loc):
                continue
            if loc.distance_to(self.ai.start_location) <= DIVERSION_TARGET_SPACING:
                continue
            if structures and structures.closer_than(12, loc):
                candidates.append(loc)
        if not candidates:
            return None
        return min(candidates, key=lambda loc: loc.distance_to(enemy_home))

    def staging_point(self, anchor: Point2, tank_count: int) -> Optional[Point2]:
        """Where to stop and dig the tanks in before committing to a fight against static defense or sieged enemy
        tanks: STAGING_STANDOFF short of the nearest one, on the side we are coming from - so our sieged tanks (range
        13) hit it while it (range 6-7) cannot hit back. None when there is nothing to stage against, we have too few
        tanks for it to matter, or the army is already that close."""
        if tank_count < STAGING_MIN_TANKS:
            return None
        ai = self.ai
        candidates = [
            s for s in ai.enemy_structures
            if s.type_id in STAGING_STRUCTURE_TYPES and s.build_progress >= 1
        ] + [
            e for e in ai.enemy_units
            if e.type_id == U.SIEGETANKSIEGED and not e.is_memory
        ]
        if not candidates:
            return None
        nearest = min(candidates, key=lambda c: c.position.distance_to(anchor))
        distance = nearest.position.distance_to(anchor)
        if distance > STAGING_TRIGGER_RANGE or distance <= STAGING_STANDOFF + 2.0:
            return None
        # the standoff point can be a spot nobody can stand on (a cliff, the far side of a wall): an army sent there walks
        # to the nearest cell it can reach and waits - so back the point off, towards us, until it is somewhere walkable
        pull_back = 0.0
        while pull_back <= STAGING_MAX_PULL_BACK:
            standoff = min(STAGING_STANDOFF + pull_back, distance - 1.0)
            point = nearest.position.towards(anchor, standoff)
            if self._walkable(point):
                return point
            pull_back += 1.0
        return None

    def _walkable(self, position: Point2) -> bool:
        try:
            return bool(self.ai.in_map_bounds(position) and self.ai.in_pathing_grid(position))
        except Exception:  # noqa: BLE001 - positioning must never take a step down
            return True

    def is_maxed(self) -> bool:
        """The kept-from-before "attack at full supply" rule."""
        return self.ai.supply_cap >= MAXED_SUPPLY_CAP and self.ai.supply_left <= MAXED_SUPPLY_LEFT
