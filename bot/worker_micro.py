"""Worker micro that is not mining: stopping Planetary Fortress rushes, protecting workers that are constructing, and
pulling workers out of harm's way. (Army micro lives in bot/army/.)

All of these look at enemies that are visible RIGHT NOW (`visible_enemy_units`), not the remembered ghosts Ares keeps
in `enemy_units` - reacting to a unit that left vision half a minute ago would drag workers around for nothing."""
from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.pathing.order_utils import is_already_moving_to

WORKER_FLEE_RANGE = 7.0   # start pulling workers back before a fast threat like a reaper is already on top of them


def prevent_PF_rush(self: BotAI):
    enemy_flying_structures: Units = self.enemy_structures.of_type({UnitTypeId.COMMANDCENTERFLYING})
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
        closest_worker: Unit = self.workers.gathering.closest_to(closest_enemy_struct)
        closest_worker.move(closest_enemy_struct.position)
        self.worker_assigned_to_follow[closest_enemy_struct.tag] = closest_worker.tag


def defend_building_workers(self: BotAI):
    enemy_workers = self.visible_enemy_units.of_type({UnitTypeId.SCV, UnitTypeId.PROBE, UnitTypeId.DRONE})
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


def flee_worker_threats(self: BotAI):
    """Pull workers away from an immediate combat threat (reaper/hellion harass etc.) instead of
    letting them keep mining and get picked off one by one - workers can't meaningfully fight
    back against most combat units, so self-preservation is the right reaction here, not
    continuing to work as if nothing is happening."""
    if self.worker_rushed:
        return  # worker_rush_defense already has its own dedicated worker-combat logic for that case

    threats: Units = self.visible_enemy_units.filter(
        lambda u: u.can_attack_ground and u.type_id not in {UnitTypeId.PROBE, UnitTypeId.SCV, UnitTypeId.DRONE}
    )
    if threats.amount == 0:
        return

    for worker in self.workers:
        if worker.is_repairing or worker.is_constructing_scv:
            continue  # already committed to a specific, actively-managed task elsewhere
        # build_order_critical_worker is deliberately NOT exempted here (only from being re-picked for a DIFFERENT
        # task, e.g. by scout()) - early_build_order() runs earlier in the same step and keeps re-issuing its own
        # move order every frame regardless, so this only overrides it while a real threat is within
        # WORKER_FLEE_RANGE, and the build-order walk resumes on its own the instant the worker is safe again.
        # Exempting it from fleeing too would leave a worker walking to a build site defenseless against anything
        # that wanders close during the walk
        closest_threat = threats.closest_to(worker)
        if worker.distance_to(closest_threat) < WORKER_FLEE_RANGE:
            safe_spot: Point2 = self.townhalls.closest_to(worker).position
            if not is_already_moving_to(worker, safe_spot):
                worker.move(safe_spot)


def worker_micro(self: BotAI):
    prevent_PF_rush(self)
    defend_building_workers(self)
    flee_worker_threats(self)
