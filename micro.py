from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit
from sc2.units import Units
from sc2.bot_ai import BotAI
from sc2.position import Point2
from typing import Dict, Iterable, List, Optional, Set


# hit and run
def kite_attack(unit : Unit, enemy : Unit, unit_range):
    if unit.weapon_cooldown == 0 or unit.distance_to(enemy) > unit_range:
        unit.attack(enemy)
    else:
        unit.move(unit.position.towards(enemy, -1))


# same as attack, except medivacs and other non attacking units don't suicide straight in the enemy lines
def smart_attack(self : BotAI, units : Units, unit : Unit, position_or_enemy, enemies : Units):
    if not unit.can_attack:
        if units.not_flying.amount > 0:
            pos = units.not_flying.closest_to(position_or_enemy).position
            unit.attack(pos)
        else:
            unit.attack(position_or_enemy)
        return
    
    if unit.type_id == UnitTypeId.SIEGETANK and enemies.not_flying.amount > 0 and enemies.not_flying.closest_distance_to(unit) <= 13:
        unit(AbilityId.SIEGEMODE_SIEGEMODE)
        return
    elif unit.type_id == UnitTypeId.SIEGETANKSIEGED and (enemies.not_flying.amount == 0 or enemies.not_flying.closest_distance_to(unit) >= 14):
        unit(AbilityId.UNSIEGE_UNSIEGE)
        return
    
    dangers : Units = self.enemy_units.exclude_type({UnitTypeId.LARVA, UnitTypeId.EGG})
    # dangerous_structures = self.enemy_structures({UnitTypeId.PHOTONCANNON, UnitTypeId.BUNKER, UnitTypeId.MISSILETURRET, UnitTypeId.SPORECRAWLER, UnitTypeId.SPINECRAWLER}) # to be used later

    if unit.can_attack_both:
        if dangers.amount == 0:
            unit.attack(position_or_enemy)
            return
        closest_enemy = dangers.closest_to(unit)
        kite_attack(unit, closest_enemy, unit.ground_range)
        return
    if unit.can_attack_ground:
        if dangers.not_flying.amount == 0:
            unit.attack(position_or_enemy)
            return
        closest_enemy = dangers.not_flying.closest_to(unit)
        kite_attack(unit, closest_enemy, unit.ground_range)
        return
    if unit.can_attack_air:
        if dangers.flying.amount == 0:
            unit.attack(position_or_enemy)
            return
        closest_enemy = dangers.flying.closest_to(unit)
        kite_attack(unit, closest_enemy, unit.air_range)
        return


# move to retreat avoiding enemies as much as possible
def smart_move(self : BotAI, unit : Unit, position, enemies : Units):

    if unit.type_id == UnitTypeId.SIEGETANKSIEGED and enemies.not_flying.amount > 0 and enemies.not_flying.closest_distance_to(unit) > 13:
            unit(AbilityId.UNSIEGE_UNSIEGE)

    unit.move(position)
    # generate map of area covered by units
    # TODO


def are_we_worker_rushed(self : BotAI):

    if self.time > 300:
        return 0, None

    enemies: Units = self.enemy_units.visible.of_type({UnitTypeId.PROBE, UnitTypeId.SCV, UnitTypeId.DRONE}).sorted(lambda x: x.distance_to(self.start_location))
    
    if enemies.empty:
        return 0, None

    dangerous_units = 0
    for s in self.structures.ready:
        max_dangerous_units = 0
        for e in enemies:
            if e.distance_to(s) < 8:
                max_dangerous_units += 1
        if max_dangerous_units > dangerous_units:
            dangerous_units = max_dangerous_units
    return dangerous_units, enemies.first.position


def counter_worker_rush(self : BotAI):
    w, pos = are_we_worker_rushed(self)
    if (w < 3 and not self.worker_rushed) or w == 0:
        return False

    self.worker_rushed = True
    counter = 0
    for i in self.workers:
        if i.health <= 10 and not self.attack_with_all_worker:
            mfs: Units = self.mineral_field.closer_than(12, self.start_location)
            if mfs:
                mf: Unit = mfs.furthest_to(i)
                i.gather(mf)
            else:
                i.move(self.mineral_field.closest_to(i))
            continue
        counter += 1
        if counter > w + 2: # only pull their amount + 2
            break
        i.attack(pos)
    if counter <= w + 2:
        self.attack_with_all_worker = True
        for i in self.workers:
            i.attack(pos)
    else:
        self.attack_with_all_worker = False
    return True


def worker_rush_ended(self : BotAI):
    w, _ = are_we_worker_rushed(self)
    if w == 0 and self.worker_rushed:
        self.worker_rushed = False
        self.attack_with_all_worker = False
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
        if i.position.distance_to_closest(self.enemy_units) < 24:
            return True
    return False


def are_we_idle_at_enemy_base(self):
    return self.enemy_structures.amount == 0 and self.enemy_units.amount == 0 and self.units.closest_distance_to(self.enemy_start_locations[0]) < 3


def go_scout_bases(self : BotAI):
    if self.time - self.scouted_at_time < 90:
        return
    
    self.scouted_at_time = self.time
    counter = 0
    ground_units = self.units.filter(lambda unit: unit.can_attack_ground)
    for i in self.expansion_locations:
        if counter >= ground_units.amount:
            break
        ground_units[counter].attack(i)
        ground_units[counter].attack(i.towards(self.game_info.map_center, -9), True)
        counter += 1
    vikings = self.units.of_type({UnitTypeId.VIKINGFIGHTER})

    # kill the tanks if we can't buy vikings and produce only vikings from starports
    counter = 0
    for i in self.units.of_type({UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED}):
        marauders = self.units.of_type({UnitTypeId.MARAUDER})
        marines = self.units.of_type({UnitTypeId.MARINE})
        if marauders.amount > 0:
            marauders.random.attack(i)
        if marines.amount > 0:
            marines.random.attack(i)
    self.produce_from_factories = False
    self.produce_from_barracks = False
    
    for i in vikings.idle:
        not_first = False
        for corner in self.map_corners:
            i.attack(corner, not_first)
            not_first = True


async def micro(self : BotAI):

    if counter_worker_rush(self):
        worker_rush_ended(self)
        return

    units : Units = self.units.exclude_type({UnitTypeId.SCV, UnitTypeId.MULE})
    if len(units) == 0:
        return
    
    if are_we_idle_at_enemy_base(self):
        go_scout_bases(self)
        return
    
    self.produce_from_starports = True
    self.produce_from_factories = True
    self.produce_from_barracks = True

    attack = False
    pos = self.townhalls.closest_to(self.enemy_start_locations[0]).position.towards(self.enemy_start_locations[0], 10)
    enemies: Units = self.enemy_units | self.enemy_structures
    if self.supply_army >= 40 or should_we_fight(self):
        if enemies.amount > 0:
            pos = enemies.closest_to(self.start_location)
        else:
            pos = self.enemy_start_locations[0]
        attack = True

    for i in units:
        if attack:
            smart_attack(self, units, i, pos, enemies)
        else:
            smart_move(self, i, pos, enemies)


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