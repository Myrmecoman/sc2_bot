import time

from collections import namedtuple, deque
from sc2.main import run_game
from sc2.data import Race, Difficulty
from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit
from sc2.units import Units
from sc2.bot_ai import BotAI
from typing import Dict, Iterable, List, Optional, Set


# same as attack, except medivacs and other non attacking units don't suicide straight in the enemy lines
def soft_attack(units : Units, unit : Unit, position_or_enemy):
    if not unit.can_attack:
        if units.not_flying.amount > 0:
            pos = units.not_flying.closest_to(position_or_enemy).position
            unit.attack(pos)
        else:
            unit.attack(position_or_enemy)
        return
    unit.attack(position_or_enemy)


# move to retreat avoiding enemies as much as possible
def smart_move(self : BotAI, unit : Unit, position):
    unit.move(position)
    # generate map of area covered by units
    self.client
    


def are_we_worker_rushed(self : BotAI):
    enemies: Units = self.enemy_units.visible.of_type({UnitTypeId.PROBE, UnitTypeId.SCV, UnitTypeId.DRONE}).sorted(lambda x: x.distance_to(self.start_location))
    dangerous_units = 0
    for e in enemies:
        if e.distance_to(self.start_location) < 8:
            dangerous_units += 1
    if enemies.empty:
        return 0, None
    return dangerous_units, enemies.first.position


def counter_worker_rush(self : BotAI):
    w, pos = are_we_worker_rushed(self)
    if w < 3 and not self.worker_rushed:
        return False

    self.worker_rushed = True
    counter = 0
    for i in self.workers:
        if i.health <= 10:
            mfs: Units = self.mineral_field.closer_than(12, self.start_location)
            if mfs:
                mf: Unit = mfs.furthest_to(i)
                i.gather(mf)
            else:
                i.move(self.mineral_field.closest_to(i))
            continue
        counter += 1
        if counter > 2 * w: # only pull twice their amount
            break
        i.attack(pos)
    if counter < 2 * w:
        for i in self.workers.idle:
            i.attack(pos)
        for i in self.workers.gathering:
            i.attack(pos)
    return True


def worker_rush_ended(self : BotAI):
    w, _ = are_we_worker_rushed(self)
    if w == 0 and self.worker_rushed:
        self.worker_rushed = False
        for i in self.workers.idle:
            mfs: Units = self.mineral_field.closer_than(10, self.townhalls.first)
            if mfs:
                mf: Unit = mfs.closest_to(i)
                i.gather(mf)


# very basic indicator
def should_we_fight(self : BotAI):
    if self.enemy_units.amount == 0:
        return False
    for i in self.structures:
        if i.position.distance_to_closest(self.enemy_units) < 18:
            return True
    return False


def are_we_idle_at_enemy_base(self):
    return self.enemy_structures.amount == 0 and self.enemy_units.amount == 0 and self.units.closest_distance_to(self.enemy_start_locations[0]) < 3


async def micro(self : BotAI):

    if counter_worker_rush(self):
        worker_rush_ended(self)
        return

    units : Units = self.units.of_type({UnitTypeId.MARINE, UnitTypeId.MARAUDER, UnitTypeId.REAPER, UnitTypeId.GHOST, UnitTypeId.HELLION, UnitTypeId.WIDOWMINE,
    UnitTypeId.WIDOWMINEBURROWED, UnitTypeId.CYCLONE, UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED, UnitTypeId.VIKINGFIGHTER, UnitTypeId.VIKINGASSAULT, UnitTypeId.LIBERATOR, UnitTypeId.MEDIVAC,
    UnitTypeId.RAVEN, UnitTypeId.BATTLECRUISER, UnitTypeId.BANSHEE})

    if len(units) == 0:
        return
    
    if are_we_idle_at_enemy_base(self):
        if len(self.scouting_units) != 0:
            return
        counter = 0
        for i in self.expansion_locations:
            if counter >= self.units.amount:
                break
            self.scouting_units.append((self.units[counter], i, False))
            self.units[counter].attack(i)
            counter += 1
        for i in range(len(self.scouting_units)):
            if self.scouting_units[i][0].distance_to(self.scouting_units[i][1]) < 1 and self.scouting_units[i][2] == False:
                self.scouting_units[i] = (self.scouting_units[i][0], self.scouting_units[i][1], True)
                self.scouting_units[i][0].attack(self.scouting_units[i][1].towards(self.game_info.map_center, -9))
        return
    
    self.scouting_units = []

    attack = False
    pos = self.townhalls.closest_to(self.game_info.map_center).position.towards(self.game_info.map_center, 10)
    enemies: Units = self.enemy_units | self.enemy_structures
    if self.supply_army >= 40 or should_we_fight(self):
        enemy_closest: Units = enemies.sorted(lambda x: x.distance_to(self.start_location))
        if enemy_closest.amount > 0:
            pos = enemy_closest[0]
        else:
            pos = self.enemy_start_locations[0]
        attack = True
    elif self.supply_army < 20 or attack == False:
        pos = self.townhalls.closest_to(self.game_info.map_center).position.towards(self.game_info.map_center, 10)

    for i in units:
        enemy_closest: Units = enemies.sorted(lambda x: x.distance_to(i.position))
        if attack:
            if i.type_id == UnitTypeId.SIEGETANK and enemy_closest.not_flying.amount > 0 and enemy_closest.not_flying.first.distance_to(i.position) <= 12:
                i(AbilityId.SIEGEMODE_SIEGEMODE)
            elif i.type_id == UnitTypeId.SIEGETANKSIEGED and (enemy_closest.not_flying.amount == 0 or enemy_closest.not_flying.first.distance_to(i.position) >= 13):
                i(AbilityId.UNSIEGE_UNSIEGE)
            elif enemy_closest.amount > 0:
                soft_attack(units, i, enemy_closest.first)
            else:
                soft_attack(units, i, pos)
        else:
            if i.type_id == UnitTypeId.SIEGETANKSIEGED and enemy_closest.not_flying.amount > 0 and enemy_closest.not_flying.first.distance_to(i.position) > 13:
                i(AbilityId.UNSIEGE_UNSIEGE)
            elif enemy_closest.amount > 0 and enemy_closest.first.distance_to(i.position) <= 6:
                soft_attack(units, i, enemy_closest.first)
            else:
                smart_move(self, i, pos)


# distribute initial workers on mineral patches
def split_workers(self) -> None:
    minerals = self.expansion_locations_dict[self.start_location].mineral_field.sorted_by_distance_to(self.start_location)
    self.close_minerals = {m.tag for m in minerals[0:4]}
    assigned: Set[int] = set()
    for i in range(self.workers.amount):
        patch = minerals[i % len(minerals)]
        if i < len(minerals):
            worker = self.workers.tags_not_in(assigned).closest_to(patch) # first, each patch gets one worker closest to it
        else:
            worker = self.workers.tags_not_in(assigned).furthest_to(patch) # the remaining workers get longer paths, this usually results in double stacking without having to spam orders
        worker.gather(patch)
        assigned.add(worker.tag)