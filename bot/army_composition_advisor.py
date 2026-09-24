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
DANGEROUS_STRUCTURE_THREAT = 5

# how much extra effective HP each point of armor is worth, as a flat fraction
ARMOR_EHP_BONUS = 0.05

# total_enemy_power fades a sighting's weight the longer it's gone unconfirmed
POWER_CONFIDENCE_FULL_WINDOW = 60.0
POWER_CONFIDENCE_TAPER = 180.0
POWER_CONFIDENCE_FLOOR = 0.3

# Combat simulator settings.
#
# predict_engage() is expensive, so don't run it every frame.
# The army composition signature also invalidates the cache when units
# are added/removed/type-changed.
#
# 0.5 seconds = approximately 11 SC2 game loops at normal speed.
# Increase to 1.0 if you want even fewer simulations.
COMBAT_SIM_INTERVAL = 0.5


# So far, all this does is track enemy army.
#
# TODO:
# Make a calculator for marine/marauder percentage, taking flying units and armored into account
# Provide advice if we should make ghosts or not
# Provide advice early against zerg if we should make helions or tanks
# Provide advice for combat positioning before fighting, and micro settings


class ArmyCompositionAdvisor():

    def __init__(self, bot: BotAI):

        self.bot = bot

        # keep track of alive enemy units, even if they burrowed or left vision
        self.known_enemy_units = dict()

        # max health/shield for each enemy unit type we've actually seen alive at least once
        self.enemy_type_stats: Dict[UnitTypeId, Tuple[float, float]] = {}

        # make more marines if enemy has light or flying units
        self.marine_marauder_ratio = 0.5

        # indicators depending on enemy units
        self.max_tanks = 10
        self.max_cyclones = 0
        self.max_hellions = 6
        self.max_ravens = 2
        self.max_medivacs = 4
        self.max_vikings = 4
        self.max_liberators = 0
        self.max_battlecruisers = 1
        self.max_banshees = 2

        # jump Vikings to the front of Starport production
        self.prioritize_vikings = False

        # make less techlabs if we want more marines
        self.barracks_techlab_ratio = 0.5
        self.factory_techlab_ratio = 0.5
        self.starport_techlab_ratio = 0.5

        # should we attack
        self.should_attack = False

        # enemies are close enough to our own structures that we must respond
        self.defending = False

        # track resources lost by each player
        self.resources_lost = 0
        self.enemy_resources_lost = 0

        # useful infos
        self.zergling_rushed = False

        # cache static DPS/armor information
        self._dps_armor_cache: Dict[
            UnitTypeId,
            Tuple[float, float]
        ] = {}

        # ---------------------------------------------------------
        # Combat simulation cache
        # ---------------------------------------------------------

        # Reuse one simulator instead of constructing one every frame.
        self._combat_simulator = CombatSimulator()

        # Last cached result.
        self._cached_winnable = False

        # Time at which predict_engage() was last executed.
        self._last_combat_sim_time = -999.0

        # Signature of the armies used by the last simulation.
        self._last_combat_sim_signature = None

    # -------------------------------------------------------------
    # Combat simulation caching
    # -------------------------------------------------------------

    def _combat_army_signature(
        self,
        friendlies: Units,
        enemies: Units,
    ):
        """
        Create a cheap signature representing the composition of both armies.

        We intentionally DON'T include HP/shield here.

        HP changes almost every frame during combat. Including it would
        defeat the purpose of caching because predict_engage() would still
        run constantly.

        The signature changes when:
            - a unit enters/leaves the army
            - a unit dies
            - a new unit is produced
            - a unit changes type
        """

        friendly_signature = tuple(
            sorted(
                (unit.tag, unit.type_id.value)
                for unit in friendlies
            )
        )

        enemy_signature = tuple(
            sorted(
                (unit.tag, unit.type_id.value)
                for unit in enemies
            )
        )

        return friendly_signature, enemy_signature

    def _predict_engage_cached(
        self,
        friendlies: Units,
        enemies: Units,
    ) -> bool:
        """
        Return the cached combat result whenever possible.

        predict_engage() is only executed when:
            1. The army composition changed, OR
            2. COMBAT_SIM_INTERVAL seconds have passed.

        This prevents an expensive simulation from running every frame.
        """

        if friendlies.empty or enemies.empty:
            self._cached_winnable = False
            return False

        now = self.bot.time

        signature = self._combat_army_signature(
            friendlies,
            enemies,
        )

        composition_changed = (
            signature != self._last_combat_sim_signature
        )

        interval_elapsed = (
            now - self._last_combat_sim_time
            >= COMBAT_SIM_INTERVAL
        )

        # Only call predict_engage when necessary.
        if composition_changed or interval_elapsed:

            simulator = self._combat_simulator

            simulator.bad_micro(False)
            simulator.enable_splash(True)
            simulator.enable_timing_adjustment(True)
            simulator.enable_surround_limits(True)
            simulator.enable_melee_blocking(True)
            simulator.workers_do_no_damage(False)
            simulator.assume_reasonable_positioning(True)

            self._cached_winnable, _ = simulator.predict_engage(
                friendlies,
                enemies,
                False,
            )

            self._last_combat_sim_signature = signature
            self._last_combat_sim_time = now

        return self._cached_winnable

    def invalidate_combat_simulation(self):
        """
        Force the next provide_advices() call to run predict_engage().

        Useful if your bot has an event where you know the tactical state
        changed and don't want to wait for COMBAT_SIM_INTERVAL.
        """

        self._last_combat_sim_signature = None
        self._last_combat_sim_time = -999.0

    # -------------------------------------------------------------
    # Existing advisor logic
    # -------------------------------------------------------------

    def is_wall_closed(self):
        barrack_ok = False

        for b in self.bot.structures(UnitTypeId.BARRACKS):
            if b.position.distance_to(
                self.bot.main_base_ramp.barracks_in_middle
            ) <= 3:
                barrack_ok = True
                break

        depot_ok = False

        for d in self.bot.structures.of_type(
            {
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.SUPPLYDEPOTLOWERED
            }
        ):
            if d.position.distance_to(
                self.bot.main_base_ramp.depot_in_middle
            ) < 1:
                depot_ok = True
                break

        depot_placement_positions: FrozenSet[
            Point2
        ] = self.bot.main_base_ramp.corner_depots

        depots: Units = self.bot.structures.of_type(
            {
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.SUPPLYDEPOTLOWERED
            }
        )

        if depots:
            depot_placement_positions: Set[
                Point2
            ] = {
                d
                for d in depot_placement_positions
                if depots.closest_distance_to(d) > 1
            }

        return (
            len(depot_placement_positions) == 0
            and (barrack_ok or depot_ok)
        )

    def amount_of_enemies_of_type(
        self,
        type: UnitTypeId
    ):
        enemies = 0

        for i in self.known_enemy_units.keys():
            if self.known_enemy_units[i][1] == type:
                enemies += 1

        return enemies

    def update_enemy_army(self, enemies: Units):

        for i in enemies:

            if (
                i.tag in self.known_enemy_units
                and not i.is_visible
            ):
                continue

            if i.type_id in {
                UnitTypeId.PROBE,
                UnitTypeId.DRONE,
                UnitTypeId.SCV,
                UnitTypeId.MULE,
            }:
                continue

            self.known_enemy_units[i.tag] = (
                i.position,
                i.type_id,
                self.bot.time,
            )

            if i.type_id not in self.enemy_type_stats:
                self.enemy_type_stats[i.type_id] = (
                    i.health_max,
                    i.shield_max,
                )

        for i in self.known_enemy_units.keys():

            pos, type_id, last_seen = self.known_enemy_units[i]

            if (
                self.bot.is_visible(pos)
                and enemies.find_by_tag(i) is None
            ):
                self.known_enemy_units[i] = (
                    self.bot.enemy_start_locations[0],
                    type_id,
                    last_seen,
                )

    def remove_unit(self, tag: int):
        self.known_enemy_units.pop(tag, None)

        # Enemy composition changed.
        # Force a fresh combat simulation next time.
        self.invalidate_combat_simulation()

    def track_resource_losses(self, tag: int):
        return

    def supply_of(self, unit: UnitTypeId):

        if unit in {
            UnitTypeId.ZERGLING,
            UnitTypeId.BANELING,
        }:
            return 0.5

        if unit in {
            UnitTypeId.RAVAGER,
            UnitTypeId.LURKER,
        }:
            return 3

        if unit in {
            UnitTypeId.BROODLORD,
            UnitTypeId.ARCHON,
        }:
            return 4

        return self.bot.calculate_supply_cost(unit)

    def total_enemy_supply(self):

        total_enemy_supply = 0

        for i in self.known_enemy_units:
            _, type_id, _ = self.known_enemy_units[i]
            total_enemy_supply += self.supply_of(type_id)

        total_enemy_supply += (
            DANGEROUS_STRUCTURE_THREAT
            * self.bot.enemy_structures
                .of_type(DANGEROUS_STRUCTURES)
                .amount
        )

        return total_enemy_supply

    def _type_dps_and_armor(
        self,
        type_id: UnitTypeId
    ) -> Tuple[float, float]:

        cached = self._dps_armor_cache.get(type_id)

        if cached is not None:
            return cached

        type_data = self.bot.game_data.units.get(
            type_id.value
        )

        armor: float = (
            type_data._proto.armor
            if type_data
            else 0.0
        )

        if type_id in INFLUENCE_COSTS:

            values: Dict = INFLUENCE_COSTS[type_id]

            result = (
                values.get("GroundCost", 0)
                + values.get("AirCost", 0),
                armor,
            )

        elif type_data is None:

            result = (0.0, armor)

        else:

            weapons = type_data._proto.weapons

            ground = next(
                (
                    w for w in weapons
                    if w.type in TARGET_GROUND
                ),
                None,
            )

            air = next(
                (
                    w for w in weapons
                    if w.type in TARGET_AIR
                ),
                None,
            )

            ground_dps: float = (
                (ground.damage * ground.attacks) / ground.speed
                if ground and ground.speed
                else 0.0
            )

            air_dps: float = (
                (air.damage * air.attacks) / air.speed
                if air and air.speed
                else 0.0
            )

            result = (
                ground_dps + air_dps,
                armor,
            )

        self._dps_armor_cache[type_id] = result

        return result

    def _power(
        self,
        dps: float,
        armor: float,
        health: float,
        shield: float
    ) -> float:

        return (
            dps
            * (health + shield)
            * (1 + armor * ARMOR_EHP_BONUS)
        )

    def unit_power(self, unit: Unit) -> float:

        dps, armor = self._type_dps_and_armor(
            unit.type_id
        )

        return self._power(
            dps,
            armor,
            unit.health,
            unit.shield,
        )

    def our_army_power(self) -> float:

        return sum(
            self.unit_power(u)
            for u in self.bot.units.exclude_type(
                {
                    UnitTypeId.SCV,
                    UnitTypeId.MULE
                }
            )
        )

    @staticmethod
    def _sighting_confidence(age: float) -> float:

        if age <= POWER_CONFIDENCE_FULL_WINDOW:
            return 1.0

        taper = (
            age - POWER_CONFIDENCE_FULL_WINDOW
        ) / POWER_CONFIDENCE_TAPER

        return max(
            POWER_CONFIDENCE_FLOOR,
            1.0 - taper,
        )

    def total_enemy_power(self) -> float:

        total = 0.0

        for i in self.known_enemy_units:

            _, type_id, last_seen = (
                self.known_enemy_units[i]
            )

            stats = self.enemy_type_stats.get(
                type_id
            )

            if stats is None:
                continue

            dps, armor = self._type_dps_and_armor(
                type_id
            )

            confidence = self._sighting_confidence(
                self.bot.time - last_seen
            )

            total += (
                self._power(
                    dps,
                    armor,
                    *stats,
                )
                * confidence
            )

        for s in self.bot.enemy_structures.of_type(
            DANGEROUS_STRUCTURES
        ):
            total += self.unit_power(s)

        return total

    # -------------------------------------------------------------
    # Main advisor
    # -------------------------------------------------------------

    def provide_advices(self):

        self.update_enemy_army(
            self.bot.enemy_units
        )

        enemies: Units = self.bot.enemy_units

        friendlies: Units = (
            self.bot.units.exclude_type(
                {
                    UnitTypeId.SCV,
                    UnitTypeId.MULE
                }
            )
        )

        # ---------------------------------------------------------
        # Zergling rush
        # ---------------------------------------------------------

        if (
            self.bot.enemy_race == Race.Zerg
            and self.bot.time < 180
            and self.bot.enemy_units(
                UnitTypeId.ZERGLING
            ).amount > 0
        ):
            self.zergling_rushed = True

        elif (
            self.zergling_rushed
            and self.bot.time > 400
            and self.bot.enemy_units(
                UnitTypeId.ZERGLING
            ).closer_than(
                20,
                self.bot.start_location
            ).amount == 0
        ):
            self.zergling_rushed = False

        # ---------------------------------------------------------
        # Zerg
        # ---------------------------------------------------------

        if self.bot.enemy_race == Race.Zerg:

            if (
                self.amount_of_enemies_of_type(
                    UnitTypeId.ROACH
                )
                < len(self.known_enemy_units.keys()) / 2
            ):
                self.marine_marauder_ratio = 0.8
            else:
                self.marine_marauder_ratio = 0.5

            enemy_mech_heavy = (
                self.amount_of_enemies_of_type(
                    UnitTypeId.ULTRALISK
                )
                + self.amount_of_enemies_of_type(
                    UnitTypeId.BROODLORD
                )
                > 2
            )

            self.max_tanks = (
                12 if enemy_mech_heavy else 8
            )

            detected_anti_banshee = (
                self.amount_of_enemies_of_type(
                    UnitTypeId.OVERSEER
                ) > 0
                or self.bot.enemy_structures(
                    UnitTypeId.SPORECRAWLER
                ).amount > 0
            )

            self.max_banshees = (
                0
                if detected_anti_banshee
                else 2
            )

        # ---------------------------------------------------------
        # Protoss
        # ---------------------------------------------------------

        if self.bot.enemy_race == Race.Protoss:

            detected_skytoss = (
                self.bot.enemy_structures(
                    UnitTypeId.STARGATE
                ).amount > 0
                or any(
                    self.amount_of_enemies_of_type(t) > 0
                    for t in SKYTOSS_TYPES
                )
            )

            if detected_skytoss:

                self.marine_marauder_ratio = 0.9
                self.max_cyclones = 6
                self.max_vikings = 10
                self.prioritize_vikings = True

            else:

                self.marine_marauder_ratio = 0.5
                self.max_cyclones = 0
                self.max_vikings = 4
                self.prioritize_vikings = False

            enemy_mech_heavy = (
                self.amount_of_enemies_of_type(
                    UnitTypeId.COLOSSUS
                )
                + self.amount_of_enemies_of_type(
                    UnitTypeId.IMMORTAL
                )
                > 3
            )

            self.max_tanks = (
                10 if enemy_mech_heavy else 6
            )

            hellion_countered = any(
                self.amount_of_enemies_of_type(t) > 0
                for t in {
                    UnitTypeId.IMMORTAL,
                    UnitTypeId.COLOSSUS,
                    UnitTypeId.ARCHON,
                }
            )

            self.max_hellions = (
                0 if hellion_countered else 2
            )

            detected_anti_banshee = (
                self.amount_of_enemies_of_type(
                    UnitTypeId.PHOENIX
                ) > 0
                or self.amount_of_enemies_of_type(
                    UnitTypeId.OBSERVER
                ) > 0
                or self.bot.enemy_structures(
                    UnitTypeId.PHOTONCANNON
                ).amount > 0
            )

            self.max_banshees = (
                0
                if detected_anti_banshee
                else 2
            )

        # ---------------------------------------------------------
        # Terran
        # ---------------------------------------------------------

        if self.bot.enemy_race == Race.Terran:

            enemy_mech_heavy = (
                self.amount_of_enemies_of_type(
                    UnitTypeId.SIEGETANK
                )
                + self.amount_of_enemies_of_type(
                    UnitTypeId.CYCLONE
                )
                + self.amount_of_enemies_of_type(
                    UnitTypeId.THOR
                )
                > 4
            )

            self.max_tanks = (
                14 if enemy_mech_heavy else 8
            )

            detected_enemy_tanks = (
                self.amount_of_enemies_of_type(
                    UnitTypeId.SIEGETANK
                )
                + self.amount_of_enemies_of_type(
                    UnitTypeId.SIEGETANKSIEGED
                )
                > 0
            )

            self.max_liberators = (
                2 if detected_enemy_tanks else 0
            )

            self.max_hellions = (
                2 if enemy_mech_heavy else 6
            )

            detected_anti_banshee = (
                self.amount_of_enemies_of_type(
                    UnitTypeId.RAVEN
                ) > 0
                or self.bot.enemy_structures(
                    UnitTypeId.MISSILETURRET
                ).amount > 0
            )

            self.max_banshees = (
                0
                if detected_anti_banshee
                else 2
            )

        # ---------------------------------------------------------
        # Army power
        # ---------------------------------------------------------

        our_power = self.our_army_power()
        enemy_power = self.total_enemy_power()

        # ---------------------------------------------------------
        # Detect nearby threats
        # ---------------------------------------------------------

        self.defending = False
        nearby_enemy_power = 0.0

        if self.bot.enemy_units.amount > 0:

            for i in self.bot.structures:

                nearby_threats: Units = (
                    self.bot.enemy_units.closer_than(
                        20,
                        i,
                    )
                )

                if nearby_threats.amount > 0:

                    self.defending = True

                    local_power = sum(
                        self.unit_power(u)
                        for u in nearby_threats
                    )

                    nearby_enemy_power = max(
                        nearby_enemy_power,
                        local_power,
                    )

        # ---------------------------------------------------------
        # EXPENSIVE PART
        #
        # This is now cached.
        #
        # predict_engage() does NOT run every frame.
        # ---------------------------------------------------------

        winnable = self._predict_engage_cached(
            friendlies,
            enemies,
        )

        # ---------------------------------------------------------
        # Attack decision
        # ---------------------------------------------------------

        defending_and_winnable = (
            self.defending and winnable
        )

        fullSupply = (self.bot.supply_cap >= 200 and self.bot.supply_left <= 2)
        self.should_attack = (defending_and_winnable or winnable or fullSupply)

    # -------------------------------------------------------------
    # Startup
    # -------------------------------------------------------------

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
