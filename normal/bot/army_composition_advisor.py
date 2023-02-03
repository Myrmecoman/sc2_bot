from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2
from sc2.bot_ai import BotAI
from typing import Dict, Iterable, List, Optional, Set
from sc2.data import Race


# So far, all this does is track enemy army.
#
# TODO:
# Make a calculator for marine/marauder percentage, taking flying units and armored into account
# Provide advice if we should make ghosts or not
# Provide advice early against zerg if we should make helions or tanks
# Provide advice for combat positioning before fighting, and micro settings (split against tanks but not against mass zerglings) - maybe in another class

class ArmyCompositionAdvisor():


    def __init__(self, bot : BotAI):

        # bot
        self.bot = bot

        # keep track of alive enemy units, even if they burrowed or left vision
        self.known_enemy_units = dict()

        # make more marines if enemy has light or flying units
        self.marine_marauder_ratio = 0.5

        # indicators depending on enemy units. If we see terran mech, make less medivacs for example
        self.max_tanks = 10
        self.max_cyclones = 0
        self.max_ravens = 2
        self.max_medivacs = 4
        self.max_vikings = 4
        self.max_battlecruisers = 1
        self.max_banshees = 2

        # make less techlabs if we want more marines for example /!\ not used yet
        self.barracks_techlab_ratio = 0.5
        self.factory_techlab_ratio = 0.5
        self.starport_techlab_ratio = 0.5

        # should we attack
        self.should_attack = False

        # track ressources lost by each player (only army units) /!\ not implemented yet
        self.resources_lost = 0
        self.enemy_resources_lost = 0

        # a few usefull infos
        self.zergling_rushed = False

    
    def amount_of_enemies_of_type(self, type : UnitTypeId):
        enemies = 0
        for i in self.known_enemy_units.keys():
            if self.known_enemy_units[i][1] == type:
                enemies += 1
        return enemies
    

    def update_enemy_army(self, enemies : Units):
        # update knowledge of enemy army
        for i in enemies:
            if i.tag in self.known_enemy_units and not i.is_visible:
                continue
            if i.type_id == UnitTypeId.PROBE or i.type_id == UnitTypeId.DRONE or i.type_id == UnitTypeId.SCV or i.type_id == UnitTypeId.MULE:
                continue
            self.known_enemy_units[i.tag] = (i.position, i.type_id)

        # update position of enemy units to default if we can see its last position but it is not there anymore
        for i in self.known_enemy_units.keys():
            if self.bot.is_visible(self.known_enemy_units[i][0]) and enemies.find_by_tag(i) is None:
                self.known_enemy_units[i] = (self.bot.enemy_start_locations[0], self.known_enemy_units[i][1])


    def remove_unit(self, tag : int):
        self.known_enemy_units.pop(tag, None)
    

    def track_resource_losses(self, tag : int):
        return


    def supply_of(self, unit : UnitTypeId):
        if unit == UnitTypeId.ZERGLING or unit == UnitTypeId.BANELING:
            return 0.5
        if unit == UnitTypeId.RAVAGER or unit == UnitTypeId.LURKER:
            return 3
        if unit == UnitTypeId.BROODLORD or unit == UnitTypeId.ARCHON:
            return 4
        return self.bot.calculate_supply_cost(unit)
    

    def total_enemy_supply(self):
        total_enemy_supply = 0
        for i in self.known_enemy_units:
            total_enemy_supply += self.supply_of(self.known_enemy_units[i][1])
        return total_enemy_supply
    

    def provide_advices(self):
        self.update_enemy_army(self.bot.enemy_units)

        if self.bot.enemy_race == Race.Zerg and self.bot.time < 130 and self.bot.enemy_units(UnitTypeId.ZERGLING).amount > 0:
            self.zergling_rushed = True

        if self.bot.enemy_race == Race.Zerg:
            if self.amount_of_enemies_of_type(UnitTypeId.ROACH) > len(self.known_enemy_units.keys())/2:
                self.marine_marauder_ratio = 0.5
            else:
                self.marine_marauder_ratio = 0.8
        if self.bot.enemy_race == Race.Protoss:
            if self.bot.enemy_structures(UnitTypeId.STARGATE).amount > 0 or self.bot.enemy_units.of_type({UnitTypeId.VOIDRAY, UnitTypeId.ORACLE, UnitTypeId.PHOENIX, UnitTypeId.CARRIER, UnitTypeId.TEMPEST}).amount > 0:
                self.marine_marauder_ratio = 0.9
            else:
                self.marine_marauder_ratio = 0.5

        total_enemy_supply = self.total_enemy_supply()
        if self.bot.supply_army > 4 * total_enemy_supply or self.bot.supply_army >= 50: # if we have more supply, or enough to trade, we attack
            self.should_attack = True
            return
        else:
            self.should_attack = False
        
        if self.bot.enemy_units.amount > 0: # if enemies too close from our buildings, we have to defend
            for i in self.bot.structures:
                if i.position.distance_to_closest(self.bot.enemy_units) < 20:
                    self.should_attack = True
                    return
        
        self.should_attack = False
    

    def provide_advices_startup(self):
        if self.bot.enemy_race == Race.Terran:
            self.max_medivacs = 2
            self.max_vikings = 10
            self.max_battlecruisers = 1
            self.max_ravens = 3
            self.max_tanks = 8
            self.max_cyclones = 0
            self.max_banshees = 2

            self.marine_marauder_ratio = 0.7

            self.barracks_techlab_ratio = 0.4
            self.factory_techlab_ratio = 0.5
            self.starport_techlab_ratio = 0.5
        
        if self.bot.enemy_race == Race.Protoss:
            self.max_medivacs = 4
            self.max_vikings = 4
            self.max_battlecruisers = 1
            self.max_ravens = 2
            self.max_tanks = 6
            self.max_cyclones = 0
            self.max_banshees = 2

            self.marine_marauder_ratio = 0.5

            self.barracks_techlab_ratio = 0.5
            self.factory_techlab_ratio = 0.5
            self.starport_techlab_ratio = 0.5
    
        if self.bot.enemy_race == Race.Zerg:
            self.max_medivacs = 6
            self.max_vikings = 2
            self.max_battlecruisers = 1
            self.max_ravens = 1
            self.max_tanks = 8
            self.max_cyclones = 0
            self.max_banshees = 2

            self.marine_marauder_ratio = 0.5

            self.barracks_techlab_ratio = 0.4
            self.factory_techlab_ratio = 0.5
            self.starport_techlab_ratio = 0.5

