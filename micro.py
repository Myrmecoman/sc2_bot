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


async def micro(self : BotAI):
    units : Units = self.units.of_type({UnitTypeId.MARINE, UnitTypeId.MARAUDER, UnitTypeId.REAPER, UnitTypeId.HELLION, UnitTypeId.SIEGETANK, UnitTypeId.MEDIVAC, UnitTypeId.RAVEN})
    if len(units) == 0:
        return
    attack = False
    pos = self.townhalls.closest_to(self.game_info.map_center).position.towards(self.game_info.map_center, 10)
    enemies: Units = self.enemy_units | self.enemy_structures
    if self.supply_army > 40:
        enemy_closest: Units = enemies.sorted(lambda x: x.distance_to(self.start_location))
        if enemy_closest.amount > 0:
            pos = enemy_closest[0]
        else:
            pos = self.enemy_start_locations[0]
        attack = True
    if self.supply_army < 20:
        pos = self.townhalls.closest_to(self.game_info.map_center).position.towards(self.game_info.map_center, 10)

    for i in units:
        if attack:
            enemy_closest: Units = enemies.sorted(lambda x: x.distance_to(i.position))
            if i.type_id == UnitTypeId.SIEGETANK and enemy_closest.amount > 0 and enemy_closest.first.distance_to(i.position) <= 12:
                i(AbilityId.SIEGEMODE_SIEGEMODE)
            elif i.type_id == UnitTypeId.SIEGETANKSIEGED:
                i(AbilityId.UNSIEGE_UNSIEGE)
            if enemy_closest.amount > 0:
                i.attack(enemy_closest.first.position)
            else:
                i.attack(pos)
        else:
            if i.type_id == UnitTypeId.SIEGETANKSIEGED:
                i(AbilityId.UNSIEGE_UNSIEGE)
            i.move(pos)
