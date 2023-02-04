from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.ids.upgrade_id import UpgradeId
from sc2.unit import Unit
from sc2.units import Units
from sc2.bot_ai import BotAI
from sc2.position import Point2
from typing import Dict, Iterable, List, Optional, Set
from sc2.data import Race
from bot.pathing.consts import ATTACK_TARGET_IGNORE


# hit and run
def kite_attack(self : BotAI, unit : Unit, enemy : Unit, unit_range):
    dist = unit.distance_to(enemy)

    if unit.weapon_cooldown == 0 or dist > unit_range + 1:
        unit.attack(enemy)
    else:
        unit.move(unit.position.towards(enemy, -1))


# same as attack, except medivacs and other non attacking units don't suicide straight in the enemy lines
def smart_attack(self : BotAI, units : Units, unit : Unit, position_or_enemy, enemies : Units):
    dangers : Units = self.enemy_units.exclude_type(ATTACK_TARGET_IGNORE)
    enemy_structures : Units = self.enemy_structures

    # everything else
    if unit.can_attack_both:
        if (dangers | enemy_structures).amount == 0:
            unit.attack(position_or_enemy)
            return
        closest_enemy = (dangers | enemy_structures).closest_to(unit)
        kite_attack(self, unit, closest_enemy, unit.ground_range)
        return
    if unit.can_attack_ground:
        if (dangers.not_flying | enemy_structures).amount == 0:
            unit.attack(position_or_enemy)
            return
        closest_enemy = (dangers.not_flying | enemy_structures).closest_to(unit)
        kite_attack(self, unit, closest_enemy, unit.ground_range)
        return
    if unit.can_attack_air:
        if (dangers.flying | enemy_structures).amount == 0:
            unit.attack(position_or_enemy)
            return
        closest_enemy = (dangers.flying | enemy_structures).closest_to(unit)
        kite_attack(self, unit, closest_enemy, unit.air_range)
        return


def are_we_worker_rushed(self : BotAI):

    if self.time > 80:
        return 0, None

    enemies: Units = self.enemy_units.visible.of_type({UnitTypeId.PROBE, UnitTypeId.SCV, UnitTypeId.DRONE})
    if enemies.empty:
        return 0, None

    dangerous_units = 0
    for e in enemies:
        if e.distance_to(self.structures.closest_to(e)) < 10:
            dangerous_units += 1
    return dangerous_units, enemies.first.position


def counter_worker_rush(self : BotAI):
    w, pos = are_we_worker_rushed(self)
    if (w < 3 and not self.worker_rushed) or w == 0:
        return False

    mfs: Units = self.mineral_field.closer_than(12, self.start_location)
    self.worker_rushed = True
    counter = 0
    for i in self.workers:

        if i.distance_to(self.start_location) > 40 or i.weapon_cooldown > 0:
            mf: Unit = mfs.closest_to(i)
            i(AbilityId.SMART, mf)
            continue

        if i.health <= 10 and not self.attack_with_all_worker:
            mf: Unit = mfs.closest_to(i)
            i(AbilityId.SMART, mf)
            continue
        counter += 1
        if counter > w + 2: # only pull their amount + 2
            break
        i.attack(pos)
    if counter <= w + 2:
        self.attack_with_all_worker = True
        for i in self.workers:
            if i.weapon_cooldown <= 0:
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
        if enemy_flying_structures.find_by_tag(i) is None or self.workers.find_by_tag(enemy_flying_structures.find_by_tag(i)) is None:
            self.worker_assigned_to_follow.pop(i, None)

    # if no worker assigned, give one and remember it
    for i in self.structures:
        closest_enemy_struct = enemy_flying_structures.closest_to(i)
        if closest_enemy_struct.distance_to(i) > 14 or self.workers.gathering.amount == 0:
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

    # always attack with reapers and banshees
    await self.reapers.handle_attackers(self.units(UnitTypeId.REAPER))
    await self.banshees.handle_attackers(self.units(UnitTypeId.BANSHEE))

    units : Units = self.units.exclude_type({
        UnitTypeId.SCV, UnitTypeId.MULE, UnitTypeId.REAPER, UnitTypeId.MARINE, UnitTypeId.MARAUDER, UnitTypeId.MEDIVAC, UnitTypeId.RAVEN,
        UnitTypeId.VIKINGFIGHTER, UnitTypeId.BANSHEE, UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED})
    if self.army_count == 0:
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
    if self.army_advisor.should_attack == True:
        if enemies.amount > 0:
            pos = enemies.closest_to(self.start_location).position
        else:
            pos = self.enemy_start_locations[0]
        attack = True

    bio : Units = self.units.of_type({UnitTypeId.MARINE, UnitTypeId.MARAUDER})
    medivacs : Units = self.units(UnitTypeId.MEDIVAC)
    ravens : Units = self.units(UnitTypeId.RAVEN)
    flying_vikings : Units = self.units(UnitTypeId.VIKINGFIGHTER)
    tanks : Units = self.units.of_type({UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED})
    if attack:
        await self.bio.handle_attackers(bio, pos)
        await self.medivacs.handle_attackers(medivacs, pos)
        await self.ravens.handle_attackers(ravens, pos)
        await self.flying_vikings.handle_attackers(flying_vikings, pos)
        await self.tanks.handle_attackers(tanks, pos)
    else:
        await self.bio.retreat_to(bio, pos)
        await self.medivacs.retreat_to(medivacs, pos)
        await self.ravens.retreat_to(ravens, pos)
        await self.flying_vikings.retreat_to(flying_vikings, pos)
        await self.tanks.retreat_to(tanks, pos)

    for i in units:
        if attack:
            smart_attack(self, units, i, pos, enemies)
        else:
            i.move(pos)
