from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2
from typing import FrozenSet, Set
from sc2.bot_ai import BotAI


def wall_as_fast_as_possible(self: BotAI):

    if self.army_advisor.is_wall_closed():
        return

    dist = 10000
    for e in self.enemy_units:
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
    enemies: Units = self.enemy_units.of_type({UnitTypeId.PROBE, UnitTypeId.SCV, UnitTypeId.DRONE})
    if enemies.empty:
        return 0, None, 0
    
    dangerous_units = 0
    pathable_units = 0
    for e in enemies:
        if e.distance_to(self.structures.closest_to(e)) < 10:
            dangerous_units += 1
            if e.position3d.z + 0.01 < self.townhalls.first.position3d.z:
                pathable_units += 1
    return dangerous_units, enemies.first.position, dangerous_units - pathable_units


def counter_worker_rush(self : BotAI, w, pos):
    if (w < 3 and not self.worker_rushed) or w == 0:
        return False

    mfs: Units = self.mineral_field.closer_than(12, self.start_location)
    self.worker_rushed = True
    counter = 0

    for i in self.workers.sorted_by_distance_to(self.start_location):

        if i.tag in self.out_of_fight_workers or i.is_constructing_scv:
            continue

        if i.health <= 6:
            if not i.tag in self.out_of_fight_workers:
                self.out_of_fight_workers.append(i.tag)
                continue
            if i.is_carrying_minerals:
                i(AbilityId.SMART, self.townhalls.first)
            else:
                if mfs.amount > 0:
                    mf: Unit = mfs.closest_to(i)
                    i(AbilityId.SMART, mf)

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
    for i in self.workers:
        if self.enemy_units.find_by_tag(i.order_target) is not None: # if the scv is targeting an enemy unit, leave it
            mf: Unit = mfs.closest_to(i)
            i.gather(mf)


def worker_rush_defense(self : BotAI):
    w, pos, enemies_inside_wall = are_we_worker_rushed(self)
    if self.army_advisor.is_wall_closed():
        w = enemies_inside_wall
    if counter_worker_rush(self, w, pos):
        if len(self.build_order) != 0:
            self.build_order = []
    if self.worker_rushed:
        wall_as_fast_as_possible(self)
        if w == 0:
            pull_back_workers(self)
