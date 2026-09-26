"""Base defense: answer enemies near our bases with just enough units, not the whole army.

A handful of enemy units (a run-by, a drop, a harassing banshee) does not need the entire force pulled off whatever it
is doing. For every enemy group near one of our structures the smallest set of nearby mobile units that beats it with a
healthy margin (Ares combat simulator) is split off into the BASE_DEFENDER role and sent to deal with it, then handed
back to the main army when the threat is gone. If even everything mobile nearby cannot win decisively - or the answer
would take most of the army anyway - the fight is escalated: the whole army defends.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from ares.consts import UnitRole, UnitTreeQueryType
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.army.consts import (
    BASE_THREAT_RADIUS,
    DETACHMENT_RESULT,
    ENEMY_NON_ARMY_TYPES,
    THREAT_CLUSTER_RADIUS,
)
from bot.army.context import ArmyContext
from bot.army.fight import FightEvaluator, Stance
from bot.army.orders import GroupOrders, Mode

# units that may be split off to defend: mobile damage dealers. Tanks and Liberators defend by being pre-positioned,
# medivacs/ravens travel with the main army, banshees/reapers have their own harass role
DEFENDER_TYPES = frozenset({U.MARINE, U.MARAUDER, U.CYCLONE, U.HELLION, U.HELLIONTANK, U.THOR, U.THORAP, U.GHOST,
                            U.VIKINGFIGHTER, U.BATTLECRUISER})
RESPONSE_RADIUS = 70.0            # only units this close (straight line) to a threat are candidates to answer it
ESCALATE_FRACTION = 0.6           # a detachment bigger than this share of the eligible units is "the whole army" anyway
RELEASE_DELAY = 5.0               # threat gone for this long -> defenders go back to the main army
MIN_DETACHMENT = 3                # always send at least this many against a real threat
TASK_MATCH_DISTANCE = 20.0        # a threat cluster this close to an existing task's centre is the same threat


@dataclass
class Threat:
    units: List[Unit]
    center: Point2


@dataclass
class DefenseTask:
    center: Point2
    threat_tags: Set[int]
    defender_tags: Set[int] = field(default_factory=set)
    last_threat_time: float = 0.0
    escalated: bool = False


def can_hit(unit: Unit, enemy: Unit) -> bool:
    return unit.can_attack_air if enemy.is_flying else unit.can_attack_ground


def cluster_units(units: List[Unit], radius: float) -> List[List[Unit]]:
    """Greedy single-link clustering by position."""
    clusters: List[List[Unit]] = []
    for u in units:
        placed = False
        for cluster in clusters:
            if any(u.position.distance_to(m.position) <= radius for m in cluster):
                cluster.append(u)
                placed = True
                break
        if not placed:
            clusters.append([u])
    # a unit can bridge two clusters - merge those
    merged = True
    while merged:
        merged = False
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                if any(a.position.distance_to(b.position) <= radius for a in clusters[i] for b in clusters[j]):
                    clusters[i].extend(clusters[j])
                    del clusters[j]
                    merged = True
                    break
            if merged:
                break
    return clusters


class BaseDefense:
    def __init__(self, ai, fight: FightEvaluator):
        self.ai = ai
        self.fight = fight
        self.tasks: List[DefenseTask] = []

    # ------------------------------------------------------------------------------------------------------------
    def find_threats(self, ctx: ArmyContext) -> List[Threat]:
        # (an Auto-Turret - a Raven's, dropped next to the enemy's army - is not a base: enemies around one are not attacking us)
        structures = [s for s in self.ai.structures if s.type_id != U.AUTOTURRET]
        if not structures:
            return []
        near_lists = ctx.mediator.get_units_in_range(
            start_points=structures,
            distances=BASE_THREAT_RADIUS,
            query_tree=UnitTreeQueryType.AllEnemy,
        )
        seen: Dict[int, Unit] = {}
        visited: Set[int] = set()
        for units in near_lists:
            for e in units:
                # an army standing near a base is within reach of dozens of its structures: each unit is looked at once, not once per structure
                if id(e) in visited:
                    continue
                visited.add(id(e))
                if e.is_memory or e.is_structure or e.is_hallucination or e.type_id in ENEMY_NON_ARMY_TYPES:
                    continue
                seen[e.tag] = e
        return [
            Threat(units=cluster, center=Point2((sum(u.position.x for u in cluster) / len(cluster),
                                                 sum(u.position.y for u in cluster) / len(cluster))))
            for cluster in cluster_units(list(seen.values()), THREAT_CLUSTER_RADIUS)
        ]

    # ------------------------------------------------------------------------------------------------------------
    def update(
        self, ctx: ArmyContext, main_units: Units, defender_units: Units
    ) -> Tuple[List[Tuple[Units, GroupOrders]], Optional[Point2]]:
        """Returns (groups of detached defenders with their orders, threat position the WHOLE army should defend against
        or None). Re-roles units through the mediator as it goes."""
        now = self.ai.time
        threats = self.find_threats(ctx)
        mobile_pool = [u for u in main_units if u.type_id in DEFENDER_TYPES]
        alive_defenders: Dict[int, Unit] = {u.tag: u for u in defender_units}

        # match threats to tasks
        active: List[Tuple[DefenseTask, Threat]] = []
        unmatched = list(self.tasks)
        for threat in threats:
            task = None
            for candidate in unmatched:
                if candidate.center.distance_to(threat.center) <= TASK_MATCH_DISTANCE:
                    task = candidate
                    break
            if task is None:
                task = DefenseTask(center=threat.center, threat_tags={u.tag for u in threat.units})
                self.tasks.append(task)
            else:
                unmatched.remove(task)
            task.center = threat.center
            task.threat_tags = {u.tag for u in threat.units}
            task.last_threat_time = now
            active.append((task, threat))

        escalate_to: Optional[Point2] = None
        groups: List[Tuple[Units, GroupOrders]] = []
        claimed: Set[int] = set()

        for task, threat in active:
            current = [alive_defenders[t] for t in task.defender_tags if t in alive_defenders]
            candidates = sorted(
                (u for u in mobile_pool
                 if u.tag not in claimed and u.tag not in task.defender_tags
                 and u.position.distance_to(threat.center) <= RESPONSE_RADIUS
                 and any(can_hit(u, e) for e in threat.units)),
                key=lambda u: u.position.distance_to(threat.center),
            )
            ordered: List[Unit] = current + candidates
            eligible_total = len(ordered)
            if eligible_total == 0:
                # nobody can answer it with a detachment - the whole army has to
                task.escalated = True
                if escalate_to is None:
                    escalate_to = threat.center
                continue

            # sending units at a threat is a commitment, and the detachment walks up to the raiders (they do not walk into it): judged
            # with everything in contact from the start, no defender's volley counted on (see FightEvaluator.plan)
            subset, result = self.fight.smallest_winning_subset(
                ordered, threat.units, target=DETACHMENT_RESULT, min_size=min(MIN_DETACHMENT, eligible_total), stance=Stance.MEETING,
            )
            if subset is None or len(subset) > ESCALATE_FRACTION * len(mobile_pool + list(defender_units)):
                task.escalated = True
                if escalate_to is None:
                    escalate_to = threat.center
                # keep what is already detached fighting rather than yanking them back mid-fight
                chosen = current
            else:
                task.escalated = False
                # never shrink a detachment while its threat is alive - only grow it
                chosen = list(subset) if len(subset) >= len(current) else current
                for u in chosen:
                    if u.tag not in task.defender_tags:
                        ctx.mediator.assign_role(tag=u.tag, role=UnitRole.BASE_DEFENDER)
                        task.defender_tags.add(u.tag)
            claimed.update(u.tag for u in chosen)

            if chosen:
                units = Units(chosen, self.ai)
                # how their fights go is filled in by the army manager, from the fights it found (ArmyManager._fight_view)
                groups.append((units, GroupOrders(
                    label="defense", mode=Mode.DEFEND, target=threat.center, hold_point=ctx.hold_point,
                    front=ctx.front, bio_position=ctx.bio_position, anchor=threat.center,
                )))

        # release the defenders of threats that are gone
        for task in list(self.tasks):
            if any(task is t for t, _ in active):
                continue
            if now - task.last_threat_time >= RELEASE_DELAY:
                for tag in task.defender_tags:
                    if tag in alive_defenders:
                        ctx.mediator.assign_role(tag=tag, role=UnitRole.ATTACKING)
                self.tasks.remove(task)
            else:
                # threat just left vision: keep them where they are for a moment (they keep fighting what they see)
                current = [alive_defenders[t] for t in task.defender_tags if t in alive_defenders]
                if current:
                    groups.append((Units(current, self.ai), GroupOrders(
                        label="defense", mode=Mode.DEFEND, target=task.center, hold_point=ctx.hold_point,
                        front=ctx.front, bio_position=ctx.bio_position, anchor=task.center, local_result=None,
                    )))

        # forget tasks whose defenders all died
        for task in list(self.tasks):
            task.defender_tags &= set(alive_defenders) | {u.tag for u in main_units}
        return groups, escalate_to
