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


# Return all points that need to be checked when trying to build an addon. Returns 4 points.
def points_to_build_addon(u_position: Point2) -> List[Point2]:
    addon_offset: Point2 = Point2((2.5, -0.5))
    addon_position: Point2 = u_position + addon_offset
    addon_points = [(addon_position + Point2((x - 0.5, y - 0.5))).rounded for x in range(0, 2) for y in range(0, 2)]
    return addon_points


def land_structures_for_addons(self : BotAI):
    # Return all points that need to be checked when trying to land at a location where there is enough space to build an addon. Returns 13 points.
    def land_positions(u_position: Point2) -> List[Point2]:
        land_positions = [(u_position + Point2((x, y))).rounded for x in range(-1, 2) for y in range(-1, 2)]
        return land_positions + points_to_build_addon(u_position)

    # Find a position to land for a flying structure so that it can build an addon
    for u in self.structures.of_type({UnitTypeId.BARRACKSFLYING, UnitTypeId.FACTORYFLYING, UnitTypeId.STARPORTFLYING}).idle:
        possible_land_positions_offset = sorted((Point2((x, y)) for x in range(-22, 22) for y in range(-7, 7)), key=lambda point: point.x**2 + point.y**2,)
        offset_point: Point2 = Point2((-0.5, -0.5))
        possible_land_positions = (u.position.rounded + offset_point + p for p in possible_land_positions_offset)
        for target_land_position in possible_land_positions:
            land_and_addon_points: List[Point2] = land_positions(target_land_position)

            authorized = True
            for i in self.structures.of_type({UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT}):
                if abs(i.position.x - target_land_position.position.x) < 7:
                    authorized = False

            if authorized and all(self.in_map_bounds(land_pos) and self.in_placement_grid(land_pos) and self.in_pathing_grid(land_pos) for land_pos in land_and_addon_points):
                u(AbilityId.LAND, target_land_position)
                break


def build_add_on(self : BotAI, type, add_on_type):
    # Build addon or lift if no room to build addon
    u: Unit
    for u in self.structures(type).ready.idle:
        if not u.has_add_on and self.can_afford(add_on_type):
            addon_points = points_to_build_addon(u.position)
            if all(self.in_map_bounds(addon_point) and self.in_placement_grid(addon_point) and self.in_pathing_grid(addon_point) for addon_point in addon_points):
                u.build(add_on_type)
            elif self.enemy_units.amount == 0 or self.enemy_units.closest_distance_to(u) > 15: # only lift if there are no threats
                u(AbilityId.LIFT)
            break
    

def handle_add_ons(self : BotAI):
    if len(self.build_order) != 0:
        return

    bars: Units = self.structures(UnitTypeId.BARRACKS)
    for b in bars.ready.idle:
        if self.structures(UnitTypeId.BARRACKSREACTOR).amount + self.already_pending(UnitTypeId.BARRACKSREACTOR) < bars.amount/2:
            if self.can_afford(UnitTypeId.REACTOR):
                build_add_on(self, UnitTypeId.BARRACKS, UnitTypeId.BARRACKSREACTOR)
        elif self.can_afford(UnitTypeId.TECHLAB):
            build_add_on(self, UnitTypeId.BARRACKS, UnitTypeId.BARRACKSTECHLAB)

    fac: Units = self.structures(UnitTypeId.FACTORY)
    for f in fac.ready.idle:
        if self.structures(UnitTypeId.FACTORYTECHLAB).amount + self.already_pending(UnitTypeId.FACTORYTECHLAB) < fac.amount/2:
            if self.can_afford(UnitTypeId.TECHLAB):
                build_add_on(self, UnitTypeId.FACTORY, UnitTypeId.FACTORYTECHLAB)
        elif self.can_afford(UnitTypeId.REACTOR):
            build_add_on(self, UnitTypeId.FACTORY, UnitTypeId.FACTORYREACTOR)

    sp: Units = self.structures(UnitTypeId.STARPORT)
    for s in sp.ready.idle:
        if self.structures(UnitTypeId.STARPORTREACTOR).amount + self.already_pending(UnitTypeId.STARPORTREACTOR) < sp.amount/2:
            if self.can_afford(UnitTypeId.REACTOR):
                build_add_on(self, UnitTypeId.STARPORT, UnitTypeId.STARPORTREACTOR)
        elif self.can_afford(UnitTypeId.TECHLAB):
            build_add_on(self, UnitTypeId.STARPORT, UnitTypeId.STARPORTTECHLAB)


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


def handle_upgrades(self : BotAI):
    bartechs = self.structures(UnitTypeId.BARRACKSTECHLAB).ready.idle
    for tech in bartechs:
        if self.can_afford(UpgradeId.SHIELDWALL) and self.already_pending_upgrade(UpgradeId.SHIELDWALL) == 0:
            tech.research(UpgradeId.SHIELDWALL)
        elif self.can_afford(UpgradeId.STIMPACK) and self.already_pending_upgrade(UpgradeId.STIMPACK) == 0:
            tech.research(UpgradeId.STIMPACK)
        elif self.can_afford(UpgradeId.PUNISHERGRENADES) and self.already_pending_upgrade(UpgradeId.PUNISHERGRENADES) == 0:
            tech.research(UpgradeId.PUNISHERGRENADES)

    engis = self.structures(UnitTypeId.ENGINEERINGBAY).ready.idle
    for engi in engis:
        if self.can_afford(UpgradeId.TERRANINFANTRYARMORSLEVEL1) and self.already_pending_upgrade(UpgradeId.TERRANINFANTRYARMORSLEVEL1) == 0:
            engi.research(UpgradeId.TERRANINFANTRYARMORSLEVEL1)
        elif self.can_afford(UpgradeId.TERRANINFANTRYWEAPONSLEVEL1) and self.already_pending_upgrade(UpgradeId.TERRANINFANTRYWEAPONSLEVEL1) == 0:
            engi.research(UpgradeId.TERRANINFANTRYWEAPONSLEVEL1)
        elif self.can_afford(UpgradeId.TERRANINFANTRYARMORSLEVEL2) and self.already_pending_upgrade(UpgradeId.TERRANINFANTRYARMORSLEVEL2) == 0:
            engi.research(UpgradeId.TERRANINFANTRYARMORSLEVEL2)
        elif self.can_afford(UpgradeId.TERRANINFANTRYWEAPONSLEVEL2) and self.already_pending_upgrade(UpgradeId.TERRANINFANTRYWEAPONSLEVEL2) == 0:
            engi.research(UpgradeId.TERRANINFANTRYWEAPONSLEVEL2)  
        elif self.can_afford(UpgradeId.TERRANINFANTRYARMORSLEVEL3) and self.already_pending_upgrade(UpgradeId.TERRANINFANTRYARMORSLEVEL3) == 0:
            engi.research(UpgradeId.TERRANINFANTRYARMORSLEVEL3)
        elif self.can_afford(UpgradeId.TERRANINFANTRYWEAPONSLEVEL3) and self.already_pending_upgrade(UpgradeId.TERRANINFANTRYWEAPONSLEVEL3) == 0:
            engi.research(UpgradeId.TERRANINFANTRYWEAPONSLEVEL3)
        elif self.can_afford(UpgradeId.TERRANBUILDINGARMOR) and self.already_pending_upgrade(UpgradeId.TERRANINFANTRYWEAPONSLEVEL3) == 1:
            engi.research(UpgradeId.TERRANBUILDINGARMOR)
        elif self.can_afford(UpgradeId.HISECAUTOTRACKING) and self.already_pending_upgrade(UpgradeId.TERRANINFANTRYWEAPONSLEVEL3) == 1:
            engi.research(UpgradeId.HISECAUTOTRACKING)
    
    if self.minerals < 1000 or self.vespene < 1000:
        return

    armories = self.structures(UnitTypeId.ARMORY).ready.idle
    for armo in armories:
        if self.can_afford(UpgradeId.TERRANVEHICLEWEAPONSLEVEL1) and self.already_pending_upgrade(UpgradeId.TERRANVEHICLEWEAPONSLEVEL1) == 0:
            armo.research(UpgradeId.TERRANVEHICLEWEAPONSLEVEL1)
        elif self.can_afford(UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL1) and self.already_pending_upgrade(UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL1) == 0:
            armo.research(UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL1)
        elif self.can_afford(UpgradeId.TERRANVEHICLEWEAPONSLEVEL2) and self.already_pending_upgrade(UpgradeId.TERRANVEHICLEWEAPONSLEVEL2) == 0:
            armo.research(UpgradeId.TERRANVEHICLEWEAPONSLEVEL2)
        elif self.can_afford(UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL2) and self.already_pending_upgrade(UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL2) == 0:
            armo.research(UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL2)
        elif self.can_afford(UpgradeId.TERRANVEHICLEWEAPONSLEVEL3) and self.already_pending_upgrade(UpgradeId.TERRANVEHICLEWEAPONSLEVEL3) == 0:
            armo.research(UpgradeId.TERRANVEHICLEWEAPONSLEVEL3)
        elif self.can_afford(UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL3) and self.already_pending_upgrade(UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL3) == 0:
            armo.research(UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL3)
        elif self.can_afford(UpgradeId.TERRANSHIPWEAPONSLEVEL1) and self.already_pending_upgrade(UpgradeId.TERRANSHIPWEAPONSLEVEL1) == 0:
            armo.research(UpgradeId.TERRANSHIPWEAPONSLEVEL1)
        elif self.can_afford(UpgradeId.TERRANSHIPWEAPONSLEVEL2) and self.already_pending_upgrade(UpgradeId.TERRANSHIPWEAPONSLEVEL2) == 0:
            armo.research(UpgradeId.TERRANSHIPWEAPONSLEVEL2)
        elif self.can_afford(UpgradeId.TERRANSHIPWEAPONSLEVEL3) and self.already_pending_upgrade(UpgradeId.TERRANSHIPWEAPONSLEVEL3) == 0:
            armo.research(UpgradeId.TERRANSHIPWEAPONSLEVEL3)


HALF_OFFSET = Point2((.5, .5))
async def handle_supply(self : BotAI):

    if self.supply_cap >= 200:
        return

    if self.supply_left < 6 and self.supply_used >= 14 and self.can_afford(UnitTypeId.SUPPLYDEPOT) and self.already_pending(UnitTypeId.SUPPLYDEPOT) < 2 and len(self.build_order) == 0:
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


def handle_orbitals(self : BotAI):
    # Manage orbital energy and drop mules if we need minerals, else keep for scanning
    if self.minerals < 800:
        for oc in self.townhalls(UnitTypeId.ORBITALCOMMAND).filter(lambda x: x.energy >= 50):
            mfs: Units = self.mineral_field.closer_than(10, oc)
            if mfs:
                mf: Unit = max(mfs, key=lambda x: x.mineral_contents)
                oc(AbilityId.CALLDOWNMULE_CALLDOWNMULE, mf)
    # Build orbital
    if self.can_afford(UnitTypeId.ORBITALCOMMAND) and len(self.build_order) == 0:
        for cc in self.townhalls(UnitTypeId.COMMANDCENTER).idle:
            cc(AbilityId.UPGRADETOORBITAL_ORBITALCOMMAND)
            break


def build_worker(self : BotAI):
    if not self.can_afford(UnitTypeId.SCV) or self.townhalls.amount == 0 or self.workers.amount > 70 or self.workers.amount >= self.townhalls.amount * 22:
        return
    ccs: Units = self.townhalls
    for cc in ccs:
        if cc.is_idle:
            cc.train(UnitTypeId.SCV)
            break
