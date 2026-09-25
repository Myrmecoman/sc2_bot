"""What a group of units has been told to do this step. Produced by the army manager, consumed by unit controllers."""
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from ares.consts import EngagementResult
from sc2.position import Point2


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
    retreating: bool = False                     # HOLD entered because a fight went badly: run for the hold point instead of kiting locally
    staging: Optional[Point2] = None             # ATTACK is currently a stop at this point (tanks siege up here) before committing
    hold_radius: float = 3.5                     # how close to its hold position a unit must be to stand still (grows with the size of the group)

    @property
    def aggressive(self) -> bool:
        return self.mode in (Mode.ATTACK, Mode.DEFEND)
