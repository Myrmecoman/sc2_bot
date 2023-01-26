from typing import Optional, Set
from sc2.bot_ai import BotAI
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from training_bots.MassReaper.pathing import Pathing
from training_bots.MassReaper.reapers import Reapers
from training_bots.MassReaper.consts import ATTACK_TARGET_IGNORE

DEBUG: bool = False


class MassReaper(BotAI):
    # In pathing we are going to use MapAnalyzer's pathing module
    # Here we will add enemy influence, and create pathing methods
    # Our reapers will have access to this class
    pathing: Pathing

    # use a separate class for all reaper control
    reapers: Reapers

    def __init__(self):
        super().__init__()
        self.worker_defence_tags: Set[int] = set()
        self.enemy_committed_worker_rush: bool = False

    async def on_before_start(self) -> None:
        for worker in self.workers:
            worker.gather(self.mineral_field.closest_to(worker))

    async def on_start(self) -> None:
        self.client.game_step = 2
        self.pathing = Pathing(self, DEBUG)
        self.reapers = Reapers(self, self.pathing)

    async def on_step(self, iteration: int):
        # The macro part of this uses the reaper example in python-sc2:
        # https://github.com/BurnySc2/python-sc2/blob/develop/examples/terran/mass_reaper.py
        # this could be improved
        await self._do_mass_reaper_macro(iteration)

        # add enemy units to our pathing grids (influence)
        self.pathing.update()

        # make one call to get out attack target
        attack_target: Point2 = self.get_attack_target
        # call attack method in our reaper class
        await self.reapers.handle_attackers(
            self.units(UnitTypeId.REAPER), attack_target
        )

    @property
    def get_attack_target(self) -> Point2:
        if self.time > 300.0:
            if enemy_units := self.enemy_units.filter(
                lambda u: u.type_id not in ATTACK_TARGET_IGNORE
                and not u.is_flying
                and not u.is_cloaked
                and not u.is_hallucination
            ):
                return enemy_units.closest_to(self.start_location).position
            elif enemy_structures := self.enemy_structures:
                return enemy_structures.closest_to(self.start_location).position

        return self.enemy_start_locations[0]

    async def _do_mass_reaper_macro(self, iteration: int):
        """
        Stolen from https://github.com/BurnySc2/python-sc2/blob/develop/examples/terran/mass_reaper.py
        With a few small tweaks
        - build depots when low on remaining supply
        - townhalls contains commandcenter and orbitalcommand
        - self.units(TYPE).not_ready.amount selects all units of that type, filters incomplete units, and then counts the amount
        - self.already_pending(TYPE) counts how many units are queued
        """
        if (
            self.supply_left < 5
            and self.townhalls
            and self.supply_used >= 14
            and self.can_afford(UnitTypeId.SUPPLYDEPOT)
            and self.already_pending(UnitTypeId.SUPPLYDEPOT) < 1
        ):
            if workers := self.workers.gathering:
                worker: Unit = workers.furthest_to(workers.center)
                location: Optional[Point2] = await self.find_placement(
                    UnitTypeId.SUPPLYDEPOT, worker.position, placement_step=3
                )
                # If a placement location was found
                if location:
                    # Order worker to build exactly on that location
                    worker.build(UnitTypeId.SUPPLYDEPOT, location)

        # Lower all depots when finished
        for depot in self.structures(UnitTypeId.SUPPLYDEPOT).ready:
            depot(AbilityId.MORPH_SUPPLYDEPOT_LOWER)

        # Morph commandcenter to orbitalcommand
        # Check if tech requirement for orbital is complete (e.g. you need a barracks to be able to morph an orbital)
        if self.tech_requirement_progress(UnitTypeId.ORBITALCOMMAND) == 1:
            # Loop over all idle command centers (CCs that are not building SCVs or morphing to orbital)
            for cc in self.townhalls(UnitTypeId.COMMANDCENTER).idle:
                if self.can_afford(UnitTypeId.ORBITALCOMMAND):
                    cc(AbilityId.UPGRADETOORBITAL_ORBITALCOMMAND)

        # Expand if we can afford (400 minerals) and have less than 2 bases
        if (
            1 <= self.townhalls.amount < 2
            and self.already_pending(UnitTypeId.COMMANDCENTER) == 0
            and self.can_afford(UnitTypeId.COMMANDCENTER)
        ):
            # get_next_expansion returns the position of the next possible expansion location where you can place a command center
            location: Point2 = await self.get_next_expansion()
            if location:
                # Now we "select" (or choose) the nearest worker to that found location
                worker: Unit = self.select_build_worker(location)
                if worker and self.can_afford(UnitTypeId.COMMANDCENTER):
                    # The worker will be commanded to build the command center
                    worker.build(UnitTypeId.COMMANDCENTER, location)

        # Build up to 7 barracks if we can afford them
        max_barracks: int = 4 if len(self.townhalls) <= 1 else 7
        if (
            self.tech_requirement_progress(UnitTypeId.BARRACKS) == 1
            and self.structures(UnitTypeId.BARRACKS).ready.amount
            + self.already_pending(UnitTypeId.BARRACKS)
            < max_barracks
            and self.can_afford(UnitTypeId.BARRACKS)
        ):
            workers: Units = self.workers.gathering
            if (
                workers and self.townhalls
            ):  # need to check if townhalls.amount > 0 because placement is based on townhall location
                worker: Unit = workers.furthest_to(workers.center)
                # I chose placement_step 4 here so there will be gaps between barracks hopefully
                location: Point2 = await self.find_placement(
                    UnitTypeId.BARRACKS,
                    self.townhalls.random.position.towards(
                        self.game_info.map_center, 8
                    ),
                    placement_step=4,
                )
                if location:
                    worker.build(UnitTypeId.BARRACKS, location)

        # Build refineries (on nearby vespene) when at least one barracks is in construction
        if (
            self.structures(UnitTypeId.BARRACKS).ready.amount
            + self.already_pending(UnitTypeId.BARRACKS)
            > 0
            and self.already_pending(UnitTypeId.REFINERY) < 1
        ):
            # Loop over all townhalls nearly complete
            for th in self.townhalls.filter(lambda _th: _th.build_progress > 0.3):
                # Find all vespene geysers that are closer than range 10 to this townhall
                vgs: Units = self.vespene_geyser.closer_than(10, th)
                for vg in vgs:
                    if await self.can_place_single(
                        UnitTypeId.REFINERY, vg.position
                    ) and self.can_afford(UnitTypeId.REFINERY):
                        workers: Units = self.workers.gathering
                        if workers:  # same condition as above
                            worker: Unit = workers.closest_to(vg)
                            # Caution: the target for the refinery has to be the vespene geyser, not its position!
                            worker.build_gas(vg)

                            # Dont build more than one each frame
                            break

        # Make scvs until 22
        if (
            self.can_afford(UnitTypeId.SCV)
            and self.supply_left > 0
            and self.supply_workers < 22
            and (
                self.structures(UnitTypeId.BARRACKS).ready.amount < 1
                and self.townhalls(UnitTypeId.COMMANDCENTER).idle
                or self.townhalls(UnitTypeId.ORBITALCOMMAND).idle
            )
        ):
            for th in self.townhalls.idle:
                th.train(UnitTypeId.SCV)

        # Make reapers if we can afford them and we have supply remaining
        if self.supply_left > 0:
            # Loop through all idle barracks
            for rax in self.structures(UnitTypeId.BARRACKS).idle:
                if self.can_afford(UnitTypeId.REAPER):
                    rax.train(UnitTypeId.REAPER)

        # Send workers to mine
        if iteration % 12 == 0:
            await self.my_distribute_workers()

        # Manage orbital energy and drop mules
        for oc in self.townhalls(UnitTypeId.ORBITALCOMMAND).filter(
            lambda x: x.energy >= 50
        ):
            mfs: Units = self.mineral_field.closer_than(10, oc)
            if mfs:
                mf: Unit = max(mfs, key=lambda x: x.mineral_contents)
                oc(AbilityId.CALLDOWNMULE_CALLDOWNMULE, mf)

    # Distribute workers function rewritten, the default distribute_workers() function did not saturate gas quickly enough
    # pylint: disable=R0912
    async def my_distribute_workers(
        self, performance_heavy=True, only_saturate_gas=False
    ):
        mineral_tags = [x.tag for x in self.mineral_field]
        gas_building_tags = [x.tag for x in self.gas_buildings]

        worker_pool = self.workers.idle
        worker_pool_tags = worker_pool.tags

        # Find all gas_buildings that have surplus or deficit
        deficit_gas_buildings = {}
        surplusgas_buildings = {}
        for g in self.gas_buildings.filter(lambda x: x.vespene_contents > 0):
            # Only loop over gas_buildings that have still gas in them
            deficit = g.ideal_harvesters - g.assigned_harvesters
            if deficit > 0:
                deficit_gas_buildings[g.tag] = {"unit": g, "deficit": deficit}
            elif deficit < 0:
                surplus_workers = self.workers.closer_than(10, g).filter(
                    lambda w: w not in worker_pool_tags
                    and len(w.orders) == 1
                    and w.orders[0].ability.id in [AbilityId.HARVEST_GATHER]
                    and w.orders[0].target in gas_building_tags
                )
                for _ in range(-deficit):
                    if surplus_workers.amount > 0:
                        w = surplus_workers.pop()
                        worker_pool.append(w)
                        worker_pool_tags.add(w.tag)
                surplusgas_buildings[g.tag] = {"unit": g, "deficit": deficit}

        # Find all townhalls that have surplus or deficit
        deficit_townhalls = {}
        surplus_townhalls = {}
        if not only_saturate_gas:
            for th in self.townhalls:
                deficit = th.ideal_harvesters - th.assigned_harvesters
                if deficit > 0:
                    deficit_townhalls[th.tag] = {"unit": th, "deficit": deficit}
                elif deficit < 0:
                    surplus_workers = self.workers.closer_than(10, th).filter(
                        lambda w: w.tag not in worker_pool_tags
                        and len(w.orders) == 1
                        and w.orders[0].ability.id in [AbilityId.HARVEST_GATHER]
                        and w.orders[0].target in mineral_tags
                    )
                    # worker_pool.extend(surplus_workers)
                    for _ in range(-deficit):
                        if surplus_workers.amount > 0:
                            w = surplus_workers.pop()
                            worker_pool.append(w)
                            worker_pool_tags.add(w.tag)
                    surplus_townhalls[th.tag] = {"unit": th, "deficit": deficit}

        # Check if deficit in gas less or equal than what we have in surplus, else grab some more workers from surplus bases
        deficit_gas_count = sum(
            gasInfo["deficit"]
            for gasTag, gasInfo in deficit_gas_buildings.items()
            if gasInfo["deficit"] > 0
        )
        surplus_count = sum(
            -gasInfo["deficit"]
            for gasTag, gasInfo in surplusgas_buildings.items()
            if gasInfo["deficit"] < 0
        )
        surplus_count += sum(
            -townhall_info["deficit"]
            for townhall_tag, townhall_info in surplus_townhalls.items()
            if townhall_info["deficit"] < 0
        )

        if deficit_gas_count - surplus_count > 0:
            # Grab workers near the gas who are mining minerals
            for _gas_tag, gas_info in deficit_gas_buildings.items():
                if worker_pool.amount >= deficit_gas_count:
                    break
                workers_near_gas = self.workers.closer_than(
                    50, gas_info["unit"]
                ).filter(
                    lambda w: w.tag not in worker_pool_tags
                    and len(w.orders) == 1
                    and w.orders[0].ability.id in [AbilityId.HARVEST_GATHER]
                    and w.orders[0].target in mineral_tags
                )
                while (
                    workers_near_gas.amount > 0
                    and worker_pool.amount < deficit_gas_count
                ):
                    w = workers_near_gas.pop()
                    worker_pool.append(w)
                    worker_pool_tags.add(w.tag)

        # Now we should have enough workers in the pool to saturate all gases, and if there are workers left over, make them mine at townhalls that have mineral workers deficit
        for _gas_tag, gas_info in deficit_gas_buildings.items():
            if performance_heavy:
                # Sort furthest away to closest (as the pop() function will take the last element)
                worker_pool.sort(
                    key=lambda x: x.distance_to(gas_info["unit"]), reverse=True
                )
            for _ in range(gas_info["deficit"]):
                if worker_pool.amount > 0:
                    w = worker_pool.pop()
                    if len(w.orders) == 1 and w.orders[0].ability.id in [
                        AbilityId.HARVEST_RETURN
                    ]:
                        w.gather(gas_info["unit"], queue=True)
                    else:
                        w.gather(gas_info["unit"])

        if not only_saturate_gas:
            # If we now have left over workers, make them mine at bases with deficit in mineral workers
            for townhall_tag, townhall_info in deficit_townhalls.items():

                if performance_heavy:
                    # Sort furthest away to closest (as the pop() function will take the last element)
                    worker_pool.sort(
                        key=lambda x: x.distance_to(townhall_info["unit"]), reverse=True
                    )
                for _ in range(townhall_info["deficit"]):
                    if worker_pool.amount > 0:
                        w = worker_pool.pop()
                        mf = self.mineral_field.closer_than(
                            10, townhall_info["unit"]
                        ).closest_to(w)
                        if len(w.orders) == 1 and w.orders[0].ability.id in [
                            AbilityId.HARVEST_RETURN
                        ]:
                            w.gather(mf, queue=True)
                        else:
                            w.gather(mf)
