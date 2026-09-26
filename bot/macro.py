from bot.custom_utils import can_build_structure
from bot.custom_utils import get_safest_expansion
from bot.custom_utils import is_supply_critical
from bot.custom_utils import update_rally_points
from bot.repair import manage_repairs

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
async def smart_build_behind_mineral(self : BotAI, type : UnitTypeId, townhalls : Units = None):
    # try all ccs (or just the given ones) and find average position of its mineral fields
    for cc in (self.townhalls.ready if townhalls is None else townhalls):
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


# Production buildings: how many the number of bases calls for, how many at most, and when a bank that keeps piling up calls for more.
MAX_BARRACKS = 6               # never more than this many of each, whatever the bank says
MAX_FACTORIES = 2
MAX_STARPORTS = 2
BANK_MINERALS = 1000           # "piling up": this much unspent...
BANK_GAS = 350                 # ...and this much gas, for the buildings that make gas units (a Factory, a Starport)
END_GAME_SUPPLY = 100          # ...late in the game: at least this much supply used
TURRET_BASE_RADIUS = 15.0      # a turret this close to a townhall belongs to its base


def production_targets(self : BotAI) -> dict:
    """How many of each production building we want right now: what the number of bases calls for (the caps of the schedule below), and
    one more than we have while the bank piles up - one at a time, up to MAX_*. The gas buildings only when gas piles up as well and
    there is something left for them to make."""
    bases = self.townhalls.amount
    advisor = self.army_advisor
    have = {
        UnitTypeId.BARRACKS: self.structures(UnitTypeId.BARRACKS).amount + self.structures(UnitTypeId.BARRACKSFLYING).amount,
        UnitTypeId.FACTORY: self.structures(UnitTypeId.FACTORY).amount + self.structures(UnitTypeId.FACTORYFLYING).amount,
        UnitTypeId.STARPORT: self.structures(UnitTypeId.STARPORT).amount + self.structures(UnitTypeId.STARPORTFLYING).amount,
    }
    starports = 2 if bases >= 4 else (1 if bases >= 2 or advisor.starport_now else 0)
    # a second factory is only worth it once we're actually planning a real mech presence
    factories = 2 if bases >= 3 and (advisor.max_tanks + advisor.max_cyclones) > 10 else (1 if bases >= 1 else 0)
    barracks = 6 if bases >= 4 else (5 if bases >= 3 else (2 if bases >= 2 else (1 if bases >= 1 else 0)))
    targets = {UnitTypeId.STARPORT: starports, UnitTypeId.FACTORY: factories, UnitTypeId.BARRACKS: barracks}

    if self.supply_used >= END_GAME_SUPPLY and self.minerals >= BANK_MINERALS:
        gas_banking = self.vespene >= BANK_GAS
        tanks = self.units.of_type({UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED}).amount
        targets[UnitTypeId.BARRACKS] = max(targets[UnitTypeId.BARRACKS], have[UnitTypeId.BARRACKS] + 1)
        if gas_banking and tanks < advisor.max_tanks:
            targets[UnitTypeId.FACTORY] = max(targets[UnitTypeId.FACTORY], have[UnitTypeId.FACTORY] + 1)
        if gas_banking:
            targets[UnitTypeId.STARPORT] = max(targets[UnitTypeId.STARPORT], have[UnitTypeId.STARPORT] + 1)
    caps = {UnitTypeId.BARRACKS: MAX_BARRACKS, UnitTypeId.FACTORY: MAX_FACTORIES, UnitTypeId.STARPORT: MAX_STARPORTS}
    return {t: min(caps[t], amount) for t, amount in targets.items()}


async def build_production_buildings(self : BotAI):
    """Starports, Factories and Barracks, in that order of priority (the ones that make the units we need most come first)."""
    targets = production_targets(self)
    for building, flying in ((UnitTypeId.STARPORT, UnitTypeId.STARPORTFLYING), (UnitTypeId.FACTORY, UnitTypeId.FACTORYFLYING),
                             (UnitTypeId.BARRACKS, UnitTypeId.BARRACKSFLYING)):
        if can_build_structure(self, building, flying, targets[building]):
            await smart_build(self, building)


async def build_turrets(self : BotAI):
    """A missile turret (two against a big Mutalisk flock) in every mineral line when the scouting calls for it (army_advisor.turrets_per_base,
    see reactions.py): Dark Templar, Banshees, Oracles and Mutalisks all get there faster than an army can be brought home - and a turret
    is a detector that needs no energy and no Raven. Needs an Engineering Bay, which is built first."""
    per_base = self.army_advisor.turrets_per_base
    if per_base <= 0 or self.townhalls.amount == 0:
        return
    if not self.structures(UnitTypeId.ENGINEERINGBAY).ready:
        if can_build_structure(self, UnitTypeId.ENGINEERINGBAY, None, 1):
            await smart_build_behind_mineral(self, UnitTypeId.ENGINEERINGBAY)
        return
    if self.already_pending(UnitTypeId.MISSILETURRET) > 0 or not self.can_afford(UnitTypeId.MISSILETURRET):
        return
    for cc in self.townhalls.ready:
        if self.turret_backoff.get(cc.tag, 0.0) > self.time:
            continue
        if self.structures(UnitTypeId.MISSILETURRET).closer_than(TURRET_BASE_RADIUS, cc).amount < per_base:
            self.turret_backoff[cc.tag] = self.time + 4.0        # (placing can fail, and the new turret takes a moment to show up)
            await smart_build_behind_mineral(self, UnitTypeId.MISSILETURRET, townhalls=Units([cc], self))
            return


async def macro(self : BotAI):

    cancel_building(self)
    manage_repairs(self)
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

    await build_production_buildings(self)
    await build_turrets(self)

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
