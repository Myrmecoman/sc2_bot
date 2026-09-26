"""Hurt mechanical units go home to be repaired, and come out again repaired - or unrepaired, when nobody repairs them.

The SCVs (bot/repair.py) only repair what stands near a base, and a unit that is off on its own gets no repair: below `below` of its health a
unit walks to the spot the SCVs can reach, waits there, and goes back to work once it is up to `resume`. If nothing happens for `patience`
seconds (no SCVs, no gas for the repair) it gives up and goes back to work as it is, and is not sent home again for `cooldown` seconds. The wait
starts over each time the repair has got the unit a little further: one SCV needs about 20 seconds to get a Banshee from 40% to 90%.

Where the spot is differs (a Banshee hovers over open ground next to a townhall - units/banshees.py - a Cyclone stands at the army's hold point),
so it is a function the owner gives. Used by the Banshees and the Cyclones."""
from typing import Callable, Dict, Set

from sc2.position import Point2
from sc2.unit import Unit

from bot.army.context import ArmyContext
from bot.army.orders import GroupOrders


class RepairRetreat:
    def __init__(
        self, ai, spot: Callable[[Unit, GroupOrders, ArmyContext], Point2], below: float = 0.4, resume: float = 0.9,
        patience: float = 25.0, cooldown: float = 60.0, wait_radius: float = 6.0,
    ):
        self.ai = ai
        self.spot = spot
        self.below, self.resume, self.patience, self.cooldown, self.wait_radius = below, resume, patience, cooldown, wait_radius
        self.retreating: Set[int] = set()                 # units on their way home, or waiting there
        self.wait_since: Dict[int, float] = {}            # unit tag -> since when it has waited at the spot without getting any better
        self.health: Dict[int, float] = {}                # unit tag -> its health when last looked at while it waited
        self.no_retreat_until: Dict[int, float] = {}      # unit tag -> it gave up waiting for a repair: not sent home before then

    def forget(self, alive: Set[int]) -> None:
        """Drop what is kept of units that are no longer there."""
        for table in (self.wait_since, self.health, self.no_retreat_until):
            for tag in [t for t in list(table) if t not in alive]:
                del table[tag]
        self.retreating &= alive

    def update(self, unit: Unit, orders: GroupOrders, ctx: ArmyContext):
        """Look at one unit. Returns where it is to go to be repaired (and stay until it is), or None when it is to carry on as it was."""
        tag = unit.tag
        now = self.ai.time
        health = unit.health_percentage
        if tag in self.retreating:
            if health >= self.resume:
                self._done(tag)
                return None
            spot = self.spot(unit, orders, ctx)
            if unit.distance_to(spot) > self.wait_radius:
                self.wait_since.pop(tag, None)                          # still on its way
                self.health.pop(tag, None)
                return spot
            since = self.wait_since.setdefault(tag, now)
            if health > self.health.get(tag, health):
                since = self.wait_since[tag] = now                       # being repaired: worth waiting for
            self.health[tag] = health
            if now - since > self.patience:
                self._done(tag)
                self.no_retreat_until[tag] = now + self.cooldown
                return None
            return spot
        if health < self.below and now >= self.no_retreat_until.get(tag, 0.0):
            self.retreating.add(tag)
            return self.spot(unit, orders, ctx)
        return None

    def _done(self, tag: int) -> None:
        self.retreating.discard(tag)
        self.wait_since.pop(tag, None)
        self.health.pop(tag, None)
