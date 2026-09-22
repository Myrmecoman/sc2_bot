from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.units import Units
from sc2.ids.unit_typeid import UnitTypeId
from bot.pathing.order_utils import is_already_moving_to

SCOUT_DANGER_RANGE = 10.0    # abort if a combat unit gets this close - not worth losing the worker for a few more seconds of vision
SCOUT_GIVE_UP_TIME = 150.0   # stop waiting to start a scouting run after this long


async def scout(self : BotAI) -> None:
    """Send a single worker to get eyes on the enemy base early, once instead of only ever
    learning their race/tech/expansions incidentally from Reapers/Banshees existing mid-game."""

    if self.enemy_base_scouted or (self.scout_attempted and self.scout_worker_tag is None):
        return

    if self.scout_worker_tag is None:
        # send it right as the first barracks goes down - early enough to still be useful
        # intel, late enough not to be pulled before the opening's critical structures are secured.
        # never START a run mid worker-rush - every worker is needed for defense/economy right
        # now. (an ALREADY-out scout isn't specifically recalled for this - by the time a rush is
        # detected it's typically already too far away to help defend home anyway, and it still
        # has its own danger-abort check below if a real threat gets close to it specifically)
        barracks_placed = self.structures(UnitTypeId.BARRACKS).amount > 0 or self.already_pending(UnitTypeId.BARRACKS) > 0
        if self.time > SCOUT_GIVE_UP_TIME or not barracks_placed or self.worker_rushed:
            return
        # avoid grabbing a worker another system already committed to (notably the scripted
        # build order's worker) - picking that one out from under it looks like a stalled build
        candidates: Units = (self.workers.gathering | self.workers.idle).tags_not_in({self.build_order_critical_worker})
        if candidates.amount == 0:
            return
        self.scout_attempted = True
        self.scout_worker_tag = candidates.random.tag
        return

    worker = self.workers.find_by_tag(self.scout_worker_tag)
    if worker is None: # it died - don't send another one after it
        self.scout_worker_tag = None
        return

    if self.is_visible(self.enemy_start_locations[0]):
        self.enemy_base_scouted = True
        self.scout_worker_tag = None
        return

    danger : Units = self.enemy_units.filter(lambda u: u.type_id not in {UnitTypeId.PROBE, UnitTypeId.SCV, UnitTypeId.DRONE} and u.can_attack_ground)
    if danger.amount > 0 and danger.closest_distance_to(worker) < SCOUT_DANGER_RANGE:
        self.scout_worker_tag = None # abandon the run, let it path home and rejoin mining on its own
        worker.move(self.start_location)
        return

    if not is_already_moving_to(worker, self.enemy_start_locations[0]):
        worker.move(self.enemy_start_locations[0])
