from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2
from typing import FrozenSet, Set
from sc2.bot_ai import BotAI

WORKER_RUSH_HOME_RADIUS = 30.0    # a structure of ours is "at home" - what a worker rush is against - within this distance of one of our townhalls
WORKER_RUSH_DANGER_RADIUS = 10.0  # an enemy worker this close to one of them is a danger
WORKER_ATTACK_LEASH = 45.0        # no worker of ours is left attacking farther than this from every townhall


def wall_as_fast_as_possible(self: BotAI):

    if self.army_advisor.is_wall_closed():
        return

    dist = 10000
    for e in self.visible_enemy_units:
        new_dist = self.structures.closest_distance_to(e)
        if new_dist < dist:
            dist = new_dist
    if dist > 8:
        # at this point, we are worker rushed and the enemies got repelled. Close the wall quick with the closest non constructing SCV, check that we have a depot and the barracks
        # getting ramp wall positions
        depot_placement_positions: FrozenSet[Point2] = self.main_base_ramp.corner_depots
        depots: Units = self.structures.of_type({UnitTypeId.SUPPLYDEPOT, UnitTypeId.SUPPLYDEPOTLOWERED})
        # Filter locations close to finished supply depots
        if depots:
            depot_placement_positions: Set[Point2] = {d for d in depot_placement_positions if depots.closest_distance_to(d) > 1}
        if len(depot_placement_positions) > 0:
            for w in self.workers:
                if not w.is_constructing_scv and self.can_afford(UnitTypeId.SUPPLYDEPOT) and len(depot_placement_positions) > 0:
                    w.build(UnitTypeId.SUPPLYDEPOT, depot_placement_positions.pop())
        barracks_in_wall = False
        for b in self.structures(UnitTypeId.BARRACKS):
            if b.position == self.main_base_ramp.barracks_in_middle:
                barracks_in_wall = True
        if not barracks_in_wall:
            for w in self.workers:
                if not w.is_constructing_scv and self.can_afford(UnitTypeId.BARRACKS):
                    w.build(UnitTypeId.BARRACKS, self.main_base_ramp.barracks_in_middle)


def are_we_worker_rushed(self : BotAI):
    """(enemy workers close to our structures at home, where the closest of them is, how many of them are inside the wall, where the closest
    of THOSE is). Only structures at home count - within WORKER_RUSH_HOME_RADIUS of one of our townhalls: one of ours that stands anywhere else
    (a Raven's Auto-Turret or a bunker next to the enemy's mineral line) is not what a worker rush is against. Every enemy worker around such a
    structure used to be counted as a rushing one, and 14 of them at their own base pulled 15 of our workers across the map to attack it."""
    enemies: Units = self.visible_enemy_units.of_type({UnitTypeId.PROBE, UnitTypeId.SCV, UnitTypeId.DRONE})
    if enemies.empty:
        return 0, None, 0, None
    home: Units = self.structures.filter(lambda s: self.townhalls.closest_distance_to(s) <= WORKER_RUSH_HOME_RADIUS)
    if home.empty:
        return 0, None, 0, None

    dangerous_units = 0
    pathable_units = 0
    closest, closest_gap = None, WORKER_RUSH_DANGER_RADIUS
    closest_inside, closest_inside_gap = None, WORKER_RUSH_DANGER_RADIUS
    for e in enemies:
        gap = e.distance_to(home.closest_to(e))
        if gap < WORKER_RUSH_DANGER_RADIUS:
            dangerous_units += 1
            if gap < closest_gap:
                closest, closest_gap = e, gap
            if e.position3d.z + 0.01 < self.townhalls.first.position3d.z:
                pathable_units += 1
            elif gap < closest_inside_gap:
                closest_inside, closest_inside_gap = e, gap
    return (
        dangerous_units,
        closest.position if closest is not None else None,
        dangerous_units - pathable_units,
        closest_inside.position if closest_inside is not None else None,
    )


def counter_worker_rush(self : BotAI, w, pos):
    if (w < 3 and not self.worker_rushed) or w == 0 or pos is None:
        return False

    mfs: Units = self.mineral_field.closer_than(12, self.start_location)
    self.worker_rushed = True
    counter = 0

    for i in self.workers.sorted_by_distance_to(self.start_location):

        if i.is_constructing_scv:
            continue

        if i.health <= 6:
            if i.is_carrying_minerals:
                i(AbilityId.SMART, self.townhalls.first)
            else:
                if mfs.amount > 0:
                    mf: Unit = mfs.closest_to(i)
                    i(AbilityId.SMART, mf)
            continue

        if i.weapon_cooldown > 5: # attack again a little before we are actually a able to (quicker attacks)
            if mfs.amount > 0:
                mf: Unit = mfs.closest_to(i)
                i(AbilityId.SMART, mf)
            continue

        counter += 1
        if counter > w + 1: # only pull their amount + 1
            break
        i.attack(pos)

    return True


def pull_back_workers(self : BotAI):
    mfs: Units = self.mineral_field.closer_than(12, self.townhalls.first)
    if mfs.amount == 0:
        return
    for i in self.workers.idle:
        mf: Unit = mfs.closest_to(i)
        i.gather(mf)


def recall_far_attackers(self : BotAI):
    """A worker of ours never has any business attacking far from home: one that does (whatever sent it - a pull that chased the enemy's workers
    back to their base, ...) goes back to mining."""
    if self.mineral_field.empty:
        return
    for worker in self.workers:
        if worker.is_attacking and self.townhalls.closest_distance_to(worker) > WORKER_ATTACK_LEASH:
            worker.gather(self.mineral_field.closest_to(self.townhalls.closest_to(worker)))


WORKER_RUSH_CLEAR_DELAY = 30.0 # how long the threat must be gone before we stand down for good
def worker_rush_defense(self : BotAI):
    w, pos, enemies_inside_wall, inside_pos = are_we_worker_rushed(self)
    if self.army_advisor.is_wall_closed():
        w, pos = enemies_inside_wall, inside_pos
    if counter_worker_rush(self, w, pos):
        if len(self.build_order) != 0:
            self.build_order = []
    recall_far_attackers(self)

    if self.worker_rushed:
        # worker_rushed used to be permanent for the rest of the game once set - a single early
        # rush attempt, even a failed one, would leave pull_back_workers() overriding normal
        # worker distribution forever. Only stand down after the threat's been gone a while,
        # so we don't flip back to normal mining mid-fight if they're just regrouping.
        if w == 0:
            if self.worker_rush_clear_since is None:
                self.worker_rush_clear_since = self.time
            elif self.time - self.worker_rush_clear_since > WORKER_RUSH_CLEAR_DELAY:
                self.worker_rushed = False
                self.worker_rush_clear_since = None
        else:
            self.worker_rush_clear_since = None

    if self.worker_rushed:
        wall_as_fast_as_possible(self)
        if w == 0:
            pull_back_workers(self)
