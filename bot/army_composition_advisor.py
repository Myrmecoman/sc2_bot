from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2
from sc2.bot_ai import BotAI
from typing import Dict, Iterable, List, Optional, Set, FrozenSet, Tuple
from sc2.data import Race
from sc2.constants import TARGET_GROUND, TARGET_AIR
from bot.pathing.consts import DANGEROUS_STRUCTURES, SKYTOSS_TYPES
from bot.pathing.influence_costs import INFLUENCE_COSTS
from sc2_helper.combat_simulator import CombatSimulator

# rough supply-equivalent weight for each visible bunker/cannon/spine crawler/etc when sizing up
# a fight - these don't have a supply cost but are still a real reason not to walk in
DANGEROUS_STRUCTURE_THREAT = 4
# how much extra effective HP each point of armor is worth, as a flat fraction - a real per-matchup
# value would depend on the size of each incoming hit (armor matters far more against many small
# hits than one big one), which would need simulating every enemy weapon individually. This is a
# deliberately simple approximation used only to stop two units of equal HP but very different
# armor (e.g. a Zealot vs a Marine) from being scored as equally tough
ARMOR_EHP_BONUS = 0.05

# total_enemy_power (only) fades a sighting's weight the longer it's gone unconfirmed, instead of
# either counting it in full forever or dropping it entirely - we genuinely have no way to know a
# unit that left vision is dead (amount_of_enemies_of_type/total_enemy_supply are right to count
# every sighting permanently for strategic planning), but a fight decision made *right now*
# shouldn't be dominated by sightings from minutes ago either. Full weight while recent, tapering
# down to a floor that's never zero - "we saw it" always remains some evidence
POWER_CONFIDENCE_FULL_WINDOW = 60.0
POWER_CONFIDENCE_TAPER = 180.0
POWER_CONFIDENCE_FLOOR = 0.3


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

        # max health/shield for each enemy unit type we've actually seen alive at least once -
        # the API only exposes health/shield on live unit instances, not as static per-type game
        # data, so this is the only way to estimate a remembered (out-of-vision) unit's toughness.
        # Learned once per type and reused - health_max/shield_max don't change unit-to-unit
        self.enemy_type_stats: Dict[UnitTypeId, Tuple[float, float]] = {}

        # make more marines if enemy has light or flying units
        self.marine_marauder_ratio = 0.5

        # indicators depending on enemy units. If we see terran mech, make less medivacs for example
        self.max_tanks = 10
        self.max_cyclones = 0
        self.max_hellions = 6
        self.max_ravens = 2
        self.max_medivacs = 4
        self.max_vikings = 4
        self.max_liberators = 0  # Terran-only, reactive to detected enemy Siege Tanks - see provide_advices
        self.max_battlecruisers = 1
        self.max_banshees = 2
        # jump Vikings to the front of Starport production regardless of the usual Raven/BC/Medivac
        # priority - set reactively once something (skytoss, for now) makes them the actual answer
        self.prioritize_vikings = False

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

        # (dps, armor) per unit type is fixed for the whole game (upgrades aren't modeled here,
        # see _type_dps_and_armor) - cache it instead of re-deriving it for every unit, every step
        self._dps_armor_cache: Dict[UnitTypeId, Tuple[float, float]] = {}

    
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
        # a unit we've actually seen stays counted until we get positive confirmation it died
        # (remove_unit, from on_unit_destroyed) - no time-based forgetting, since a unit merely
        # being out of vision is not evidence it's gone
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
            if i.type_id not in self.enemy_type_stats:
                self.enemy_type_stats[i.type_id] = (i.health_max, i.shield_max)

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
            _, type_id, _ = self.known_enemy_units[i]
            total_enemy_supply += self.supply_of(type_id)
        # defensive structures have no supply cost but are still a real reason not to just walk in
        total_enemy_supply += DANGEROUS_STRUCTURE_THREAT * self.bot.enemy_structures.of_type(DANGEROUS_STRUCTURES).amount
        return total_enemy_supply


    def _type_dps_and_armor(self, type_id : UnitTypeId) -> Tuple[float, float]:
        """(dps, armor) for a unit TYPE from static game data rather than a live unit - so this
        also works for remembered/out-of-vision enemies, which we only have a type_id for. Prefers
        the curated INFLUENCE_COSTS table (the same one pathing's danger grid uses, already hand-
        tuned for units whose real weapon doesn't show up cleanly in the API - Bunkers, BCs, ...)
        and falls back to the API's own weapon data otherwise, replicating Unit.ground_dps/air_dps's
        formula by hand since that's a live-unit-only property and we don't have one here. Ground
        and air dps are summed rather than maxed: a dual-capable unit (Thor, Battlecruiser) really
        does threaten both lanes at once in a mixed fight, not just whichever is bigger."""
        cached = self._dps_armor_cache.get(type_id)
        if cached is not None:
            return cached

        type_data = self.bot.game_data.units.get(type_id.value)
        armor: float = type_data._proto.armor if type_data else 0.0

        if type_id in INFLUENCE_COSTS:
            # some entries (Raven, Observer, Overseer, ...) are detector-only and carry just
            # DetectionRange, no GroundCost/AirCost at all - 0 offensive dps is correct for those
            values: Dict = INFLUENCE_COSTS[type_id]
            result = (values.get("GroundCost", 0) + values.get("AirCost", 0), armor)
        elif type_data is None:
            result = (0.0, armor)
        else:
            weapons = type_data._proto.weapons
            ground = next((w for w in weapons if w.type in TARGET_GROUND), None)
            air = next((w for w in weapons if w.type in TARGET_AIR), None)
            ground_dps: float = (ground.damage * ground.attacks) / ground.speed if ground and ground.speed else 0.0
            air_dps: float = (air.damage * air.attacks) / air.speed if air and air.speed else 0.0
            result = (ground_dps + air_dps, armor)

        self._dps_armor_cache[type_id] = result
        return result


    def _power(self, dps : float, armor : float, health : float, shield : float) -> float:
        """dps * effective HP - a standard, if rough, army-strength proxy: it's what makes 20 supply
        of Siege Tanks score far higher than 20 supply of Zerglings, which raw supply couldn't tell
        apart at all."""
        return dps * (health + shield) * (1 + armor * ARMOR_EHP_BONUS)


    def unit_power(self, unit : Unit) -> float:
        """Power of a live unit (ours, or a currently-visible enemy) using its actual current
        health/shield - a half-dead unit really is weaker right now, not just when it dies."""
        dps, armor = self._type_dps_and_armor(unit.type_id)
        return self._power(dps, armor, unit.health, unit.shield)


    def our_army_power(self) -> float:
        return sum(self.unit_power(u) for u in self.bot.units.exclude_type({UnitTypeId.SCV, UnitTypeId.MULE}))


    @staticmethod
    def _sighting_confidence(age : float) -> float:
        if age <= POWER_CONFIDENCE_FULL_WINDOW:
            return 1.0
        taper = (age - POWER_CONFIDENCE_FULL_WINDOW) / POWER_CONFIDENCE_TAPER
        return max(POWER_CONFIDENCE_FLOOR, 1.0 - taper)


    def total_enemy_power(self) -> float:
        total = 0.0
        for i in self.known_enemy_units:
            _, type_id, last_seen = self.known_enemy_units[i]
            stats = self.enemy_type_stats.get(type_id)
            if stats is None:
                continue # never actually seen this type alive - no toughness estimate to use, skip rather than guess
            dps, armor = self._type_dps_and_armor(type_id)
            # a unit we've seen stays counted rather than being dropped outright (see
            # amount_of_enemies_of_type) - but its weight fades the longer it's gone unconfirmed,
            # so a fight decision isn't dominated by sightings from minutes ago. Out of vision, so
            # we also don't know its CURRENT health/shield - assume full rather than underestimate
            # a threat that's likely topped back up (shields regen fast, and SC2 units don't lose
            # HP just sitting around)
            confidence = self._sighting_confidence(self.bot.time - last_seen)
            total += self._power(dps, armor, *stats) * confidence
        # structures are visible whenever they'd actually matter to a fight, so use their real
        # current health/shield directly instead of the remembered-type-stats path
        for s in self.bot.enemy_structures.of_type(DANGEROUS_STRUCTURES):
            total += self.unit_power(s)
        return total


    def provide_advices(self):
        self.update_enemy_army(self.bot.enemy_units)
        enemies:Units = self.bot.enemy_units
        friendlies:Units = self.bot.units.exclude_type({UnitTypeId.SCV, UnitTypeId.MULE})

        # 130s was too narrow to catch anything but the very earliest pool-first timings - a
        # second CC is already up well before that, so a rush arriving any time in the first few
        # minutes (a slightly delayed timing, or just late vision on units produced earlier) was
        # sailing right past this check and never engaging the emergency-economy response at all
        if self.bot.enemy_race == Race.Zerg and self.bot.time < 180 and self.bot.enemy_units(UnitTypeId.ZERGLING).amount > 0:
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
                # Vikings are our actual hard counter here (range 9, dedicated anti-air) - the flat
                # startup default of 4 was never revised up for this matchup, and production.py
                # built them dead last regardless (after Raven/BC/Medivac) even when it was raised.
                # Both fixed together: go well past the default, and jump the production queue
                self.max_vikings = 10
                self.prioritize_vikings = True
            else:
                self.marine_marauder_ratio = 0.5
                self.max_cyclones = 0
                self.max_vikings = 4
                self.prioritize_vikings = False
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
            # Liberators specifically hunt Siege Tanks (see liberators.py) - worthless without any
            # to hunt, so gated on tanks specifically rather than the broader mech_heavy signal
            detected_enemy_tanks = (self.amount_of_enemies_of_type(UnitTypeId.SIEGETANK)
                                     + self.amount_of_enemies_of_type(UnitTypeId.SIEGETANKSIEGED)) > 0
            self.max_liberators = 2 if detected_enemy_tanks else 0
            # sieged tanks/thors shred hellions long before they're close enough to matter -
            # hellions are still a normal, good pick vs terran bio otherwise (splash vs clumped
            # marines), so this stays a reactive cut rather than a low default like vs protoss
            self.max_hellions = 2 if enemy_mech_heavy else 6
            # mirror matchup: their raven (PDD can shred banshees) or a turret up removes the
            # point of cloak the same way
            detected_anti_banshee = self.amount_of_enemies_of_type(UnitTypeId.RAVEN) > 0 or self.bot.enemy_structures(UnitTypeId.MISSILETURRET).amount > 0
            self.max_banshees = 0 if detected_anti_banshee else 2

        # supply alone can't tell a fight is worth taking - it weighs a Zergling the same as a
        # Siege Tank of equal supply cost. unit_power (dps * effective HP, see above) is what
        # actually answers "does the enemy have more AND better units than us", which raw supply
        # comparisons kept saying yes to fights that were lost on quality, not quantity
        our_power = self.our_army_power()
        enemy_power = self.total_enemy_power()

        # enemies close enough to our own structures need a response - but "respond" can't mean
        # unconditionally committing regardless of whether it's actually winnable. That's what let
        # 4 marines get thrown at 2 void rays: defending alone used to force should_attack=True
        # with no strength check at all, and void rays outrange/outrun bio in small numbers - no
        # amount of grouping fixes a fight that was never winnable to begin with. Track how much
        # is actually threatening us, not just whether anything is nearby
        self.defending = False
        nearby_enemy_power = 0.0
        if self.bot.enemy_units.amount > 0:
            for i in self.bot.structures:
                nearby_threats: Units = self.bot.enemy_units.closer_than(20, i)
                if nearby_threats.amount > 0:
                    self.defending = True
                    local_power = sum(self.unit_power(u) for u in nearby_threats)
                    nearby_enemy_power = max(nearby_enemy_power, local_power)

        # attack if we clearly outmatch the enemy's real (structure-aware) strength, or we can
        # actually beat what's threatening our structures right now (a plain power edge is enough
        # here, not the stricter bar below - losing a structure outright to inaction is usually
        # worse than a fair fight - but not unconditionally, which is the part that was broken).
        # Deliberately no "just attack once supply_army is huge" escape valve anymore - that was
        # the other half of the original problem: a big army isn't automatically a winning one,
        # and a real power edge already covers the case where it genuinely is.
        # CONTINUE/START_ATTACK_POWER_RATIO are much smaller than the old 1.5/2.5 supply-ratio
        # thresholds - those were tuned to also compensate for supply being blind to unit quality,
        # which power already accounts for directly, so keeping the old supply-scale multipliers
        # on top of a quality-aware metric compounded into a bar so high the bot stopped attacking
        # at all. Still a starting estimate, not a measured value.
        # hysteresis: use a higher bar to START attacking than to KEEP attacking, otherwise this
        # flips back and forth every step whenever our advantage hovers near the threshold.
        # keyed off army_attacking (were we ACTUALLY committed to an attack last frame), not off
        # should_attack's own previous value - should_attack can go True from defending alone (a
        # single enemy scout near a structure), which isn't a real attack commitment and shouldn't
        # earn the easier "keep attacking" bar

        simulator:CombatSimulator = CombatSimulator()
        simulator.bad_micro(False)
        simulator.enable_splash(True)
        simulator.enable_timing_adjustment(True)
        simulator.enable_surround_limits(True)
        simulator.enable_melee_blocking(True)
        simulator.workers_do_no_damage(False)
        simulator.assume_reasonable_positioning(True)

        winnable = False
        if friendlies is not None and not friendlies.empty and enemies is not None and not enemies.empty:
            winnable, _ = simulator.predict_engage(friendlies, enemies, False)

        defending_and_winnable = self.defending and winnable
        self.should_attack = defending_and_winnable or winnable
    

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

