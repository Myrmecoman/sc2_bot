"""Notices a group that has stopped getting anywhere although nothing is fighting it."""
import math
from typing import Optional

from sc2.position import Point2


class ProgressWatch:
    """A group travelling to `target` is STUCK when it has not really moved for `still_seconds`, or has not got any closer
    for `no_gain_seconds`, without fighting (a fight explains standing still) and without having arrived. In practice it
    is pressed against terrain it cannot cross, on its way to a place it cannot reach (a dead end, an island, a building
    floating over a cliff).

    Both clocks matter: a group that walks a long way round an obstacle gets no closer as the crow flies for a while, but it
    MOVES; one that is jammed against a wall may jitter, but it does not get anywhere."""

    def __init__(
        self,
        still_seconds: float = 12.0,
        no_gain_seconds: float = 45.0,
        moved: float = 4.0,
        gain: float = 5.0,
        arrival: float = 15.0,
    ):
        self.still_seconds = still_seconds
        self.no_gain_seconds = no_gain_seconds
        self.moved = moved            # a group counts as having moved once it is this far from where it last was
        self.gain = gain              # ...and as having got closer once it is this much nearer than it ever was
        self.arrival = arrival        # nearer than this, it has arrived: whatever it does now is not "stuck"
        self._target: Optional[Point2] = None
        self._ref_position: Optional[Point2] = None
        self._ref_time = 0.0
        self._best = math.inf
        self._best_time = 0.0

    def reset(self) -> None:
        self._target = None

    def _start(self, now: float, position: Point2, target: Point2) -> None:
        self._target = target
        self._ref_position, self._ref_time = position, now
        self._best, self._best_time = position.distance_to(target), now

    def stuck(self, now: float, position: Point2, target: Point2, fighting: bool) -> bool:
        if self._target is None or self._target.distance_to(target) > 5.0:
            self._start(now, position, target)          # a new destination gets a new clock
            return False
        distance = position.distance_to(target)
        if fighting or distance <= self.arrival:
            self._start(now, position, target)
            return False
        if position.distance_to(self._ref_position) > self.moved:
            self._ref_position, self._ref_time = position, now
        if distance < self._best - self.gain:
            self._best, self._best_time = distance, now
        return now - self._ref_time >= self.still_seconds or now - self._best_time >= self.no_gain_seconds
