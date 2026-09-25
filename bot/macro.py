from bot.custom_utils import can_build_structure
from bot.custom_utils import get_safest_expansion
from bot.custom_utils import is_supply_critical
from bot.custom_utils import update_rally_points

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2, Point3
from typing import FrozenSet, Set
from sc2.bot_ai import BotAI
from sc2.data import Race
import math


async def build_gas(self : BotAI) -> bool:
    for cc in self.townhalls.ready:
        vgs: Units = self.vespene_geyser.closer_than(12, cc)
        for vg in vgs:
            if await self.can_place_single(UnitTypeId.REFINERY, vg.position):
                workers: Units = self.workers.gathering
                if workers:
                    worker: Unit = workers.closest_to(vg)
                    worker.build_gas(vg)
                    return True
    return False


async def build_cc(self : BotAI, build_worker: Unit = None) -> bool:
    location: Point2 = await get_safest_expansion(self)
    if location is not None:
        # prefer the worker the caller already has committed/walking there (e.g. the scripted
        # build order's critical_worker) over reselecting - select_build_worker only considers
        # gathering/idle workers, which would always exclude one that's already mid-move
        worker: Unit = build_worker if build_worker is not None else self.select_build_worker(location)
        if worker is None:
            return False
        self.worker_assigned_to_expand[worker.tag] = worker
        worker.build(UnitTypeId.COMMANDCENTER, location)
        return True
    return False


async def try_build_on_line(self : BotAI, type : UnitTypeId, prod_structures : Units, shift = 0):
    for i in prod_structures:
        if await self.can_place_single(type, Point2((i.position.x + shift, i.position.y + 3))) and await self.can_place_single(type, Point2((i.position.x + shift, i.position.y + 6))):
            await self.build(type, near=Point2((i.position.x + shift, i.position.y + 3)))
            return True
        if await self.can_place_single(type, Point2((i.position.x + shift, i.position.y - 3))) and await self.can_place_single(type, Point2((i.position.x + shift, i.position.y - 6))):
            await self.build(type, near=Point2((i.position.x + shift, i.position.y - 3)))
            return True
    return False


async def smart_build(self : BotAI, type : UnitTypeId):

    if not self.can_afford(UnitTypeId.BARRACKS) or self.tech_requirement_progress(UnitTypeId.BARRACKS) != 1:
        return False

    prod_structures : Units = self.structures.of_type({UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT})

    if prod_structures.amount == 0 and self.main_base_ramp.barracks_in_middle:
        if self.workers.amount == 0: # closest_to raises on an empty collection
            return False
        worker: Unit = self.workers.closest_to(self.main_base_ramp.barracks_in_middle) # pretty unsafe but works and should not pose any issue
        pos = self.main_base_ramp.barracks_correct_placement
        if self.enemy_race == Race.Zerg or self.enemy_race == Race.Protoss:
            pos = self.main_base_ramp.barracks_in_middle
        if await self.can_place_single(type, pos):
            worker.build(type, pos)
            return True
        return False

    # build as a line from any started line - skip the wall barracks specifically for this tight
    # (+/-3, +/-6) immediate-adjacency attempt: it already sits flush against both corner depots
    # by design (that's what makes it a wall), so chaining another building directly onto it here
    # can eat the last bit of room a worker needs to path in and repair those depots. The wider
    # offsets below are far enough away that this isn't a concern, so they still use it freely.
    wall_pos = self.main_base_ramp.barracks_in_middle
    correct_pos = self.main_base_ramp.barracks_correct_placement
    non_wall_structures: Units = prod_structures.filter(
        lambda s: (wall_pos is None or s.position.distance_to(wall_pos) > 3)
        and (correct_pos is None or s.position.distance_to(correct_pos) > 3)
    )
    if await try_build_on_line(self, type, non_wall_structures):
        return True

    # else try to build on right or left alternatively
    if await try_build_on_line(self, type, prod_structures, -7):
        return True
    if await try_build_on_line(self, type, prod_structures, 7):
        return True
    
    # else well try further
    if await try_build_on_line(self, type, prod_structures, -14):
        return True
    if await try_build_on_line(self, type, prod_structures, 14):
        return True
    # no place found
    return False


HALF_OFFSET = Point2((.5, .5))
async def smart_build_behind_mineral(self : BotAI, type : UnitTypeId):
    # try all ccs and find average position of its mineral fields
    for cc in self.townhalls.ready:
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
            position = cc.position.towards_with_random_angle(Point2((x, y)), 9, (math.pi / 3))
            position_further = cc.position.towards_with_random_angle(Point2((x, y)), 12, (math.pi / 3))
            position = position.rounded.offset(HALF_OFFSET)
            position_further = position_further.rounded.offset(HALF_OFFSET)
            if await self.can_place_single(type, position):
                await self.build(type, near=position, max_distance=4)
                return
            if await self.can_place_single(type, position_further):
                await self.build(type, near=position_further, max_distance=4)
                return
        print("Could not place tech building behind mineral lines")


# An SCV with a repair order on a unit follows that unit for as long as it needs repairs, wherever it goes: with the army marching
# to the enemy's base, every SCV repairing one of its tanks / medivacs / vikings went along across the whole map, and walked all the
# way back (micro_worker sends idle workers home) once the repair was over. Repairs are a job for the home area:
REPAIR_HOME_RADIUS = 25.0   # a damaged unit or building is only repaired while it is this close to one of our (landed) townhalls
REPAIR_LEASH = 35.0         # only workers this close to one of them are sent to repair, and one that ends up farther is sent back to mine
# (the leash is wider than the radius so a worker trailing a unit that walks out of the radius is not sent back and re-picked, over and over)


def release_far_repairers(self : BotAI):
    """Send SCVs that repair far from every landed townhall back to mining (the unit gets repaired again once it is back home)."""
    bases: Units = self.townhalls.not_flying
    if bases.empty or self.mineral_field.empty:
        return
    for worker in self.workers.filter(lambda w: w.is_repairing):
        if bases.closest_distance_to(worker) > REPAIR_LEASH:
            worker.gather(self.mineral_field.closest_to(bases.closest_to(worker)))


def repair_buildings(self : BotAI):

    if self.worker_rushed and not self.army_advisor.is_wall_closed():
        return

    bases: Units = self.townhalls.not_flying
    if bases.empty:
        return

    # adding tag if needs to be repaired, else remove it
    for i in self.structures.ready:
        if i.health_percentage > 0.9:
            if i.tag in self.worker_assigned_to_repair.keys():
                self.worker_assigned_to_repair.pop(i.tag)
            continue
        if i.tag in self.worker_assigned_to_repair.keys():
            continue
        self.worker_assigned_to_repair[i.tag] = []
    
    for key in self.worker_assigned_to_repair.keys():
        if self.structures.find_by_tag(key) is None: # the building died
            continue
        total_repairing = len(self.worker_assigned_to_repair[key])

        # keep only workers still actually repairing this specific target - one whose repair
        # got interrupted or redirected elsewhere shouldn't keep occupying a counted slot while
        # it just stands there idle
        new_value = []
        for i in range(total_repairing):
            worker_tag = self.worker_assigned_to_repair[key][i]
            worker = self.workers.find_by_tag(worker_tag)
            if worker is not None and worker.is_repairing and worker.order_target == key:
                new_value.append(worker_tag)
        self.worker_assigned_to_repair[key] = new_value
        total_repairing = len(self.worker_assigned_to_repair[key])

        i = self.structures.find_by_tag(key)
        # a flying building (e.g. a CC lifted to evade a rush) is already out of danger - still
        # repairable, but doesn't need a full repair crew the way something actively under fire does
        max_repairers = 1 if i.is_flying else (4 if i.health_percentage < 0.5 else 2)
        if total_repairing >= max_repairers or bases.closest_distance_to(i) > REPAIR_HOME_RADIUS:
            continue

        sorted_workers : Units = self.workers.sorted(lambda x: x.distance_to(i))
        for wo in sorted_workers:
            # total_repairing must be re-checked (not just gated once above) - otherwise every
            # qualifying worker in range gets assigned in this same pass, blowing straight past
            # the cap, since the tracking list only reflects the count again next frame
            if total_repairing >= max_repairers:
                break
            if wo.is_repairing or wo.is_constructing_scv or bases.closest_distance_to(wo) > REPAIR_LEASH:
                continue
            if wo.distance_to(i) < 30:
                wo(AbilityId.EFFECT_REPAIR_SCV, i)
                self.worker_assigned_to_repair[key].append(wo.tag)
                total_repairing += 1
                total_repairing = len(self.worker_assigned_to_repair[key])


def repair_mechanical_units(self : BotAI):
    """Same idea as repair_buildings, but for damaged mechanical army units (tanks, hellions,
    thors, cyclones, vikings, banshees, ravens, battlecruisers) instead of structures. Kept more
    conservative than building repair (higher damage threshold, fewer repairers) since army units
    take routine chip damage constantly in any engagement - repairing every scratch is what was
    pulling workers off mining so often."""

    if self.worker_rushed and not self.army_advisor.is_wall_closed():
        return

    bases: Units = self.townhalls.not_flying
    if bases.empty:
        return

    # is_mechanical is also true for SCVs/MULEs in the actual game data - excluding them explicitly
    # is required, not just a style choice, otherwise every worker that takes a scratch of damage
    # gets queued as a repair target and pulls other workers off mining to chase it down
    mech_units : Units = self.units.filter(lambda u: u.is_mechanical and u.type_id not in {UnitTypeId.SCV, UnitTypeId.MULE})

    # only bother once meaningfully damaged, and only if it's actually safe to send a worker there - and only at home: a worker
    # sent to a unit out on the map follows it (see REPAIR_LEASH)
    for i in mech_units:
        if i.health_percentage > 0.7 or not self.is_unit_position_safe(i) or bases.closest_distance_to(i) > REPAIR_HOME_RADIUS:
            if i.tag in self.worker_assigned_to_repair_mech.keys():
                self.worker_assigned_to_repair_mech.pop(i.tag)
            continue
        if i.tag in self.worker_assigned_to_repair_mech.keys():
            continue
        self.worker_assigned_to_repair_mech[i.tag] = []

    # workers repair_buildings already committed this frame shouldn't also get pulled here -
    # issuing a command doesn't update a unit's own cached order state until next frame, so
    # without this a worker could get claimed by both in the same step
    already_repairing_structures = {tag for tags in self.worker_assigned_to_repair.values() for tag in tags}

    for key in list(self.worker_assigned_to_repair_mech.keys()):
        target = mech_units.find_by_tag(key)
        if target is None: # the unit died
            self.worker_assigned_to_repair_mech.pop(key, None)
            continue
        total_repairing = len(self.worker_assigned_to_repair_mech[key])

        # keep only workers still actually repairing this specific target - see repair_buildings
        new_value = []
        for i in range(total_repairing):
            worker_tag = self.worker_assigned_to_repair_mech[key][i]
            worker = self.workers.find_by_tag(worker_tag)
            if worker is not None and worker.is_repairing and worker.order_target == key:
                new_value.append(worker_tag)
        self.worker_assigned_to_repair_mech[key] = new_value
        total_repairing = len(self.worker_assigned_to_repair_mech[key])

        max_repairers = 2 if target.health_percentage < 0.3 else 1
        if total_repairing >= max_repairers:
            continue

        # only ever pull workers that are otherwise just mining, never ones already tasked elsewhere
        candidates : Units = self.workers.filter(lambda w: (w.is_gathering or w.is_idle) and bases.closest_distance_to(w) <= REPAIR_LEASH)
        candidates = candidates.tags_not_in(already_repairing_structures)
        sorted_workers : Units = candidates.sorted(lambda x: x.distance_to(target))
        for wo in sorted_workers:
            if wo.is_repairing or wo.is_constructing_scv:
                continue
            if wo.distance_to(target) < 30:
                wo(AbilityId.EFFECT_REPAIR_SCV, target)
                self.worker_assigned_to_repair_mech[key].append(wo.tag)
                total_repairing = len(self.worker_assigned_to_repair_mech[key])
                if total_repairing >= max_repairers:
                    break


def cancel_building(self : BotAI):
    for st in self.structures:
        if not st.is_ready and st.health_percentage < 0.1:
            st(AbilityId.CANCEL)


def resume_building_construction(self : BotAI):
    # checking if it is actually safe to resume construction
    for i in self.structures_without_construction_SCVs:
        if (self.visible_enemy_units.amount != 0 and self.visible_enemy_units.closest_distance_to(i) < 8) or (not self.army_advisor.is_wall_closed() and (self.worker_rushed or self.army_advisor.zergling_rushed)):
            return
    
    # update dictionary if building or worker died
    to_remove = [] # list of elements to remove from dictionary
    for k in self.worker_assigned_to_resume_building.keys():
        if self.structures.find_by_tag(k) is None or self.units.find_by_tag(self.worker_assigned_to_resume_building[k]) is None:
            to_remove.append(k)
    for i in to_remove:
        self.worker_assigned_to_resume_building.pop(i, None)

    # assign a worker for each building
    for i in self.structures_without_construction_SCVs:
        if i.tag in self.worker_assigned_to_resume_building.keys():
            continue
        if self.workers.gathering.amount == 0:
            continue
        worker = self.workers.gathering.closest_to(i)
        self.worker_assigned_to_resume_building[i.tag] = worker.tag
        worker(AbilityId.SMART, i)


async def macro(self : BotAI):

    cancel_building(self)
    release_far_repairers(self)
    repair_buildings(self)
    repair_mechanical_units(self)
    resume_building_construction(self)
    update_rally_points(self)

    if self.workers.amount == 0:
        return
    # deliberately NOT gated on the scripted build_order being empty - every check below already
    # gates itself (tech_requirement_progress, can_afford, already_pending, townhalls.amount), and
    # early_build_order always runs earlier in the same step so a build it actually starts is
    # already reflected in already_pending by the time these run. Blocking ALL of this on the
    # scripted list being fully empty was the recurring root cause behind this session's "bot does
    # nothing" bugs: any single stuck build_order step (bad placement, no worker, timing) silently
    # blocked every later structure/expansion decision too, not just the stuck one

    if self.townhalls.amount >= 2 and can_build_structure(self, UnitTypeId.STARPORT, UnitTypeId.STARPORTFLYING, 1):
        await smart_build(self, UnitTypeId.STARPORT)
    if self.townhalls.amount >= 4 and can_build_structure(self, UnitTypeId.STARPORT, UnitTypeId.STARPORTFLYING, 2):
        await smart_build(self, UnitTypeId.STARPORT)

    if self.townhalls.amount >= 1 and can_build_structure(self, UnitTypeId.FACTORY, UnitTypeId.FACTORYFLYING, 1):
        await smart_build(self, UnitTypeId.FACTORY)
    # a second factory is only worth it once we're actually planning a real mech presence
    if self.townhalls.amount >= 3 and (self.army_advisor.max_tanks + self.army_advisor.max_cyclones) > 10 and can_build_structure(self, UnitTypeId.FACTORY, UnitTypeId.FACTORYFLYING, 2):
        await smart_build(self, UnitTypeId.FACTORY)

    if self.townhalls.amount >= 1 and can_build_structure(self, UnitTypeId.BARRACKS, UnitTypeId.BARRACKSFLYING, 1):
        await smart_build(self, UnitTypeId.BARRACKS)
    if self.townhalls.amount >= 2 and can_build_structure(self, UnitTypeId.BARRACKS, UnitTypeId.BARRACKSFLYING, 2):
        await smart_build(self, UnitTypeId.BARRACKS)
    if self.townhalls.amount >= 3 and can_build_structure(self, UnitTypeId.BARRACKS, UnitTypeId.BARRACKSFLYING, 5):
        await smart_build(self, UnitTypeId.BARRACKS)
    if self.townhalls.amount >= 4 and can_build_structure(self, UnitTypeId.BARRACKS, UnitTypeId.BARRACKSFLYING, 8):
        await smart_build(self, UnitTypeId.BARRACKS)

    if self.townhalls.amount >= 3 and can_build_structure(self, UnitTypeId.ENGINEERINGBAY, None, 2):
        await smart_build_behind_mineral(self, UnitTypeId.ENGINEERINGBAY)

    if (self.already_pending_upgrade(UpgradeId.TERRANINFANTRYARMORSLEVEL1) > 0.3 or self.already_pending_upgrade(UpgradeId.TERRANINFANTRYWEAPONSLEVEL1)) > 0.3 and can_build_structure(self, UnitTypeId.ARMORY, None, 1):
        await smart_build_behind_mineral(self, UnitTypeId.ARMORY)
    if self.already_pending_upgrade(UpgradeId.TERRANINFANTRYWEAPONSLEVEL3) == 1 and can_build_structure(self, UnitTypeId.ARMORY, None, 2):
        await smart_build_behind_mineral(self, UnitTypeId.ARMORY)

    if (self.already_pending_upgrade(UpgradeId.TERRANINFANTRYARMORSLEVEL3) == 1 or self.already_pending_upgrade(UpgradeId.TERRANINFANTRYWEAPONSLEVEL3)) == 1 and can_build_structure(self, UnitTypeId.FUSIONCORE, None, 1):
        await smart_build_behind_mineral(self, UnitTypeId.FUSIONCORE)

    # unit production takes priority over grabbing another base: hold off on this (the greedy,
    # unscripted expansion beyond the opening build order) while we have no army to show for our
    # current bases yet, or while a Barracks is sitting ready-and-idle right now and could be
    # spending this same money on units instead - a CC taking the minerals a Barracks needed is
    # exactly how we ended up expanding to a 3rd base at 3:20 with zero units. Deliberately only
    # Barracks, not Factory/Starport too: marine/marauder production has no upper cap so an idle
    # Barracks always genuinely means money should be going there, but Factory/Starport sit idle
    # completely normally once the composition advisor's own caps are satisfied (e.g. max_cyclones
    # 0, max_tanks reached) - treating that as "still need to feed production" was blocking every
    # expansion past 3 bases once those caps were hit, even sitting on a huge mineral bank.
    # Same overflow valve as the supply check above: once we're banking so much it would otherwise
    # just sit dead, stop holding it back
    producer_idle: bool = self.structures(UnitTypeId.BARRACKS).ready.idle.amount > 0
    holding_for_units: bool = self.army_count == 0 or producer_idle

    if self.can_afford(UnitTypeId.COMMANDCENTER) and self.townhalls.amount < 20 and (self.already_pending(UnitTypeId.COMMANDCENTER) == 0 or self.minerals > 2000) and (not is_supply_critical(self) or self.minerals > 2000) and (not holding_for_units or self.minerals > 2000):
        await build_cc(self)

    # get refineries count
    refineries = self.structures(UnitTypeId.REFINERY)
    active_refineries = 0
    for r in refineries:
        if r.vespene_contents > 20:
            active_refineries += 1
    for w in self.workers:
        if isinstance(w.order_target, int) and self.vespene_geyser.find_by_tag(w.order_target) is not None:
            active_refineries += 1
    
    # build refineries - being walled in is still danger, not safety: the enemy is at the door,
    # so gas stays deprioritized for the whole rush, not just until the wall physically closes
    if (self.worker_rushed or self.army_advisor.zergling_rushed) and self.structures.of_type(UnitTypeId.REFINERY).amount != 0:
        if self.structure_type_build_progress(UnitTypeId.REFINERY) < 1:
            self.structures.of_type(UnitTypeId.REFINERY).first(AbilityId.CANCEL)

    # stop building more refineries once we're sitting on a big banked gas surplus - it's not
    # doing anything sitting in the bank, and more refineries just pulls more workers off minerals
    # for no benefit. hysteresis: only pause once above GAS_BANK_HIGH, only resume once back below
    # GAS_BANK_LOW, so this doesn't flip on/off every step while hovering near one threshold
    GAS_BANK_HIGH = 600
    GAS_BANK_LOW = 400
    if self.gas_bank_high:
        self.gas_bank_high = self.vespene > GAS_BANK_LOW
    else:
        self.gas_bank_high = self.vespene > GAS_BANK_HIGH

    # a depot takes priority over new refineries too, same reasoning as the CC check above - but
    # only while minerals are still actually tight for it; once we're sitting on a big bank
    # (>1200, same threshold the last refinery tier already uses) there's no risk of the depot
    # getting starved, so don't stall gas taps over it
    supply_critical_for_gas = is_supply_critical(self) and self.minerals <= 1200

    if self.townhalls.amount >= 1 and active_refineries < 1 and self.can_afford(UnitTypeId.REFINERY) and self.structures(UnitTypeId.BARRACKS).amount > 0 and not self.worker_rushed and not self.army_advisor.zergling_rushed and not self.gas_bank_high and not supply_critical_for_gas:
        await build_gas(self)
    # wait for the factory before the 2nd gas - at 1 base/1 refinery there's no vehicle tech to
    # spend the extra gas on yet, so it just sits bloating the mineral-to-gas worker ratio early
    if self.townhalls.amount >= 2 and active_refineries < 2 and self.can_afford(UnitTypeId.REFINERY) and (self.structures(UnitTypeId.FACTORY).amount > 0 or self.already_pending(UnitTypeId.FACTORY) > 0) and not self.gas_bank_high and not supply_critical_for_gas:
        await build_gas(self)
    if self.townhalls.amount >= 2 and self.structures(UnitTypeId.STARPORT).amount > 0 and active_refineries < 3 and self.can_afford(UnitTypeId.REFINERY) and not self.gas_bank_high and not supply_critical_for_gas:
        await build_gas(self)
    if self.townhalls.amount >= 3 and active_refineries < 4 and self.can_afford(UnitTypeId.REFINERY) and not self.gas_bank_high and not supply_critical_for_gas:
        await build_gas(self)
    if self.townhalls.amount >= 4 and active_refineries < 6 and self.can_afford(UnitTypeId.REFINERY) and not self.gas_bank_high and not supply_critical_for_gas:
        await build_gas(self)
    if self.townhalls.amount >= 5 and active_refineries < 7 and self.can_afford(UnitTypeId.REFINERY) and not self.gas_bank_high and not supply_critical_for_gas:
        await build_gas(self)
    if self.townhalls.amount >= 5 and active_refineries < 8 and self.can_afford(UnitTypeId.REFINERY) and self.minerals > 1200 and not self.gas_bank_high:
        await build_gas(self)
