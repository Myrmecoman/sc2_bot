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
from bot.pathing.order_utils import is_already_attacking_target, is_already_attack_moving_to, is_already_moving_to
from bot.custom_utils import get_rally_point

DIVERSION_SQUAD_SIZE = 3
DIVERSION_MIN_MAIN_ARMY = 10  # only split off a diversion if the main bio force can actually spare it
DIVERSION_TARGET_SPACING = 15 # how far apart two locations must be to count as "different bases"
WORKER_FLEE_RANGE = 7.0       # start pulling workers back before a fast threat like a reaper is already on top of them


# hit and run, but only when we actually outrange the target - otherwise backing off just
# throws away DPS uptime for nothing since the enemy can hit us anyway
def kite_attack(self : BotAI, unit : Unit, enemy : Unit, unit_range):
    dist = unit.distance_to(enemy)

    if unit.weapon_cooldown == 0 or dist > unit_range + 1:
        if not is_already_attacking_target(unit, enemy):
            unit.attack(enemy)
        return

    enemy_range = enemy.air_range if unit.is_flying else enemy.ground_range
    if 0 < enemy_range < unit_range:
        unit.move(unit.position.towards(enemy, -1))
    elif not is_already_attacking_target(unit, enemy):
        unit.attack(enemy)


# same as attack, except medivacs and other non attacking units don't suicide straight in the enemy lines
def smart_attack(self : BotAI, units : Units, unit : Unit, position_or_enemy, enemies : Units):
    dangers : Units = self.enemy_units.exclude_type(ATTACK_TARGET_IGNORE)
    enemy_structures : Units = self.enemy_structures

    # everything else
    if unit.can_attack_both:
        if (dangers | enemy_structures).amount == 0:
            if not is_already_attacking_target(unit, position_or_enemy):
                unit.attack(position_or_enemy)
            return
        closest_enemy = (dangers | enemy_structures).closest_to(unit)
        kite_attack(self, unit, closest_enemy, unit.ground_range)
        return
    if unit.can_attack_ground:
        # a ground-only unit (e.g. Hellion) can't hit a lifted structure either - exclude flying
        # structures too, not just flying units, or it'll be sent after an unreachable target
        if (dangers.not_flying | enemy_structures.not_flying).amount == 0:
            if not is_already_attacking_target(unit, position_or_enemy):
                unit.attack(position_or_enemy)
            return
        closest_enemy = (dangers.not_flying | enemy_structures.not_flying).closest_to(unit)
        kite_attack(self, unit, closest_enemy, unit.ground_range)
        return
    if unit.can_attack_air:
        if (dangers.flying | enemy_structures.flying).amount == 0:
            if not is_already_attacking_target(unit, position_or_enemy):
                unit.attack(position_or_enemy)
            return
        closest_enemy = (dangers.flying | enemy_structures.flying).closest_to(unit)
        kite_attack(self, unit, closest_enemy, unit.air_range)
        return


REGROUP_SPREAD = 8.0  # how close counts as "part of the main blob" for both checks below


# the unit with the most friendlies within spread of it - treated as the center of the main blob
def find_army_anchor(units : Units, spread: float = REGROUP_SPREAD) -> Optional[Unit]:
    if units.amount == 0:
        return None
    return max(units, key=lambda u: units.closer_than(spread, u).amount)


# is at least min_fraction of the army within spread of its main blob - used to gate committing
# to an attack until we're actually grouped up, instead of trickling in piecemeal
def army_is_grouped(units : Units, anchor: Optional[Unit], min_fraction: float = 0.75, spread: float = REGROUP_SPREAD) -> bool:
    if units.amount == 0:
        return True
    if anchor is None:
        return False
    grouped = units.closer_than(spread, anchor).amount
    return grouped / units.amount >= min_fraction


# units far from the main blob vs everyone else - used so reinforcements/stragglers rally in
# before fighting instead of trickling into an ongoing engagement one at a time, which is exactly
# what the sticky army_attacking flag would otherwise do to any unit produced mid-fight: once the
# army is committed, the cohesion check above is deliberately never re-run (see its call site) so
# a fresh unit needs its OWN check before being thrown into the fight alongside everyone else
def split_stragglers(units : Units, anchor: Optional[Unit], spread: float = REGROUP_SPREAD):
    if anchor is None or units.amount == 0:
        return units, units.tags_not_in(units.tags)
    grouped = units.closer_than(spread, anchor)
    stragglers = units.tags_not_in(grouped.tags)
    return grouped, stragglers


def get_diversion_target(self : BotAI, main_target: Point2) -> Optional[Point2]:
    """Pick a different enemy location than wherever the main army is headed, so a small
    detachment can threaten it and force the enemy to split their defense instead of
    turtling everything on the fight against our main push."""
    enemy_home = self.enemy_start_locations[0]
    if enemy_home.distance_to(main_target) > DIVERSION_TARGET_SPACING:
        # main force isn't heading home - home is probably the softer target right now
        return enemy_home
    # main force is already heading home - hit a different enemy expansion instead
    candidates = [
        loc for loc in self.expansion_locations_list
        if loc.distance_to(enemy_home) > DIVERSION_TARGET_SPACING and loc.distance_to(self.start_location) > DIVERSION_TARGET_SPACING
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda loc: loc.distance_to(enemy_home))


async def handle_diversion(self : BotAI, units : Units, target : Point2) -> None:
    """Simple, expendable attack-move for a diversion squad: get to the target and fight
    whatever's on the way, retreat only if truly in danger rather than trading forever."""
    grid = self.pathing.ground_grid
    for unit in units:
        if not self.pathing.is_position_safe(grid, unit.position):
            safe_spot: Point2 = self.pathing.find_closest_safe_spot(unit.position, grid)
            move_to: Point2 = self.pathing.find_path_next_point(unit.position, safe_spot, grid)
            unit.move(move_to)
            continue
        if not is_already_attack_moving_to(unit, target):
            unit.attack(target)


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

    # remove dead buildings or with dead SCV
    keys = [i for i in self.worker_assigned_to_follow.keys()]
    for i in keys:
        if enemy_flying_structures.find_by_tag(i) is None or self.workers.find_by_tag(enemy_flying_structures.find_by_tag(i)) is None:
            self.worker_assigned_to_follow.pop(i, None)

    # updating all flying buildings
    for i in enemy_flying_structures:
        if not i.tag in self.worker_assigned_to_follow.keys():
            self.worker_assigned_to_follow[i.tag] = -1

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


def flee_worker_threats(self : BotAI):
    """Pull workers away from an immediate combat threat (reaper/hellion harass etc.) instead of
    letting them keep mining and get picked off one by one - workers can't meaningfully fight
    back against most combat units, so self-preservation is the right reaction here, not
    continuing to work as if nothing is happening."""
    if self.worker_rushed:
        return # worker_rush_defense already has its own dedicated worker-combat logic for that case

    threats : Units = self.enemy_units.filter(lambda u: u.can_attack_ground and u.type_id not in {UnitTypeId.PROBE, UnitTypeId.SCV, UnitTypeId.DRONE})
    if threats.amount == 0:
        return

    for worker in self.workers:
        if worker.is_repairing or worker.is_constructing_scv:
            continue # already committed to a specific, actively-managed task elsewhere
        # build_order_critical_worker is deliberately NOT exempted here (only from being
        # re-picked for a DIFFERENT task, e.g. by scout() - see build_order_critical_worker's
        # other consumers) - early_build_order() runs earlier in the same step and keeps
        # re-issuing its own move order every frame regardless, so this only overrides it while
        # a real threat is within WORKER_FLEE_RANGE, and the build-order walk resumes on its own
        # the instant the worker is safe again. Exempting it from fleeing too would leave a worker
        # walking to a build site defenseless against anything that wanders close during the walk
        closest_threat = threats.closest_to(worker)
        if worker.distance_to(closest_threat) < WORKER_FLEE_RANGE:
            safe_spot: Point2 = self.townhalls.closest_to(worker).position
            if not is_already_moving_to(worker, safe_spot):
                worker.move(safe_spot)


async def micro(self : BotAI):

    prevent_PF_rush(self)
    defend_building_workers(self)
    flee_worker_threats(self)

    # always attack with reapers and banshees
    await self.reapers.handle_attackers(self.units(UnitTypeId.REAPER))
    await self.banshees.handle_attackers(self.units(UnitTypeId.BANSHEE))

    units : Units = self.units.exclude_type({
        UnitTypeId.SCV, UnitTypeId.MULE, UnitTypeId.REAPER, UnitTypeId.MARINE, UnitTypeId.MARAUDER, UnitTypeId.MEDIVAC, UnitTypeId.RAVEN,
        UnitTypeId.VIKINGFIGHTER, UnitTypeId.BANSHEE, UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED, UnitTypeId.CYCLONE})
    if self.army_count == 0:
        return

    if are_we_idle_at_enemy_base(self):
        go_scout_bases(self)
        return

    self.produce_from_starports = True
    self.produce_from_factories = True
    self.produce_from_barracks = True

    bio : Units = self.units.of_type({UnitTypeId.MARINE, UnitTypeId.MARAUDER})
    medivacs : Units = self.units(UnitTypeId.MEDIVAC)
    ravens : Units = self.units(UnitTypeId.RAVEN)
    flying_vikings : Units = self.units(UnitTypeId.VIKINGFIGHTER)
    tanks : Units = self.units.of_type({UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED})
    cyclones : Units = self.units(UnitTypeId.CYCLONE)
    ground_army : Units = bio | tanks | cyclones
    # computed once and reused for both the cohesion gate below and the straggler split further
    # down, instead of each redoing the same O(n^2) neighbor search independently
    army_anchor : Optional[Unit] = find_army_anchor(ground_army)

    attack = False
    # same forward staging point production structures rally new units to (see get_rally_point) -
    # computed once there instead of re-derived here so the two can't silently drift apart, and it
    # correctly falls back to holding at start_location while the wall isn't closed yet
    pos = get_rally_point(self)
    enemies: Units = self.enemy_units | self.enemy_structures
    if self.army_advisor.should_attack == True:
        # cohesion only gates the TRANSITION into attacking (don't trickle in piecemeal) - once
        # we're already committed, re-checking it every frame would make us retreat mid-fight the
        # moment units spread out to kite/avoid splash, which is normal fighting, not disarray
        if self.army_attacking or self.army_advisor.defending or army_is_grouped(ground_army, army_anchor):
            if enemies.amount > 0:
                pos = enemies.closest_to(self.start_location).position
            else:
                pos = self.enemy_start_locations[0]
            attack = True

    self.army_attacking = attack

    if attack:
        # even once committed, anything too far from the main blob (a unit fresh out of
        # production, a straggler) rallies in first instead of piling into the fight alone - the
        # cohesion check above only gates the transition and is deliberately never re-run once
        # army_attacking is sticky, so without this, every new unit produced mid-fight would walk
        # straight into the enemy by itself the instant it exists. This is what "fighting marine
        # by marine instead of taking winnable fights" actually was
        bio, bio_stragglers = split_stragglers(bio, army_anchor)
        tanks, tanks_stragglers = split_stragglers(tanks, army_anchor)
        cyclones, cyclones_stragglers = split_stragglers(cyclones, army_anchor)

        # split off a small detachment to threaten a different base and force the enemy to
        # split their defense, but only once the main push is big enough to spare it
        diversion_squad : Optional[Units] = None
        diversion_target : Optional[Point2] = None
        if bio.amount >= DIVERSION_MIN_MAIN_ARMY:
            diversion_target = get_diversion_target(self, pos)
            if diversion_target:
                diversion_squad = bio.take(DIVERSION_SQUAD_SIZE)
                bio = bio.tags_not_in(diversion_squad.tags)

        await self.bio.handle_attackers(bio, pos)
        await self.medivacs.handle_attackers(medivacs, pos)
        await self.ravens.handle_attackers(ravens, pos)
        await self.flying_vikings.handle_attackers(flying_vikings, pos)
        await self.tanks.handle_attackers(tanks, pos)
        await self.cyclones.handle_attackers(cyclones, pos)
        if diversion_squad:
            await handle_diversion(self, diversion_squad, diversion_target)

        if army_anchor is not None:
            await self.bio.retreat_to(bio_stragglers, army_anchor.position)
            await self.tanks.retreat_to(tanks_stragglers, army_anchor.position)
            await self.cyclones.retreat_to(cyclones_stragglers, army_anchor.position)
    else:
        await self.bio.retreat_to(bio, pos)
        await self.medivacs.retreat_to(medivacs, pos)
        await self.ravens.retreat_to(ravens, pos)
        await self.flying_vikings.retreat_to(flying_vikings, pos)
        await self.tanks.retreat_to(tanks, pos)
        await self.cyclones.retreat_to(cyclones, pos)

    for i in units:
        if attack:
            smart_attack(self, units, i, pos, enemies)
        else:
            i.move(pos)
