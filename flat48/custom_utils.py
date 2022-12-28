from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.ids.upgrade_id import UpgradeId
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2, Point3
from typing import List, Tuple
from sc2.bot_ai import BotAI
import math


def can_build_structure(self : BotAI, type, fly_type, amount):
    if fly_type is not None:
        return self.structures(type).ready.amount + self.already_pending(type) + self.structures(fly_type).amount < amount and self.can_afford(type) and self.tech_requirement_progress(type) == 1
    return self.structures(type).ready.amount + self.already_pending(type) < amount and self.can_afford(type) and self.tech_requirement_progress(type) == 1


def handle_depot_status(self : BotAI):
    if self.enemy_units.amount == 0:
        for depo in self.structures(UnitTypeId.SUPPLYDEPOT).ready:
            depo(AbilityId.MORPH_SUPPLYDEPOT_LOWER)
    else:
        enemies: Units = self.enemy_units
        for depo in self.structures(UnitTypeId.SUPPLYDEPOT).ready:
            enemy_closest: Units = enemies.sorted(lambda x: x.distance_to(depo.position))
            if enemy_closest.first.distance_to(depo) >= 12:
                depo(AbilityId.MORPH_SUPPLYDEPOT_LOWER)
        for depo in self.structures(UnitTypeId.SUPPLYDEPOTLOWERED).ready:
            enemy_closest: Units = enemies.sorted(lambda x: x.distance_to(depo.position))
            if enemy_closest.first.distance_to(depo) < 12:
                depo(AbilityId.MORPH_SUPPLYDEPOT_RAISE)


HALF_OFFSET = Point2((.5, .5))
async def handle_supply(self : BotAI):

    if self.supply_cap >= 200:
        return

    if self.supply_left < 6 and self.can_afford(UnitTypeId.SUPPLYDEPOT) and self.already_pending(UnitTypeId.SUPPLYDEPOT) < 1:
        # try all ccs and find average position of its mineral fields
        for cc in self.townhalls:
            mfs: Units = self.mineral_field.closer_than(10, cc)
            if mfs.amount == 0:
                continue
            x = 0
            y = 0
            for i in mfs:
                x += i.position.x
                y += i.position.y
            x = x // mfs.amount
            y = y // mfs.amount
            # try to place at a few positions
            for i in range(20):
                position = cc.position.towards_with_random_angle(Point2((x, y)), 8, (math.pi / 3))
                position_further = cc.position.towards_with_random_angle(Point2((x, y)), 11, (math.pi / 3))
                position.rounded.offset(HALF_OFFSET)
                position_further.rounded.offset(HALF_OFFSET)
                if await self.can_place_single(UnitTypeId.SUPPLYDEPOT, position):
                    await self.build(UnitTypeId.SUPPLYDEPOT, near=position, max_distance=4)
                    return
                if await self.can_place_single(UnitTypeId.SUPPLYDEPOT, position_further):
                    await self.build(UnitTypeId.SUPPLYDEPOT, near=position_further, max_distance=4)
                    return
        print("Could not place depot")


def build_worker(self : BotAI):
    if not self.can_afford(UnitTypeId.SCV) or self.townhalls.amount == 0 or self.workers.amount > 32 or self.workers.amount >= self.townhalls.amount * 16:
        return
    for cc in self.townhalls:
        if cc.is_idle:
            cc.train(UnitTypeId.SCV)
            break
