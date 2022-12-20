from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.ids.upgrade_id import UpgradeId
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2, Point3
from typing import List, Tuple
from sc2.bot_ai import BotAI


def can_build_structure(self : BotAI, type, amount):
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
        possible_land_positions_offset = sorted((Point2((x, y)) for x in range(-10, 10) for y in range(-10, 10)), key=lambda point: point.x**2 + point.y**2,)
        offset_point: Point2 = Point2((-0.5, -0.5))
        possible_land_positions = (u.position.rounded + offset_point + p for p in possible_land_positions_offset)
        for target_land_position in possible_land_positions:
            land_and_addon_points: List[Point2] = land_positions(target_land_position)
            if all(self.in_map_bounds(land_pos) and self.in_placement_grid(land_pos) and self.in_pathing_grid(land_pos) for land_pos in land_and_addon_points):
                u(AbilityId.LAND, target_land_position)
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
        for depo in self.structures(UnitTypeId.SUPPLYDEPOT).ready:
            for unit in self.enemy_units.not_flying:
                if unit.distance_to(depo) < 15:
                    break
                else:
                    depo(AbilityId.MORPH_SUPPLYDEPOT_LOWER)
        for depo in self.structures(UnitTypeId.SUPPLYDEPOTLOWERED).ready:
            for unit in self.enemy_units:
                if unit.distance_to(depo) < 10:
                    depo(AbilityId.MORPH_SUPPLYDEPOT_RAISE)
                    break


def handle_upgrades(self : BotAI):
    engis = self.structures(UnitTypeId.ENGINEERINGBAY).ready.idle
    for engi in engis:
        if self.can_afford(UpgradeId.TERRANINFANTRYARMORSLEVEL1) and self.already_pending_upgrade(UpgradeId.TERRANINFANTRYARMORSLEVEL1) == 0:
            engi.research(UpgradeId.TERRANINFANTRYARMORSLEVEL1)
        elif self.can_afford(UpgradeId.TERRANINFANTRYWEAPONSLEVEL1) and self.already_pending_upgrade(UpgradeId.TERRANINFANTRYWEAPONSLEVEL1) == 0:
            engi.research(UpgradeId.TERRANINFANTRYWEAPONSLEVEL1)

        if self.can_afford(UpgradeId.TERRANINFANTRYARMORSLEVEL2) and self.already_pending_upgrade(UpgradeId.TERRANINFANTRYARMORSLEVEL2) == 0:
            engi.research(UpgradeId.TERRANINFANTRYARMORSLEVEL2)
        elif self.can_afford(UpgradeId.TERRANINFANTRYWEAPONSLEVEL2) and self.already_pending_upgrade(UpgradeId.TERRANINFANTRYWEAPONSLEVEL2) == 0:
            engi.research(UpgradeId.TERRANINFANTRYWEAPONSLEVEL2)
            
        if self.can_afford(UpgradeId.TERRANINFANTRYARMORSLEVEL3) and self.already_pending_upgrade(UpgradeId.TERRANINFANTRYARMORSLEVEL3) == 0:
            engi.research(UpgradeId.TERRANINFANTRYARMORSLEVEL3)
        elif self.can_afford(UpgradeId.TERRANINFANTRYWEAPONSLEVEL3) and self.already_pending_upgrade(UpgradeId.TERRANINFANTRYWEAPONSLEVEL3) == 0:
            engi.research(UpgradeId.TERRANINFANTRYWEAPONSLEVEL3)

    bartechs = self.structures(UnitTypeId.BARRACKSTECHLAB).ready.idle
    for tech in bartechs:
        if self.can_afford(UpgradeId.SHIELDWALL) and self.already_pending_upgrade(UpgradeId.SHIELDWALL) == 0:
            tech.research(UpgradeId.SHIELDWALL)
        elif self.can_afford(UpgradeId.STIMPACK) and self.already_pending_upgrade(UpgradeId.STIMPACK) == 0:
            tech.research(UpgradeId.STIMPACK)
        elif self.can_afford(UpgradeId.PUNISHERGRENADES) and self.already_pending_upgrade(UpgradeId.PUNISHERGRENADES) == 0:
            tech.research(UpgradeId.PUNISHERGRENADES)


def handle_workers(self : BotAI):
    # Saturate refineries
    for refinery in self.gas_buildings:
        if refinery.assigned_harvesters < refinery.ideal_harvesters:
            worker: Units = self.workers.closer_than(10, refinery)
            if worker:
                worker.random.gather(refinery)


async def handle_supply(self : BotAI):
    if self.supply_left < 6 and self.supply_used >= 14 and self.can_afford(UnitTypeId.SUPPLYDEPOT) and self.already_pending(UnitTypeId.SUPPLYDEPOT) < 1 and len(self.build_order) == 0:
        workers: Units = self.workers.gathering
        if workers:
            worker: Unit = workers.furthest_to(workers.center)
            location: Point2 = await self.find_placement(UnitTypeId.SUPPLYDEPOT, worker.position, placement_step=3)
            if location:
                worker.build(UnitTypeId.SUPPLYDEPOT, location)
            if len(self.build_order) == 0:
                ccs: Units = self.townhalls
                await self.build(UnitTypeId.SUPPLYDEPOT, near=ccs.random.position.towards(self.game_info.map_center, 8))


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
        cc: Unit
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


def build_add_on(self : BotAI, type, add_on_type):
    # Build addon or lift if no room to build addon
    u: Unit
    for u in self.structures(type).ready.idle:
        if not u.has_add_on and self.can_afford(add_on_type):
            addon_points = points_to_build_addon(u.position)
            if all(self.in_map_bounds(addon_point) and self.in_placement_grid(addon_point) and self.in_pathing_grid(addon_point) for addon_point in addon_points):
                u.build(add_on_type)
            else:
                u(AbilityId.LIFT)
            break


def handle_constructions(self : BotAI):
    for b in self.structures_without_construction_SCVs:
        return
