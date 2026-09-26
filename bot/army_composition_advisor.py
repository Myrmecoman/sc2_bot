from collections import Counter
from copy import copy

from loguru import logger

from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2
from sc2.bot_ai import BotAI
from typing import Dict, FrozenSet, List, Set
from sc2.data import Race
from bot.pathing.consts import DANGEROUS_STRUCTURES, SKYTOSS_TYPES
from bot.reactions import KNOBS, REACTIONS, Scouted, react


# rough supply-equivalent weight for each visible bunker/cannon/spine crawler/etc when sizing up
# what the enemy has - these don't have a supply cost but are still a real reason not to walk in
DANGEROUS_STRUCTURE_THREAT = 5


# What to BUILD, based on what the enemy has shown us.
#
# This class decides army composition only (the max_* caps, marine/marauder split, tech-lab ratios; what the scouting calls for
# on top of the usual per-race numbers lives in reactions.py) and answers
# a few questions macro needs (is the wall closed, were we zergling-rushed, how much enemy army supply is out
# there). Everything about how the army MOVES and FIGHTS - when to push, when to hold, who defends, harass,
# scouting - lives in bot/army/ (built on the Ares library).
#
# TODO:
# Make a calculator for marine/marauder percentage, taking flying units and armored into account
# Provide advice if we should make ghosts or not
# Provide advice early against zerg if we should make helions or tanks


class ArmyCompositionAdvisor():

    def __init__(self, bot: BotAI):

        self.bot = bot

        # keep track of alive enemy units, even if they burrowed or left vision. NO time-based decay: a unit
        # we've seen is still alive until we see it die (tag -> (last known position, type, time last seen))
        self.known_enemy_units = dict()

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

        # set by the reactions to what we scouted (reactions.py): see the module docstring there
        self.raven_first = False                 # the Starport's first unit is a Raven, not a Banshee
        self.priority_units: List[UnitTypeId] = []   # money is held back for these (marines do not starve them)
        self.turrets_per_base = 0                # missile turrets in every mineral line
        self.starport_now = False                # build the Starport at once, not once a second base is up
        self.reactions_fired: Set[str] = set()   # the reactions already logged
        self.active_reactions: List[str] = []    # the reactions that applied on the last step
        self._startup: Dict[str, object] = {}    # the knobs as provide_advices_startup left them: what every step starts from
        self._startup_race = None

        # make less techlabs if we want more marines
        self.barracks_techlab_ratio = 0.5
        self.factory_techlab_ratio = 0.5
        self.starport_techlab_ratio = 0.5

        # useful infos
        self.zergling_rushed = False

    # -------------------------------------------------------------
    # Questions macro asks
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
        """`enemies` must be the enemy units visible right now (not remembered ghosts)."""

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

    # -------------------------------------------------------------
    # Main advisor
    # -------------------------------------------------------------

    def scouted(self) -> Scouted:
        """What we know of the enemy right now (see reactions.py)."""
        return Scouted(
            race=self.bot.enemy_race,
            structures=Counter(s.type_id for s in self.bot.enemy_structures),
            units=Counter(type_id for _, type_id, _ in self.known_enemy_units.values()),
        )

    def provide_advices(self):

        # a Random opponent only shows its race once we have seen a unit of theirs: start over with that race's numbers then
        if self._startup_race != self.bot.enemy_race:
            self.provide_advices_startup()
        # every step starts from the usual numbers, then the race's rules and the reactions to the scouting adjust them - so nothing
        # sticks once whatever called for it is gone
        for name, value in self._startup.items():
            setattr(self, name, copy(value))

        visible_enemies: Units = self.bot.visible_enemy_units

        self.update_enemy_army(visible_enemies)

        # ---------------------------------------------------------
        # Zergling rush
        # ---------------------------------------------------------

        if (
            self.bot.enemy_race == Race.Zerg
            and self.bot.time < 180
            and visible_enemies(
                UnitTypeId.ZERGLING
            ).amount > 0
        ):
            self.zergling_rushed = True

        elif (
            self.zergling_rushed
            and self.bot.time > 400
            and visible_enemies(
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

        self.active_reactions = react(self.scouted(), self)
        for name in self.active_reactions:
            if name not in self.reactions_fired:
                self.reactions_fired.add(name)
                reaction = next(r for r in REACTIONS if r.name == name)
                logger.info(f"[react] {name} (at {self.bot.time:.0f}s): {reaction.why}")

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

        # what every later step starts from (see provide_advices)
        self._startup_race = self.bot.enemy_race
        self._startup = {name: copy(getattr(self, name)) for name in KNOBS}
