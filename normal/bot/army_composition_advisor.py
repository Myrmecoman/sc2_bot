from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2
from sc2.bot_ai import BotAI
from typing import Dict, Iterable, List, Optional, Set, FrozenSet
from sc2.data import Race
from bot.pathing.consts import DANGEROUS_STRUCTURES, SKYTOSS_TYPES

# stop counting a tracked enemy unit toward its strength once it hasn't been reconfirmed in this
# long - otherwise units from a fight (or scouting look) minutes ago inflate our estimate forever
ENEMY_MEMORY_TIMEOUT = 150.0
# rough supply-equivalent weight for each visible bunker/cannon/spine crawler/etc when sizing up
# a fight - these don't have a supply cost but are still a real reason not to walk in
DANGEROUS_STRUCTURE_THREAT = 4


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
        self.max_hellions = 6
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
        # enemies are close enough to our own structures that we must respond regardless of army cohesion
        self.defending = False

        # track ressources lost by each player (only army units) /!\ not implemented yet
        self.resources_lost = 0
        self.enemy_resources_lost = 0

        # a few usefull infos
        self.zergling_rushed = False

    
    def is_wall_closed(self):
        barrack_ok = False
        for b in self.bot.structures(UnitTypeId.BARRACKS):
            if b.position.distance_to(self.bot.main_base_ramp.barracks_in_middle) <= 3:
                barrack_ok = True
                break
        
        depot_ok = False
        for d in self.bot.structures.of_type({UnitTypeId.SUPPLYDEPOT, UnitTypeId.SUPPLYDEPOTLOWERED}):
            if d.position.distance_to(self.bot.main_base_ramp.depot_in_middle) < 1:
                depot_ok = True
                break

        depot_placement_positions: FrozenSet[Point2] = self.bot.main_base_ramp.corner_depots
        depots: Units = self.bot.structures.of_type({UnitTypeId.SUPPLYDEPOT, UnitTypeId.SUPPLYDEPOTLOWERED})
        if depots:
            depot_placement_positions: Set[Point2] = {d for d in depot_placement_positions if depots.closest_distance_to(d) > 1}
        return len(depot_placement_positions) == 0 and (barrack_ok or depot_ok)

    
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
            self.known_enemy_units[i.tag] = (i.position, i.type_id, self.bot.time)

        # update position of enemy units to default if we can see its last position but it is not there anymore
        for i in self.known_enemy_units.keys():
            pos, type_id, last_seen = self.known_enemy_units[i]
            if self.bot.is_visible(pos) and enemies.find_by_tag(i) is None:
                self.known_enemy_units[i] = (self.bot.enemy_start_locations[0], type_id, last_seen)


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
            _, type_id, last_seen = self.known_enemy_units[i]
            if self.bot.time - last_seen > ENEMY_MEMORY_TIMEOUT:
                continue # not reconfirmed in a long time - assume dead/gone rather than count it forever
            total_enemy_supply += self.supply_of(type_id)
        # defensive structures have no supply cost but are still a real reason not to just walk in
        total_enemy_supply += DANGEROUS_STRUCTURE_THREAT * self.bot.enemy_structures.of_type(DANGEROUS_STRUCTURES).amount
        return total_enemy_supply
    

    def provide_advices(self):
        self.update_enemy_army(self.bot.enemy_units)

        if self.bot.enemy_race == Race.Zerg and self.bot.time < 130 and self.bot.enemy_units(UnitTypeId.ZERGLING).amount > 0:
            self.zergling_rushed = True
        # this used to stay true for the rest of the game once set - stand down well into the
        # midgame as long as there isn't still an actual zergling threat sitting on our doorstep
        elif self.zergling_rushed and self.bot.time > 400 and self.bot.enemy_units(UnitTypeId.ZERGLING).closer_than(20, self.bot.start_location).amount == 0:
            self.zergling_rushed = False

        if self.bot.enemy_race == Race.Zerg:
            if self.amount_of_enemies_of_type(UnitTypeId.ROACH) < len(self.known_enemy_units.keys())/2:
                self.marine_marauder_ratio = 0.8
            else:
                self.marine_marauder_ratio = 0.5
            enemy_mech_heavy = self.amount_of_enemies_of_type(UnitTypeId.ULTRALISK) + self.amount_of_enemies_of_type(UnitTypeId.BROODLORD) > 2
            self.max_tanks = 12 if enemy_mech_heavy else 8
            # banshees only pay off before the enemy has a way to see or hit them - once either
            # shows up, stop investing more into a unit that's now just going to trade badly
            detected_anti_banshee = self.amount_of_enemies_of_type(UnitTypeId.OVERSEER) > 0 or self.bot.enemy_structures(UnitTypeId.SPORECRAWLER).amount > 0
            self.max_banshees = 0 if detected_anti_banshee else 2

        if self.bot.enemy_race == Race.Protoss:
            # detect "skytoss" even from units we've only ever seen once and lost vision of since
            detected_skytoss = self.bot.enemy_structures(UnitTypeId.STARGATE).amount > 0 or any(self.amount_of_enemies_of_type(t) > 0 for t in SKYTOSS_TYPES)
            if detected_skytoss:
                self.marine_marauder_ratio = 0.9
                self.max_cyclones = 6 # counters high HP armored air well with lock-on
            else:
                self.marine_marauder_ratio = 0.5
                self.max_cyclones = 0
            enemy_mech_heavy = self.amount_of_enemies_of_type(UnitTypeId.COLOSSUS) + self.amount_of_enemies_of_type(UnitTypeId.IMMORTAL) > 3
            self.max_tanks = 10 if enemy_mech_heavy else 6
            # hellions are situational vs protoss, not a default filler unit for an idle reactor
            # factory - they only pay off in a deliberate early harass window (before stalker/
            # zealot numbers build up) or vs a scouted zealot-heavy (light-tagged) composition.
            # default to just enough for that harass/scouting window, not a standing-army amount,
            # and to none at all once actually hard-countered (immortal burst, colossus range,
            # archon splash+HP all beat them outright, no amount of micro fixes that trade)
            hellion_countered = any(self.amount_of_enemies_of_type(t) > 0 for t in {UnitTypeId.IMMORTAL, UnitTypeId.COLOSSUS, UnitTypeId.ARCHON})
            self.max_hellions = 0 if hellion_countered else 2
            # phoenix hard-counters banshees outright (can't be hit back); observer/cannon just
            # remove the ambush value cloak exists for - either way, stop investing more
            detected_anti_banshee = (
                self.amount_of_enemies_of_type(UnitTypeId.PHOENIX) > 0
                or self.amount_of_enemies_of_type(UnitTypeId.OBSERVER) > 0
                or self.bot.enemy_structures(UnitTypeId.PHOTONCANNON).amount > 0
            )
            self.max_banshees = 0 if detected_anti_banshee else 2

        if self.bot.enemy_race == Race.Terran:
            enemy_mech_heavy = (self.amount_of_enemies_of_type(UnitTypeId.SIEGETANK) + self.amount_of_enemies_of_type(UnitTypeId.CYCLONE)
                                 + self.amount_of_enemies_of_type(UnitTypeId.THOR)) > 4
            self.max_tanks = 14 if enemy_mech_heavy else 8
            # sieged tanks/thors shred hellions long before they're close enough to matter -
            # hellions are still a normal, good pick vs terran bio otherwise (splash vs clumped
            # marines), so this stays a reactive cut rather than a low default like vs protoss
            self.max_hellions = 2 if enemy_mech_heavy else 6
            # mirror matchup: their raven (PDD can shred banshees) or a turret up removes the
            # point of cloak the same way
            detected_anti_banshee = self.amount_of_enemies_of_type(UnitTypeId.RAVEN) > 0 or self.bot.enemy_structures(UnitTypeId.MISSILETURRET).amount > 0
            self.max_banshees = 0 if detected_anti_banshee else 2

        total_enemy_supply = self.total_enemy_supply()

        # enemies close enough to our own structures need a response - but "respond" can't mean
        # unconditionally committing regardless of whether it's actually winnable. That's what let
        # 4 marines get thrown at 2 void rays: defending alone used to force should_attack=True
        # with no strength check at all, and void rays outrange/outrun bio in small numbers - no
        # amount of grouping fixes a fight that was never winnable to begin with. Track how much
        # is actually threatening us, not just whether anything is nearby
        self.defending = False
        nearby_enemy_supply = 0.0
        if self.bot.enemy_units.amount > 0:
            for i in self.bot.structures:
                nearby_threats: Units = self.bot.enemy_units.closer_than(20, i)
                if nearby_threats.amount > 0:
                    self.defending = True
                    local_supply = sum(self.supply_of(u.type_id) for u in nearby_threats)
                    nearby_enemy_supply = max(nearby_enemy_supply, local_supply)

        # attack if we clearly outmatch the enemy's real (decayed, structure-aware) strength, we're
        # already near max supply, or we can actually beat what's threatening our structures right
        # now (a plain supply edge is enough here, not the stricter bar below - losing a structure
        # outright to inaction is usually worse than a fair fight - but not unconditionally, which
        # is the part that was broken).
        # hysteresis: use a higher bar to START attacking than to KEEP attacking, otherwise this
        # flips back and forth every step whenever our advantage hovers near the threshold.
        # keyed off army_attacking (were we ACTUALLY committed to an attack last frame), not off
        # should_attack's own previous value - should_attack can go True from defending alone (a
        # single enemy scout near a structure), which isn't a real attack commitment and shouldn't
        # earn the easier "keep attacking" bar
        defending_and_winnable = self.defending and self.bot.supply_army > nearby_enemy_supply
        if self.bot.army_attacking:
            self.should_attack = defending_and_winnable or self.bot.supply_army > 1.5 * total_enemy_supply or self.bot.supply_army >= 30
        else:
            self.should_attack = defending_and_winnable or self.bot.supply_army > 2.5 * total_enemy_supply or self.bot.supply_army >= 40
    

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

