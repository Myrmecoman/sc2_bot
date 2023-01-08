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
    if unit.weapon_cooldown == 0 or unit.distance_to(enemy) > unit_range + 1:
        unit.attack(enemy)
    else:
        unit.move(unit.position.towards(enemy, -1))


# same as attack, except medivacs and other non attacking units don't suicide straight in the enemy lines
def smart_attack(self : BotAI, units : Units, unit : Unit, position_or_enemy, enemies : Units):

    # if the position cannot be reached by ground units and we are a viking at the designated position, land
    if not self.in_pathing_grid(position_or_enemy) and isinstance(position_or_enemy, Unit) and not position_or_enemy.is_flying:
        if unit.type_id == UnitTypeId.VIKINGFIGHTER:
            if unit.position.distance_to(position_or_enemy) < 8:
                unit(AbilityId.MORPH_VIKINGASSAULTMODE)
            else:
                unit.move(position_or_enemy)
            return
    if any(enemies.flying) and unit.type_id == UnitTypeId.VIKINGASSAULT:
        unit(AbilityId.MORPH_VIKINGFIGHTERMODE)

    # handle medivacs and ravens
    if not unit.can_attack:
        if unit.type_id == UnitTypeId.MEDIVAC:
            unit(AbilityId.EFFECT_MEDIVACIGNITEAFTERBURNERS)
        if units.not_flying.amount > 0:
            pos = units.not_flying.closest_to(position_or_enemy).position
            unit.attack(pos)
        else:
            unit.attack(position_or_enemy)
        return
    
    # handle tanks
    if unit.type_id == UnitTypeId.SIEGETANK and enemies.not_flying.amount > 0 and enemies.not_flying.closest_distance_to(unit) <= 13:
        unit(AbilityId.SIEGEMODE_SIEGEMODE)
        return
    elif unit.type_id == UnitTypeId.SIEGETANKSIEGED and (enemies.not_flying.amount == 0 or enemies.not_flying.closest_distance_to(unit) >= 14):
        unit(AbilityId.UNSIEGE_UNSIEGE)
        return
    
    dangers : Units = self.enemy_units.exclude_type({UnitTypeId.LARVA, UnitTypeId.EGG})
    enemy_structures : Units = self.enemy_structures

    # everything else
    if unit.can_attack_both:
        if (dangers | enemy_structures).amount == 0:
            unit.attack(position_or_enemy)
            return
        closest_enemy = (dangers | enemy_structures).closest_to(unit)
        kite_attack(unit, closest_enemy, unit.ground_range)
        return
    if unit.can_attack_ground:
        if (dangers.not_flying | enemy_structures).amount == 0:
            unit.attack(position_or_enemy)
            return
        closest_enemy = (dangers.not_flying | enemy_structures).closest_to(unit)
        kite_attack(unit, closest_enemy, unit.ground_range)
        return
    if unit.can_attack_air:
        if (dangers.flying | enemy_structures).amount == 0:
            unit.attack(position_or_enemy)
            return
        closest_enemy = (dangers.flying | enemy_structures).closest_to(unit)
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

    enemies: Units = self.enemy_units.visible.of_type({UnitTypeId.PROBE, UnitTypeId.SCV, UnitTypeId.DRONE})
    if enemies.empty:
        return 0, None

    dangerous_units = 0
    for e in enemies:
        if e.distance_to(self.start_location) < 10:
            dangerous_units += 1
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
    
    # shift used to split vikings around
    vikings = self.units.of_type({UnitTypeId.VIKINGFIGHTER})
    shift = 0
    for i in vikings:
        not_first = False
        shift = (shift + 1) % 4
        for x in range(len(self.map_corners)):
            i.attack(self.map_corners[(x + shift) % 4], not_first)
            not_first = True


def prevent_PF_rush(self : BotAI):
    enemy_flying_structures : Units = self.enemy_structures.of_type({UnitTypeId.COMMANDCENTERFLYING})
    if enemy_flying_structures.amount == 0 or self.workers.gathering.amount == 0:
        return

    # updating all flying buildings
    for i in enemy_flying_structures:
        if not i.tag in self.worker_assigned_to_follow.keys():
            self.worker_assigned_to_follow[i.tag] = -1
    keys = [i for i in self.worker_assigned_to_follow.keys()]
    for i in keys:
        if enemy_flying_structures.find_by_tag(i) is None:
            self.worker_assigned_to_follow.pop(i)

    # if no worker assigned, give one and remember it
    for i in self.structures:
        closest_enemy_struct = enemy_flying_structures.closest_to(i)
        if closest_enemy_struct.distance_to(i) > 14:
            continue
        if self.worker_assigned_to_follow[closest_enemy_struct.tag] != -1:
            self.workers.find_by_tag(self.worker_assigned_to_follow[closest_enemy_struct.tag]).move(closest_enemy_struct.position)
            continue
        closest_worker : Unit = self.workers.gathering.closest_to(closest_enemy_struct)
        closest_worker.move(closest_enemy_struct.position)
        self.worker_assigned_to_follow[closest_enemy_struct.tag] = closest_worker.tag


def defend_building_workers(self : BotAI):
    enemy_workers = self.enemy_units.of_type({UnitTypeId.SCV, UnitTypeId.PROBE, UnitTypeId.DRONE})
    if enemy_workers.amount == 0 or self.workers.gathering.amount == 0:
        return

    # updating all threatened workers
    for i in self.workers:
        if not i.is_constructing_scv or enemy_workers.closest_distance_to(i) > 10:
            continue
        if not i.tag in self.worker_assigned_to_defend.keys() or self.workers.find_by_tag(self.worker_assigned_to_defend[i.tag]) is None:
            self.worker_assigned_to_defend[i.tag] = -1
    keys = [i for i in self.worker_assigned_to_defend.keys()]
    for i in keys:
        if self.workers.find_by_tag(i) is None or enemy_workers.closer_than(10, self.workers.find_by_tag(i)).amount > 1:
            if self.worker_assigned_to_defend[i] != -1 and self.workers.find_by_tag(self.worker_assigned_to_defend[i]) is not None:
                self.workers.find_by_tag(self.worker_assigned_to_defend[i]).move(self.townhalls.first)
            self.worker_assigned_to_defend.pop(i)
    
    # if no worker assigned, give one and remember it
    for i in self.worker_assigned_to_defend.keys():
        if self.worker_assigned_to_defend[i] != -1:
            continue
        closest_worker = self.workers.gathering.closest_to(self.workers.find_by_tag(i))
        closest_worker.attack(self.workers.find_by_tag(i).position)
        self.worker_assigned_to_defend[i] = closest_worker.tag


async def micro(self : BotAI):

    if counter_worker_rush(self):
        worker_rush_ended(self)
        return

    prevent_PF_rush(self)
    defend_building_workers(self)

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
