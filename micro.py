import time
import random

from collections import namedtuple, deque
from threading import Thread
from sc2 import maps
from sc2.player import Bot, Computer
from sc2.main import run_game
from sc2.data import Race, Difficulty
from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.ids.upgrade_id import UpgradeId
from sc2.unit import Unit
from sc2.units import Units
from sc2.bot_ai import BotAI


# very basic indicator
def should_we_fight(self : BotAI):
    nb_enemies = self.enemy_units.amount
    nb_army = self.army_count
    if nb_army / (nb_enemies + 0.01) > 1.5:
        return True
    return False


# same as attack, except medivacs and other non attacking units don't suicide straight in the enemy lines
def soft_attack(units : Units, unit : Unit, position_or_enemy):
    if not unit.can_attack:
        pos = units.not_flying.closest_to(position_or_enemy).position
        unit.attack(pos)
        return
    unit.attack(position_or_enemy)


# move to retreat avoiding enemies as much as possible
def smart_move(unit : Unit, position):
    unit.move(position)


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
            mfs: Units = self.mineral_field.closer_than(10, self.townhalls.first)
            if mfs:
                mf: Unit = mfs.closest_to(i)
                i.gather(mf)
            i.move(self.mineral_field.closest_to(i.position))
            continue
        counter += 1
        if counter > 2 * w: # only pull twice their amount
            break
        i.attack(pos)
    if counter < 2 * w:
        for i in self.workers.idle:
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


async def micro(self : BotAI):

    if counter_worker_rush(self):
        worker_rush_ended(self)
        return

    units : Units = self.units.of_type({UnitTypeId.MARINE, UnitTypeId.MARAUDER, UnitTypeId.REAPER, UnitTypeId.GHOST, UnitTypeId.HELLION, UnitTypeId.WIDOWMINE,
    UnitTypeId.WIDOWMINEBURROWED, UnitTypeId.CYCLONE, UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED, UnitTypeId.VIKING, UnitTypeId.LIBERATOR, UnitTypeId.MEDIVAC,
    UnitTypeId.RAVEN, UnitTypeId.BATTLECRUISER, UnitTypeId.BANSHEE})

    if len(units) == 0:
        return

    attack = False
    pos = self.townhalls.closest_to(self.game_info.map_center).position.towards(self.game_info.map_center, 10)
    enemies: Units = self.enemy_units | self.enemy_structures
    if self.supply_army > 40 and should_we_fight(self):
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
            if i.type_id == UnitTypeId.SIEGETANK and enemy_closest.amount > 0 and enemy_closest.first.distance_to(i.position) <= 12:
                i(AbilityId.SIEGEMODE_SIEGEMODE)
            elif i.type_id == UnitTypeId.SIEGETANKSIEGED and (enemy_closest.amount == 0 or enemy_closest.first.distance_to(i.position) >= 13):
                i(AbilityId.UNSIEGE_UNSIEGE)
            elif enemy_closest.amount > 0:
                soft_attack(units, i, enemy_closest.first)
            else:
                soft_attack(units, i, pos)
        else:
            if i.type_id == UnitTypeId.SIEGETANKSIEGED and enemy_closest.amount > 0 and enemy_closest.first.distance_to(i.position) > 13:
                i(AbilityId.UNSIEGE_UNSIEGE)
            elif enemy_closest.amount > 0 and enemy_closest.first.distance_to(i.position) <= 6:
                soft_attack(units, i, enemy_closest.first)
            else:
                smart_move(i, pos)
