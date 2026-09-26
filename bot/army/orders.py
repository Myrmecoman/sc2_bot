"""What a group of units has been told to do this step. Produced by the army manager, consumed by unit controllers."""
from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, Optional

from ares.consts import EngagementResult
from sc2.position import Point2
from sc2.unit import Unit


class Mode(Enum):
    ATTACK = auto()    # go to `target` and fight everything on the way
    DEFEND = auto()    # same as ATTACK but towards a threat at home (target = the threat's position)
    HOLD = auto()      # stand at the hold point (pre-positioned), fight what comes


@dataclass
class GroupOrders:
    label: str                                   # "main", "defense", "diversion", ... (debug / logging)
    mode: Mode
    target: Point2                               # where ATTACK/DEFEND march to
    hold_point: Point2                           # the army's rally / defend point
    front: Point2 = Point2((1.0, 0.0))           # unit vector from the hold point towards where the enemy comes from
    bio_position: Optional[Point2] = None        # where bio stands while HOLDing
    anchor: Optional[Point2] = None              # centre of the group's main squad - followers gravitate to it
    local_result: Optional[EngagementResult] = None   # sim result of the fight right around this group (None: no enemies near)
    # tag -> how the fight THAT unit is in looks if its side walks into the enemy (what "kite in" does): judged on the units that can
    # take part in it, cautiously, only for a fight that is under way, and no better than UNCONFIRMED_RESULT until that verdict has held
    # a while (ArmyManager._fight_view). None = the manager did not assess this group's fights: `local_result` stands in
    unit_results: Optional[Dict[int, EngagementResult]] = None
    retreating: bool = False                     # HOLD entered because a fight went badly: run for the hold point instead of kiting locally
    staging: Optional[Point2] = None             # ATTACK is currently a stop at this point (tanks siege up here) before committing
    pausing: bool = False                        # ATTACK is currently a stop at `target` to let the tail of the army catch up: hold there, do not advance or dig in
    hold_radius: float = 3.5                     # how close to its hold position a unit must be to stand still (grows with the size of the group)

    @property
    def aggressive(self) -> bool:
        return self.mode in (Mode.ATTACK, Mode.DEFEND)

    def advance_result(self, unit: Unit) -> Optional[EngagementResult]:
        """How the fight around `unit` looks if it and its side step INTO the enemy: the basis of the "kite in" decision. With per-unit
        results (the manager's), a unit that is in no fight gets none - no confidence at all - instead of the group's."""
        if self.unit_results is None:
            return self.local_result
        return self.unit_results.get(unit.tag)
