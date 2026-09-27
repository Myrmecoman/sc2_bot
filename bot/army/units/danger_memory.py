"""Where a scout or harasser (a Reaper, a raiding Cyclone) knows - or knew a moment ago - a threat to stand, even though it is out of vision
right now: it should not walk straight back into the same spot the instant its own sight of it clears. Ares remembers the exact units
involved for a while by itself (the 30 s ghost window in `enemy_units`, `FIGHT_GHOST_MAX_AGE` = 12 s where this bot decides who is in a
fight), but neither is meant for "stay off this ramp": one is short, tuned for combat decisions, not a scout's whole retreat-and-return
cycle; the other is a blanket policy for every enemy everywhere, not specific to standing at a choke point. A unit that gets shot from a
ramp, backs off, and finds nothing there a moment later (its own sight of the ramp cleared as it retreated) would otherwise go straight
back up it - and get shot again.

`ground_defenders` is what is dangerous to a ground unit right now (live, or Ares' own recent memory of it - both already sit in
`ai.enemy_units`/`enemy_structures`). `DangerMemory` remembers such a spot for longer on its own, and gives up on it the moment it can
see the spot again and finds nothing there - "the path is cleared" - or, without ever seeing that, after REMEMBER_SECONDS."""
import itertools
from typing import Iterable, List, Tuple

import numpy as np

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.army.consts import ENEMY_WORKER_TYPES

BUNKER_RANGE = 7.0                # a bunker has no weapon of its own (its marines shoot up to 6, from the bunker's edge)
DEFENDED_MARGIN = 3.0             # a spot is "defended" when something that shoots ground units reaches it with room to spare
REMEMBER_SECONDS = 45.0           # a spot not seen dangerous again in this long is forgotten even without ever seeing it empty - comfortably
                                  # longer than a scout's own retreat-heal-and-return cycle, and longer than Ares' 30 s ghost window
AVOID_EXTRA_COST = 500.0          # far more than any live threat's own dps-based grid weight (Ares): a real detour, even a long one, beats
                                  # walking back through a spot we know - or knew a moment ago - a threat to stand at. It is a weight, not a
                                  # wall: where there truly is no other way, a path is still found through it, just an expensive one


def ground_defenders(ai) -> List[Tuple[Point2, float]]:
    """Everything known to us right now (live, or Ares' own recent memory of it - `ai.enemy_units`/`enemy_structures` already carry both)
    that can shoot a ground unit: its position and how far its threat reaches (its weapon's range, both radii, and a margin) - a Bunker's
    own marines (it has no weapon of its own) counted at BUNKER_RANGE. Workers are left out on purpose: Ares' own influence grid already
    treats every one of them as a melee threat (4 more around each), which would flag every mineral line in the game as dangerous."""
    defenders: List[Tuple[Point2, float]] = []
    for e in itertools.chain(ai.enemy_units, ai.enemy_structures):
        if e.type_id in ENEMY_WORKER_TYPES or e.is_hallucination:
            continue
        reach = BUNKER_RANGE if e.type_id == U.BUNKER else (e.ground_range if e.can_attack_ground else 0.0)
        if reach > 0:
            defenders.append((e.position, reach + e.radius + DEFENDED_MARGIN))
    return defenders


class DangerMemory:
    """Ground spots worth routing around: not only what `ground_defenders` (or an equivalent) says is dangerous THIS step, but also what
    it said a moment ago and has not been seen to be clear since. `refresh` is called once a step with the current reading; `spots` and
    `avoiding_grid` are how the callers use what it remembers."""

    def __init__(self, ai):
        self.ai = ai
        self._spots: List[Tuple[Point2, float, float]] = []      # (position, reach, forget-by time)

    def refresh(self, danger_now: Iterable[Tuple[Point2, float]]) -> None:
        """`danger_now`: what is dangerous this step (from `ground_defenders`). A remembered spot not among them survives - its own
        expiry unchanged, it is not "seen again", just absent from one reading - unless we can now see the spot itself and it really is
        not there (cleared), or REMEMBER_SECONDS have passed since it was last confirmed."""
        now = self.ai.time
        danger_now = list(danger_now)
        still_there = [position for position, _ in danger_now]
        kept = [
            (position, reach, until) for position, reach, until in self._spots
            if not any(position.distance_to(p) <= 1.0 for p in still_there)
            and now < until and not self.ai.is_visible(position)
        ]
        kept.extend((position, reach, now + REMEMBER_SECONDS) for position, reach in danger_now)
        self._spots = kept

    def spots(self) -> List[Tuple[Point2, float]]:
        return [(position, reach) for position, reach, _ in self._spots]

    def avoiding_grid(self, grid: np.ndarray) -> np.ndarray:
        """`grid` (Ares' own ground/climber grid) with every remembered spot piled on heavily, in a disk the size of its own reach:
        routing around them - even a long way around - beats walking back through where we know, or very recently knew, a threat to
        stand. A copy: `grid` itself is shared with everything else this step and is never touched. The plain `grid` back, untouched,
        when nothing is remembered - the common case, and worth not paying for a copy over."""
        if not self._spots:
            return grid
        grid = grid.copy()
        for position, reach, _ in self._spots:
            x0, x1 = max(0, int(position.x - reach)), min(grid.shape[0], int(position.x + reach) + 1)
            y0, y1 = max(0, int(position.y - reach)), min(grid.shape[1], int(position.y + reach) + 1)
            if x1 > x0 and y1 > y0:
                grid[x0:x1, y0:y1] += AVOID_EXTRA_COST
        return grid
