"""The army manager: decides what every combat unit does each step, on top of Ares' roles, squads, grids and
combat simulator.

Units live in one role at a time, each with its own controller and orders:

    ATTACKING           the main army - HOLD (pre-positioned at the hold point), ATTACK (push) or DEFEND (a threat at home)
    BASE_DEFENDER       a detachment split off to answer a specific enemy group near one of our bases (defense.py)
    CONTROL_GROUP_ONE   a small diversion squad sent at a different enemy base to split their defense
    HARASSING_BANSHEE / HARASSING_REAPER   harassers with their own targeting (units/banshees.py, units/reapers.py)
    SCOUTING            a hidden-base sweep, protected from everything else (scouting.py)

The strategic decision - push or hold - comes from the combat simulator run on our army against EVERYTHING we know
of the enemy army (enemy_tracker.py, no time decay), and from the old "attack at full supply" rule.
"""
import math
from dataclasses import replace
from typing import Dict, Iterable, List, NamedTuple, Optional, Set, Tuple

from loguru import logger

from ares.consts import EngagementResult, UnitRole, UnitTreeQueryType
from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.ares_compat import refresh_ability_cache
from bot.army.consts import (
    BANSHEE_TYPES,
    BIO_TYPES,
    CONTINUE_ATTACK_RESULT,
    CYCLONE_TYPES,
    DANGEROUS_STRUCTURES,
    DEDICATED_TYPES,
    ENEMY_NON_ARMY_TYPES,
    FIGHT_GHOST_MAX_AGE,
    GROUPED_FRACTION,
    KITE_IN_CONFIRM_SECONDS,
    KITE_IN_RESULT,
    LIBERATOR_TYPES,
    LOCAL_RETREAT_RESULT,
    MAX_FIGHTS_JUDGED,
    MEDIVAC_TYPES,
    NON_ARMY_TYPES,
    RAVEN_TYPES,
    REAPER_TYPES,
    SQUAD_RADIUS,
    STAGING_COOLDOWN,
    STAGING_TIMEOUT,
    START_ATTACK_RESULT,
    TANK_TYPES,
    UNCONFIRMED_RESULT,
    VIKING_TYPES,
)
from bot.army.context import ArmyContext
from bot.army.defense import BaseDefense
from bot.army.enemy_tracker import EnemyTracker
from bot.army.fight import FightEvaluator, Stance
from bot.army.local_fight import Fight, find_fights
from bot.army.orders import GroupOrders, Mode
from bot.army.positioning import Positioning
from bot.army.progress import ProgressWatch
from bot.army.scouting import HiddenBaseScouting
from bot.army.units.banshees import BansheeHarass
from bot.army.units.bio import BioController
from bot.army.units.common import attack_move
from bot.army.units.cyclones import CycloneController
from bot.army.units.generic import GenericController
from bot.army.units.liberators import LiberatorController
from bot.army.units.medivacs import MedivacController
from bot.army.units.ravens import RavenController
from bot.army.units.reapers import ReaperHarass
from bot.army.units.tanks import TankController
from bot.army.units.vikings import VikingController
from bot.pathing.order_utils import plain_point

# ---- strategic push -------------------------------------------------------------------------------------------------
MIN_PUSH_SUPPLY = 40                  # never start a sim-driven push with less army supply than this
INTEL_MIN_SUPPLY = 10.0               # the sim is only trusted once we have SEEN at least this much enemy army (alive or dead)...
INTEL_FRACTION = 0.5                  # ...and at least this fraction of our own army's supply
RETREAT_CONFIRM_SECONDS = 2.0         # the sim must say "losing" this long in a row before the push is called off
RETREAT_HOLD_SECONDS = 12.0           # after calling it off, run for the hold point instead of kiting locally this long
KEEP_ATTACK_SUPPLY_FRACTION = 0.5     # a push that has lost half its supply is over, whatever the sim says
MIN_ARMY_TO_KEEP_ATTACKING = 12       # ...and so is one that has shrunk below this many supply
RECALL_RADIUS = 80.0                  # the army only comes home to defend if it is at most this far from the threat
GIVE_UP_SECONDS = 180.0               # a target the army got stuck on (see ProgressWatch) is left alone this long
# ---- massing: the army fights as one -------------------------------------------------------------------------------------
# Against Protoss - Stalkers blink and kite whatever runs ahead, and skytoss trades better than bio does - a push starts later: with more
# army, more tightly grouped, and with the simulator (which knows nothing of blink or micro) surer of the fight
MIN_PUSH_SUPPLY_VS_PROTOSS = 60
START_ATTACK_RESULT_VS_PROTOSS = EngagementResult.VICTORY_OVERWHELMING
GROUPED_FRACTION_VS_PROTOSS = 0.9
# Against everyone: a push that has got strung out stops and waits for its tail (the head of an army that meets the enemy alone is lost one
# unit at a time)...
REGROUP_TAIL_DISTANCE = 45.0          # units this close to the army but outside its main squad are its tail, and are waited for
REGROUP_TAIL_FRACTION = 0.12          # ...when they are at least this share of the ground army (and at least 3 of them)
REGROUP_MAX_SECONDS = 12.0            # a pause never lasts longer than this...
REGROUP_COOLDOWN = 25.0               # ...and is not called again for this long (twice, four times as long when the tail never came)
# ...new units do not walk across the map one by one - whatever meets a lone unit picks it off - but wait at home for a wave
REINFORCE_HOME_RADIUS = 25.0          # units this close to the hold point and this far from the army are reinforcements waiting at home
REINFORCE_WAVE_FRACTION = 0.2         # a wave is this share of the army that is out there (in supply)...
REINFORCE_WAVE_SUPPLY = (8.0, 20.0)   # ...but not less than the first number, and never more than the second
REINFORCE_RELEASE_SECONDS = 20.0      # a wave that has been sent is not held back again for this long: all of it gets out of the door
# ---- diversion ------------------------------------------------------------------------------------------------------
DIVERSION_SQUAD_SIZE = 3
DIVERSION_MIN_MAIN_ARMY = 10          # only split one off if the main bio force can spare it
DIVERSION_ARRIVAL_RANGE = 10.0        # arrived at the target and nothing there -> done
# ---- roles ----------------------------------------------------------------------------------------------------------
MANAGED_ROLES = (
    UnitRole.ATTACKING, UnitRole.BASE_DEFENDER, UnitRole.CONTROL_GROUP_ONE, UnitRole.SCOUTING,
    UnitRole.HARASSING_BANSHEE, UnitRole.HARASSING_REAPER,
)


class MainPlan(NamedTuple):
    """What _main_orders decides for the units of the main army (three groups: the main body, its stragglers, the ones waiting at home)."""
    orders: GroupOrders
    stragglers: Units                 # core units outside the main squad: they rally in to it (or rush to a fight it is in)
    straggler_orders: GroupOrders
    waiting: Units                    # reinforcements standing at home until there are enough of them for a wave
    waiting_orders: GroupOrders


class ArmyManager:
    def __init__(self, ai):
        self.ai = ai
        self.tracker = EnemyTracker(ai)
        self.fight = FightEvaluator(ai)
        self.positioning = Positioning(ai)
        self.defense = BaseDefense(ai, self.fight)
        self.scouting = HiddenBaseScouting(ai)

        self.bio = BioController(ai)
        self.tanks = TankController(ai, self.positioning)
        self.cyclones = CycloneController(ai)
        self.medivacs = MedivacController(ai)
        self.ravens = RavenController(ai)
        self.vikings = VikingController(ai)
        self.liberators = LiberatorController(ai)
        self.generic = GenericController(ai)
        self.banshees = BansheeHarass(ai, self.positioning)
        self.reapers = ReaperHarass(ai)

        # unit tag -> since when its fight has been judged confident enough to walk into (see _fight_view)
        self._confident_since: Dict[int, float] = {}

        # main army push state
        self.attacking: bool = False
        self.attack_started: float = 0.0
        self.attack_start_supply: float = 0.0
        self.losing_since: Optional[float] = None
        self.retreating_until: float = 0.0
        self.anchor: Optional[Point2] = None
        self.global_result: Optional[EngagementResult] = None

        # assault staging state
        self.staging_since: Optional[float] = None
        self.staging_cooldown_until: float = 0.0

        # massing (see _regroup_pause and _waiting_at_home)
        self.grouped: bool = True                        # is the army together enough to start a push (as of the last step)
        self.regroup_point: Optional[Point2] = None      # where the army holds while its tail catches up (None: no pause is on)
        self.regroup_until: float = 0.0
        self.regroup_cooldown_until: float = 0.0
        self.regroup_timeouts: int = 0                   # pauses in a row that ended because they ran out of time, not because the tail arrived
        self.wave_until: float = 0.0                     # a reinforcement wave was sent: nobody at home is held back until then

        # stuck detection: an army (or the diversion squad) that stops getting anywhere on its way to a target
        self.attack_watch = ProgressWatch()
        self.diversion_watch = ProgressWatch()

        # diversion state
        self.diversion_tags: Set[int] = set()
        self.diversion_target: Optional[Point2] = None

        self._errors: Dict[str, int] = {}

    # ================================================================================================================
    # per-step entry point
    # ================================================================================================================
    def on_unit_destroyed(self, tag: int) -> None:
        self.tracker.remove(tag)
        self._confident_since.pop(tag, None)

    async def update(self, iteration: int) -> None:
        """One army step. Every stage is guarded: an exception in one part is logged and costs only that part this
        step, and if the core cannot even start, a minimal fallback keeps the army from standing idle."""
        ai = self.ai
        self.fight.begin_step()
        ctx = self._guard("context", self._begin_step)
        if ctx is None:
            self._guard("fallback", self._emergency_fallback)
            return

        self._guard("roles", self._sweep_roles, ctx)
        army = self._army_units()
        await self._aguard("abilities", refresh_ability_cache, ai, army)
        self._guard("prefetch", ctx.prefetch_near, army)

        role = ctx.mediator.get_units_from_role
        self._guard("scouting", self.scouting.update, ctx, role(role=UnitRole.ATTACKING))
        defense_groups, escalate_to = self._guard(
            "defense", self.defense.update, ctx, role(role=UnitRole.ATTACKING), role(role=UnitRole.BASE_DEFENDER)
        ) or ([], None)
        main_units: Units = role(role=UnitRole.ATTACKING)
        defenders: Units = role(role=UnitRole.BASE_DEFENDER)
        self._guard("fights", self._find_fights, ctx)
        for units, orders in defense_groups:
            orders.local_result, orders.unit_results = self._guard("defense fights", self._fight_view, ctx, units, Stance.DEFENDING) or (None, {})

        plan = self._guard("orders", self._main_orders, ctx, main_units, defenders, escalate_to)
        if plan is None:
            plan = MainPlan(self._hold_orders(ctx), Units([], ai), self._hold_orders(ctx), Units([], ai), self._hold_orders(ctx))
        main_orders, stragglers, straggler_orders = plan.orders, plan.stragglers, plan.straggler_orders

        diversion = self._guard("diversion", self._manage_diversion, ctx, main_units, main_orders)
        main_units = role(role=UnitRole.ATTACKING)     # the diversion may just have taken some (or given some back)
        stragglers = stragglers.tags_in(main_units.tags)
        waiting = plan.waiting.tags_in(main_units.tags)

        # ---- dispatch (each group isolated: one bug must never freeze the rest of the army) ----------------------
        groups: List[Tuple[str, Units, GroupOrders]] = []
        if stragglers:
            groups.append(("regroup", stragglers, straggler_orders))
        if waiting:
            groups.append(("waiting", waiting, plan.waiting_orders))
        apart = stragglers.tags | waiting.tags
        groups.append(("main", main_units.tags_not_in(apart) if apart else main_units, main_orders))
        for units, orders in defense_groups:
            groups.append(("defense", units, orders))
        if diversion is not None:
            groups.append(("diversion", diversion[0], diversion[1]))
        for name, units, orders in groups:
            await self._aguard(name, self._dispatch, units, orders, ctx)

        # a unit whose special role lost its controller this step (the code that owns BASE_DEFENDER / diversion units
        # failed, or an old task is gone) must not idle: hand it back to the main army and order it like the rest
        handled = {tag for _, units, _ in groups for tag in units.tags}
        orphans = (role(role=UnitRole.BASE_DEFENDER) | role(role=UnitRole.CONTROL_GROUP_ONE)).tags_not_in(handled)
        if orphans:
            for unit in orphans:
                ctx.mediator.assign_role(tag=unit.tag, role=UnitRole.ATTACKING)
            self.diversion_tags -= orphans.tags
            await self._aguard("orphans", self._dispatch, orphans, main_orders, ctx)

        self._guard("banshees", self._harass, self.banshees, role(role=UnitRole.HARASSING_BANSHEE), main_orders, ctx)
        self._guard("reapers", self._harass, self.reapers, role(role=UnitRole.HARASSING_REAPER), main_orders, ctx)

    def _begin_step(self) -> ArmyContext:
        self.tracker.update(self.ai.visible_enemy_units)
        return ArmyContext(self.ai, self.positioning)

    def _hold_orders(self, ctx: ArmyContext) -> GroupOrders:
        return GroupOrders(label="main", mode=Mode.HOLD, target=ctx.hold_point, hold_point=ctx.hold_point,
                           front=ctx.front, bio_position=ctx.bio_position, anchor=ctx.hold_point)

    # ----------------------------------------------------------------------------------------------------------------
    # guards
    # ----------------------------------------------------------------------------------------------------------------
    def _log_error(self, name: str, e: BaseException) -> None:
        count = self._errors.get(name, 0) + 1
        self._errors[name] = count
        if count <= 3 or count % 200 == 0:     # first few in full, then thin out - a per-step error would flood the log
            logger.opt(exception=e).error(f"[army] {name} failed (occurrence {count})")

    def _guard(self, name: str, func, *args):
        """Run one part of the army logic; log and swallow any exception so it can only cost that part this step.
        Returns the result, or None if it failed."""
        try:
            return func(*args)
        except Exception as e:  # noqa: BLE001
            self._log_error(name, e)
            return None

    async def _aguard(self, name: str, func, *args):
        try:
            return await func(*args)
        except Exception as e:  # noqa: BLE001
            self._log_error(name, e)
            return None

    def _emergency_fallback(self) -> None:
        """The army logic could not even start this step. Give every combat unit a plain attack-move (at full supply
        towards the enemy, otherwise to the hold point) so a bug never leaves the whole army standing still."""
        ai = self.ai
        try:
            target = self.positioning.attack_target() if self.positioning.is_maxed() else self.positioning.hold_point()
        except Exception:  # noqa: BLE001 - even the target lookup may be what broke; the start location always works
            target = ai.start_location
        for unit in self._army_units():
            if unit.type_id in TANK_TYPES and unit.type_id == UnitTypeId.SIEGETANKSIEGED:
                continue     # a sieged tank cannot move
            attack_move(unit, target)

    # ================================================================================================================
    # roles
    # ================================================================================================================
    def _army_units(self) -> Units:
        return self.ai.units.exclude_type(NON_ARMY_TYPES)

    def _sweep_roles(self, ctx: ArmyContext) -> None:
        """Every combat unit belongs to exactly one managed role. New units start in ATTACKING (banshees and reapers
        in their harass roles); anything that somehow ended up unassigned or in the wrong place is put right here."""
        mediator = ctx.mediator
        role_sets = mediator.get_unit_role_dict
        assigned: Dict[int, str] = {}
        for role in MANAGED_ROLES:
            for tag in role_sets.get(role.name, ()):
                assigned[tag] = role.name
        for unit in self._army_units():
            wanted: Optional[UnitRole] = None
            current = assigned.get(unit.tag)
            if unit.type_id in BANSHEE_TYPES:
                if current not in (UnitRole.HARASSING_BANSHEE.name, UnitRole.SCOUTING.name):
                    wanted = UnitRole.HARASSING_BANSHEE
            elif unit.type_id in REAPER_TYPES:
                if current not in (UnitRole.HARASSING_REAPER.name, UnitRole.SCOUTING.name):
                    wanted = UnitRole.HARASSING_REAPER
            elif current is None:
                wanted = UnitRole.ATTACKING
            if wanted is not None:
                mediator.assign_role(tag=unit.tag, role=wanted)

    # ================================================================================================================
    # main army
    # ================================================================================================================
    def _main_orders(
        self, ctx: ArmyContext, main_units: Units, defenders: Units, escalate_to: Optional[Point2]
    ) -> MainPlan:
        ai = self.ai
        now = ai.time
        hold = ctx.hold_point
        core = main_units.of_type(BIO_TYPES | TANK_TYPES | CYCLONE_TYPES)

        # ---- cohesion: who is in the main squad? ---------------------------------------------------------------
        stragglers = Units([], ai)
        squads = ctx.mediator.get_squads(role=UnitRole.ATTACKING, squad_radius=SQUAD_RADIUS) if main_units else []
        main_squad = self._pick_main_squad(squads)
        if main_squad is not None:
            self.anchor = plain_point(main_squad.squad_position)
            in_squad = main_squad.tags
            stragglers = core.tags_not_in(in_squad)
        elif not main_units:
            self.anchor = None
        grouped = True
        if core:
            needed = GROUPED_FRACTION_VS_PROTOSS if ai.enemy_race == Race.Protoss else GROUPED_FRACTION
            grouped = (core.amount - stragglers.amount) / core.amount >= needed
        self.grouped = grouped

        # ---- strategic decision: push or hold ------------------------------------------------------------------
        fighters = main_units | defenders
        self.global_result = self._global_result(fighters)
        self._update_push_state(now, fighters, grouped, escalate_to, self._push_result(ctx, fighters))

        defend_target = None
        if escalate_to is not None and (self.anchor is None or self.anchor.distance_to(escalate_to) <= RECALL_RADIUS):
            # the fight is at home and too big for a detachment - the whole army answers it if it can win, else holds. The whole army is
            # judged here on purpose (it is the one that would go), against the enemy at the threat, as us defending our own ground
            local = self.fight.evaluate(fighters, self._enemy_units_near(ctx, escalate_to, 25.0), stance=Stance.DEFENDING)
            if local >= EngagementResult.TIE:
                defend_target = escalate_to

        anchor = self.anchor if self.anchor is not None else hold
        staging: Optional[Point2] = None
        pausing = False
        fighting = bool(ctx.fights.fights_of(main_units))
        if defend_target is not None:
            mode, target = Mode.DEFEND, defend_target
        elif self.attacking:
            mode, target = Mode.ATTACK, self.positioning.attack_target()
            staging = self._staging(now, anchor, main_units)
            if staging is not None:
                target = staging
                self.attack_watch.reset()          # stopping there on purpose
            else:
                pause = self._regroup_pause(now, fighting, core, stragglers, anchor)
                if pause is not None:
                    target, anchor, pausing = pause, pause, True       # the head of the army holds, the tail comes to it
                    self.attack_watch.reset()      # ...on purpose
                else:
                    target = self._unstick(now, anchor, target, main_units)
        else:
            mode, target = Mode.HOLD, hold
            self.regroup_point = None
            self.staging_since = None
            self.attack_watch.reset()
        if mode == Mode.DEFEND:
            self.attack_watch.reset()

        # units standing at home while the army is out on the map wait there for a wave of reinforcements
        waiting = Units([], ai)
        if mode == Mode.ATTACK:
            waiting = self._waiting_at_home(now, main_units, anchor, hold)
            if waiting:
                stragglers = stragglers.tags_not_in(waiting.tags)

        # the fight the army is in, as its mode sees it (holding: they walk into us; attacking: we walk into them; answering a threat: both move)
        stance = {Mode.HOLD: Stance.DEFENDING, Mode.ATTACK: Stance.ATTACKING}.get(mode, Stance.MEETING)
        local_result, unit_results = self._fight_view(ctx, main_units, stance)
        orders = GroupOrders(
            label="main", mode=mode, target=target, hold_point=hold, front=ctx.front, bio_position=ctx.bio_position,
            anchor=anchor, local_result=local_result, unit_results=unit_results,
            retreating=(mode == Mode.HOLD and now < self.retreating_until),
            staging=staging, pausing=pausing,
            # the crowd standing at the hold position needs room: ~1 cell per unit, doubled for the gaps
            hold_radius=max(3.5, 1.1 * math.sqrt(max(1, main_units.amount))),
        )
        # stragglers rally in to the main squad before fighting: they are sent to its position, not into the enemy - but once that squad is
        # in a fight they rush to it (an attack-move: the steering that keeps a unit out of enemy fire would keep it out of the fight)
        regroup_orders = GroupOrders(
            label="regroup", mode=Mode.ATTACK if fighting and mode != Mode.HOLD else Mode.HOLD, target=anchor, hold_point=anchor,
            front=ctx.front, bio_position=anchor, anchor=anchor, local_result=None, retreating=False,
        )
        if mode == Mode.HOLD:
            stragglers = Units([], ai)      # everyone is already heading for the hold point
        waiting_orders = replace(self._hold_orders(ctx), label="waiting")
        return MainPlan(orders, stragglers, regroup_orders, waiting, waiting_orders)

    def _regroup_pause(self, now: float, fighting: bool, core: Units, stragglers: Units, anchor: Point2) -> Optional[Point2]:
        """While the tail of a strung-out push is still coming: the point where the head of it holds. A fight puts an end to it (nobody is
        waited for then: the stragglers rush in), and so does REGROUP_MAX_SECONDS - a tail that never arrives (stuck, dead) must not hold
        the army up for ever - after which there is no new pause for REGROUP_COOLDOWN."""
        tail = stragglers.closer_than(REGROUP_TAIL_DISTANCE, anchor) if stragglers else stragglers
        if self.regroup_point is not None:                                  # a pause is on
            if now < self.regroup_until and not fighting and tail.amount >= max(2, 0.04 * core.amount):
                return self.regroup_point
            if now >= self.regroup_until and not fighting:
                self.regroup_timeouts += 1                                  # the tail did not come: the next pause has to wait longer
            elif not fighting:
                self.regroup_timeouts = 0                                   # it did: the army is together again
            self.regroup_point = None
            self.regroup_cooldown_until = now + REGROUP_COOLDOWN * 2 ** min(3, max(0, self.regroup_timeouts - 1))
            return None
        if now < self.regroup_cooldown_until or fighting or tail.amount < max(3, REGROUP_TAIL_FRACTION * core.amount):
            return None
        self.regroup_point = anchor
        self.regroup_until = now + REGROUP_MAX_SECONDS
        logger.info(f"[army] the push is strung out ({tail.amount} of {core.amount} ground units are behind): holding at {anchor} for the tail")
        return anchor

    def _waiting_at_home(self, now: float, main_units: Units, anchor: Point2, hold: Point2) -> Units:
        """The units that stand at home while the army is out on the map (new ones, or ones that came back): they wait there until there
        are enough of them for a wave (a fifth of the army out there, between REINFORCE_WAVE_SUPPLY) and then go together. Sent one by one
        across the map they meet whatever the enemy has out there alone. A wave that has been sent is not held back again for
        REINFORCE_RELEASE_SECONDS, so that all of it gets out of the door."""
        ai = self.ai
        away = main_units.filter(lambda u: u.distance_to(hold) <= REINFORCE_HOME_RADIUS and u.distance_to(anchor) > REGROUP_TAIL_DISTANCE)
        if not away or now < self.wave_until:
            return Units([], ai)
        supply = sum(ai.calculate_supply_cost(u.type_id) for u in away)
        field = sum(ai.calculate_supply_cost(u.type_id) for u in main_units.closer_than(REGROUP_TAIL_DISTANCE, anchor))
        lowest, highest = REINFORCE_WAVE_SUPPLY
        if supply >= min(highest, max(lowest, REINFORCE_WAVE_FRACTION * field)):
            self.wave_until = now + REINFORCE_RELEASE_SECONDS
            logger.info(f"[army] a wave of {supply:.0f} supply leaves home for the army ({field:.0f} supply out there)")
            return Units([], ai)
        return away

    def _unstick(self, now: float, anchor: Point2, target: Point2, units: Units) -> Point2:
        """The army is marching on `target`. If it has stopped getting anywhere - jammed against terrain it cannot cross,
        in a dead end, or after a place it cannot reach at all (an island, a building floating over a cliff) - give that
        target up for a while and march on the next one instead of standing there forever."""
        fighting = any(u.weapon_cooldown > 0 for u in units)      # somebody fired: a fight explains standing still
        if not self.attack_watch.stuck(now, anchor, target, fighting):
            return target
        logger.warning(f"[army] stuck at {anchor} on the way to {target}: giving that target up for {GIVE_UP_SECONDS:.0f}s")
        self.positioning.give_up(target, GIVE_UP_SECONDS)
        self.attack_watch.reset()
        return self.positioning.attack_target()

    def _staging(self, now: float, anchor: Point2, main_units: Units) -> Optional[Point2]:
        """Pre-position before a fight against static defense or sieged tanks: stop at the standoff point, dig the tanks
        in, and only then commit. Bounded (timeout, then a cooldown) so it can never stall a push."""
        if now < self.staging_cooldown_until:
            return None
        tanks = main_units.of_type(TANK_TYPES)
        point = self.positioning.staging_point(anchor, tanks.amount)
        if point is None:
            self.staging_since = None
            return None
        if self.staging_since is None:
            self.staging_since = now
        waited = now - self.staging_since
        dug_in = tanks.of_type({UnitTypeId.SIEGETANKSIEGED}).closer_than(10, point).amount
        ready = tanks.amount > 0 and dug_in >= max(2, int(0.6 * tanks.amount))
        if (ready and waited >= 4.0) or waited > STAGING_TIMEOUT:
            self.staging_since = None
            self.staging_cooldown_until = now + STAGING_COOLDOWN
            return None
        return point

    @staticmethod
    def _pick_main_squad(squads):
        """The squad holding the most core ground units (bio, tanks, cyclones) - not merely the most units, or a knot of
        medivacs and vikings that flew ahead could pose as the army. Falls back to plain size when no squad has any."""
        if not squads:
            return None
        core = BIO_TYPES | TANK_TYPES | CYCLONE_TYPES
        return max(squads, key=lambda s: (sum(1 for u in s.squad_units if u.type_id in core), len(s.squad_units)))

    def _global_result(self, fighters: Units) -> Optional[EngagementResult]:
        """Our whole army against every enemy army unit we know of (visible or not), plus the static defense standing
        near where we would attack, judged as a march into a position they hold. That is the one place everybody is in the fight by
        design (a push is the whole army against the whole enemy); starting one is a commitment, hence `cautious`. None while we
        know nothing about their army."""
        known = self.tracker.known_army()
        if not known or not fighters:
            return None
        enemy: List[Unit] = list(known)
        structures = self.ai.enemy_structures
        if structures:
            target = self.positioning.attack_target()
            enemy.extend(s for s in structures.of_type(DANGEROUS_STRUCTURES) if s.position.distance_to(target) <= 20)
        return self.fight.evaluate(fighters, enemy, stance=Stance.ATTACKING, cautious=True, cache_seconds=1.0)

    def _push_result(self, ctx: ArmyContext, fighters: Units) -> Optional[EngagementResult]:
        """What a push in progress is judged by. While the army is fighting: that fight, on the units that can take part in it - not
        the whole army against everything we know of theirs, most of which is still on its way, on both sides. Otherwise the global
        result."""
        fights = ctx.fights.fights_of(fighters)
        if fights:
            result = self._judge(fights[0], Stance.ATTACKING)
            if result is not None:
                return result
        return self.global_result

    def _update_push_state(
        self, now: float, fighters: Units, grouped: bool, escalate_to: Optional[Point2], push_result: Optional[EngagementResult]
    ) -> None:
        ai = self.ai
        maxed = self.positioning.is_maxed()
        army_supply = float(ai.supply_army)
        result = self.global_result
        protoss = ai.enemy_race == Race.Protoss

        if not self.attacking:
            start = False
            if maxed:
                start = True
            elif (
                escalate_to is None and grouped and army_supply >= (MIN_PUSH_SUPPLY_VS_PROTOSS if protoss else MIN_PUSH_SUPPLY)
                and result is not None and now >= self.retreating_until
            ):
                # (a push called off because the fight it was in went badly is not restarted at once on the strength of the whole-army
                # verdict, which it did not agree with: the army gets the retreat time to pull back and regroup first)
                # trust the sim only if we have actually SEEN a meaningful part of their army (alive or dead)
                intel_ok = self.tracker.total_seen_supply() >= max(INTEL_MIN_SUPPLY, INTEL_FRACTION * army_supply)
                start = intel_ok and result >= (START_ATTACK_RESULT_VS_PROTOSS if protoss else START_ATTACK_RESULT)
            if start and fighters:
                self.attacking = True
                self.attack_started = now
                self.attack_start_supply = army_supply
                self.losing_since = None
            return

        # already pushing: stay committed unless the sim says we are clearly losing, or the push has melted away. While the army is
        # fighting, "the sim" is asked about THAT fight (see _push_result), not about the whole matchup
        result = push_result
        stop = False
        if result is not None and result < CONTINUE_ATTACK_RESULT:
            self.losing_since = self.losing_since if self.losing_since is not None else now
            if now - self.losing_since >= RETREAT_CONFIRM_SECONDS and not maxed:
                stop = True
        else:
            self.losing_since = None
        if (
            self.attack_start_supply > 0
            and army_supply < KEEP_ATTACK_SUPPLY_FRACTION * self.attack_start_supply
            and (result is None or result < EngagementResult.VICTORY_CLOSE)
        ):
            stop = True
        if not maxed and army_supply < MIN_ARMY_TO_KEEP_ATTACKING:
            stop = True
        if not fighters:
            stop = True
        if stop:
            self.attacking = False
            self.losing_since = None
            self.retreating_until = now + RETREAT_HOLD_SECONDS

    # ================================================================================================================
    # local fight assessment
    # ================================================================================================================
    def _enemy_units_near(self, ctx: ArmyContext, position: Point2, radius: float) -> Units:
        """Visible enemy units and completed static defenses within `radius` of `position` (sim input)."""
        near = ctx.mediator.get_units_in_range(
            start_points=[position], distances=radius, query_tree=UnitTreeQueryType.AllEnemy,
        )[0]
        return Units([e for e in near if not e.is_memory and e.type_id not in ENEMY_NON_ARMY_TYPES], self.ai)

    def _fight_enemies(self) -> List[Unit]:
        """Everything hostile that may be in a fight: what we see, what dropped out of sight a moment ago (Ares' ghosts, where they
        were last seen: a fight against the front of an army is not a fight against only the part of it we happen to see), and the
        static defenses we know of."""
        ai = self.ai
        enemies = [e for e in ai.enemy_units if not e.is_memory or e.age <= FIGHT_GHOST_MAX_AGE]
        enemies.extend(ai.enemy_structures)
        return enemies

    def _find_fights(self, ctx: ArmyContext) -> None:
        """Sort out who is in which fight this step (local_fight.py): the units of every fighting role against the enemy units they
        can get at, or that can get at them, within a few seconds. Everything else is not part of a fight yet."""
        role = ctx.mediator.get_units_from_role
        fighters = role(role=UnitRole.ATTACKING) | role(role=UnitRole.BASE_DEFENDER) | role(role=UnitRole.CONTROL_GROUP_ONE)
        own = self.fight.clean_own(fighters)
        enemy = self.fight.clean_enemy(self._fight_enemies(), any(u.is_flying for u in own), True)
        ctx.fights = find_fights(own, enemy)

    def _judge(self, fight: Fight, stance: Stance, cautious: bool = False) -> Optional[EngagementResult]:
        """The simulator's verdict on one fight; None for the small ones past the per-step budget (MAX_FIGHTS_JUDGED)."""
        if fight.rank >= MAX_FIGHTS_JUDGED:
            return None
        return self.fight.evaluate(fight.own, fight.enemy, stance=stance, engaged=fight.engaged, cautious=cautious)

    def _fight_view(
        self, ctx: ArmyContext, units: Units, stance: Stance
    ) -> Tuple[Optional[EngagementResult], Dict[int, EngagementResult]]:
        """What a group's controllers are told about its fights: (how the group's biggest fight goes, as its mode sees it; and per unit
        of the group how the fight that unit is in looks as an advance - the "kite in" question). That question is only asked of a fight
        that is under way: while it is still an approach, walking up to sieged tanks or spines under their fire is exactly what "kite
        in" must not do, so nobody is confident yet. It is always answered cautiously, and never better than UNCONFIRMED_RESULT until
        the verdict has held for KITE_IN_CONFIRM_SECONDS."""
        fights = ctx.fights.fights_of(units)
        group = self._judge(fights[0], stance) if fights else None
        tags = units.tags
        now = self.ai.time
        per_unit: Dict[int, EngagementResult] = {}
        for fight in fights:
            if not fight.engaged:
                continue
            advance = self._judge(fight, Stance.ATTACKING, cautious=True)
            if advance is None:
                continue
            for unit in fight.own:
                if unit.tag in tags:
                    per_unit[unit.tag] = advance
        for tag in tags:
            advance = per_unit.get(tag)
            if advance is None or advance < KITE_IN_RESULT:
                self._confident_since.pop(tag, None)
            elif now - self._confident_since.setdefault(tag, now) < KITE_IN_CONFIRM_SECONDS:
                per_unit[tag] = UNCONFIRMED_RESULT
        return group, per_unit

    # ================================================================================================================
    # diversion
    # ================================================================================================================
    def _manage_diversion(
        self, ctx: ArmyContext, main_units: Units, main_orders: GroupOrders
    ) -> Optional[Tuple[Units, GroupOrders]]:
        ai = self.ai
        role = ctx.mediator.get_units_from_role
        squad: Units = role(role=UnitRole.CONTROL_GROUP_ONE)
        self.diversion_tags &= squad.tags

        def dissolve() -> None:
            for unit in squad:
                ctx.mediator.assign_role(tag=unit.tag, role=UnitRole.ATTACKING)
            self.diversion_tags = set()
            self.diversion_target = None

        if squad and (main_orders.mode != Mode.ATTACK or squad.amount < 2):
            dissolve()
            self.diversion_watch.reset()
            return None

        if not squad:
            bio = main_units.of_type(BIO_TYPES)
            if main_orders.mode == Mode.ATTACK and bio.amount >= DIVERSION_MIN_MAIN_ARMY and self.diversion_target is None:
                target = self.positioning.diversion_target(main_orders.target)
                if target is not None:
                    chosen = bio.sorted_by_distance_to(target).take(DIVERSION_SQUAD_SIZE)
                    for unit in chosen:
                        ctx.mediator.assign_role(tag=unit.tag, role=UnitRole.CONTROL_GROUP_ONE)
                    self.diversion_tags = chosen.tags
                    self.diversion_target = target
                    squad = role(role=UnitRole.CONTROL_GROUP_ONE)
            if not squad:
                return None

        target = self.diversion_target
        if target is None:
            dissolve()
            return None
        center = Point2((sum(u.position.x for u in squad) / squad.amount, sum(u.position.y for u in squad) / squad.amount))
        # arrived and nothing left to kill there: done (a new target is picked on a later step if still worthwhile)
        if center.distance_to(target) <= DIVERSION_ARRIVAL_RANGE and not ai.enemy_structures.closer_than(15, target):
            dissolve()
            self.diversion_watch.reset()
            return None
        # stuck on the way (see ProgressWatch): give that place up and let the squad rejoin the army
        if self.diversion_watch.stuck(ai.time, center, target, any(u.weapon_cooldown > 0 for u in squad)):
            logger.warning(f"[army] diversion squad stuck at {center} on the way to {target}: giving that target up")
            self.positioning.give_up(target, GIVE_UP_SECONDS)
            dissolve()
            self.diversion_watch.reset()
            return None

        local, unit_results = self._fight_view(ctx, squad, Stance.ATTACKING)
        if local is not None and local <= LOCAL_RETREAT_RESULT:
            anchor = main_orders.anchor if main_orders.anchor is not None else ctx.hold_point
            orders = GroupOrders(label="diversion", mode=Mode.HOLD, target=anchor, hold_point=anchor, front=ctx.front,
                                 bio_position=anchor, anchor=anchor, local_result=local, unit_results=unit_results, retreating=True)
        else:
            orders = GroupOrders(label="diversion", mode=Mode.ATTACK, target=target, hold_point=ctx.hold_point,
                                 front=ctx.front, bio_position=ctx.bio_position, anchor=center, local_result=local,
                                 unit_results=unit_results)
        return squad, orders

    # ================================================================================================================
    # dispatch
    # ================================================================================================================
    async def _dispatch(self, units: Units, orders: GroupOrders, ctx: ArmyContext) -> None:
        if not units:
            return
        self.bio.control(units.of_type(BIO_TYPES), orders, ctx)
        self.tanks.control(units.of_type(TANK_TYPES), orders, ctx)
        self.cyclones.control(units.of_type(CYCLONE_TYPES), orders, ctx)
        self.vikings.control(units.of_type(VIKING_TYPES), orders, ctx)
        self.liberators.control(units.of_type(LIBERATOR_TYPES), orders, ctx)
        self.medivacs.control(units.of_type(MEDIVAC_TYPES), orders, ctx)
        await self.ravens.control(units.of_type(RAVEN_TYPES), orders, ctx)
        # banshees and reapers are never in these groups (_sweep_roles keeps them in their harass roles)
        self.generic.control(units.exclude_type(DEDICATED_TYPES), orders, ctx)

    def _harass(self, controller, units: Units, main_orders: GroupOrders, ctx: ArmyContext) -> None:
        if not units:
            return
        # harassers take their targets from their own logic; the orders only carry the hold point (where to repair)
        controller.control(units, main_orders, ctx)
