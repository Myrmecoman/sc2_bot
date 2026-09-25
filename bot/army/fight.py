"""How likely is a fight to go our way?  A defensive layer over the Rust combat simulator (`sc2_helper`) that Ares runs.

What the wrapper adds: input filtering (workers, changelings, structures that make the sim misbehave), a short-lived result
cache, a per-step call budget, a plain power-ratio fallback so a simulator failure degrades a decision instead of crashing the step -
and the simulator's settings, chosen for the situation the fight is judged in (`Stance`).

What the settings do (probed with the real simulator; none of it is in its documentation):

* The simulator ignores where units stand. The same armies give the same answer 2 or 110 cells apart, in a ball or strung out.
  Who takes part is decided by the caller (local_fight.py) - and every unit it is given fights from the first second.
* `timing_adjust` gives the side that OUT-RANGES the other a free volley while the other walks up to it: marines against zealots,
  sieged tanks against zerglings, spine crawlers against marines. Without it every unit is in contact from the start.
* `defender_player` says who walks and who holds: 1 = our units hold their ground and the enemy walks into them, 2 = the enemy
  holds and we walk in (it has no effect without `timing_adjust`). A side that holds never approaches: zerglings that "hold" against
  our tanks are never reached by them, so the tanks win without a scratch.
* A unit that cannot move (sieged tank, burrowed unit, static defense) never arrives when it is on the side that walks: with
  `timing_adjust` and nobody holding - or the wrong side holding - 20 marines beat 4 sieged tanks without a loss, and 6 sieged tanks
  do no damage at all to 16 zerglings. Such a fight must be judged without the approach model.
* `good_positioning` ("units are decently split") changes almost nothing without `timing_adjust`.
"""
import asyncio
from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from loguru import logger

from ares.consts import EngagementResult
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit
from sc2.units import Units

from bot.army.consts import (
    ANTI_AIR_ONLY_STRUCTURES,
    DANGEROUS_STRUCTURES,
    DETACHMENT_RESULT,
    ENEMY_NON_ARMY_TYPES,
    ENEMY_WORKER_TYPES,
    NON_ARMY_TYPES,
)

MAX_SIM_CALLS_PER_STEP = 24          # hard cap on simulator calls in one step, past which cached/fallback answers are used
_CACHE_MAX_AGE = 3.0                 # entries older than this (game seconds) are dropped
_VICTORY = EngagementResult.VICTORY_EMPHATIC
_LOSS = EngagementResult.LOSS_EMPHATIC


class Stance(Enum):
    """The situation a fight is judged in: who walks up to whom."""
    ATTACKING = auto()    # we walk into a position they hold: their base, static defense, sieged tanks, an army standing its ground
    DEFENDING = auto()    # we hold a position (the hold point, one of our bases) and they walk into us
    MEETING = auto()      # neither, or a fight that is under way: everything is in contact from the start


@dataclass(frozen=True)
class SimSetup:
    """The simulator's settings for one run (the options that change from fight to fight; see the module docstring)."""
    timing_adjust: bool = False
    defender_player: int = 0          # 0 = nobody holds, 1 = we hold, 2 = they hold
    good_positioning: bool = False


BASELINE = SimSetup()                 # everything in contact from the start: the neutral, always usable model


def engagement_result(won: bool, health_left: float, own: Sequence[Unit], enemy: Sequence[Unit]) -> EngagementResult:
    """The simulator's answer on Ares' EngagementResult scale. This is `CombatSimManager.can_win_fight`'s own conversion (it has no
    function for it, and `can_win_fight` cannot say who holds position), thresholds included."""
    own_health = sum(u.health for u in own) + 1e-16
    enemy_health = sum(u.health + u.shield for u in enemy) + 1e-16
    if won:
        share = health_left / own_health
        if share >= 0.9:
            return EngagementResult.VICTORY_EMPHATIC
        if share >= 0.75:
            return EngagementResult.VICTORY_OVERWHELMING
        if share >= 0.6:
            return EngagementResult.VICTORY_DECISIVE
        if share > 0.4:
            return EngagementResult.VICTORY_CLOSE
        if share > 0.2:
            return EngagementResult.VICTORY_MARGINAL
    else:
        share = health_left / enemy_health
        if share >= 0.9:
            return EngagementResult.LOSS_EMPHATIC
        if share >= 0.75:
            return EngagementResult.LOSS_OVERWHELMING
        if share > 0.6:
            return EngagementResult.LOSS_DECISIVE
        if share > 0.4:
            return EngagementResult.LOSS_CLOSE
        if share > 0.2:
            return EngagementResult.LOSS_MARGINAL
    return EngagementResult.TIE


class FightEvaluator:
    def __init__(self, ai):
        self.ai = ai
        self.sim_calls_this_step: int = 0
        self.total_sim_calls: int = 0
        self.total_fallbacks: int = 0
        self._cache: Dict[tuple, Tuple[float, EngagementResult]] = {}
        self._configured = False

    # ------------------------------------------------------------------------------------------------------------
    # housekeeping
    # ------------------------------------------------------------------------------------------------------------
    def begin_step(self) -> None:
        self.sim_calls_this_step = 0
        now = self.ai.time
        if self._cache and len(self._cache) > 64:
            self._cache = {k: v for k, v in self._cache.items() if now - v[0] <= _CACHE_MAX_AGE}

    def _configure_simulator(self) -> None:
        """Set the simulator options that do not change from fight to fight (timing, positioning, who holds and workers are set
        per run, see `_simulate`). The simulator object is shared, so this needs doing once."""
        if self._configured:
            return
        self._configured = True
        try:
            sim = self.ai.manager_hub.combat_sim_manager.combat_sim
            sim.bad_micro(False)
            sim.enable_splash(True)
            sim.enable_surround_limits(True)
            sim.enable_melee_blocking(True)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[fight] could not configure combat simulator ({e!r}); using its defaults")

    # ------------------------------------------------------------------------------------------------------------
    # input filtering
    # ------------------------------------------------------------------------------------------------------------
    def clean_own(self, own: Iterable[Unit]) -> List[Unit]:
        return [u for u in own if u.type_id not in NON_ARMY_TYPES and not u.is_structure]

    def clean_enemy(self, enemy: Iterable[Unit], own_has_air: bool, workers_do_no_damage: bool) -> List[Unit]:
        result: List[Unit] = []
        for u in enemy:
            type_id = u.type_id
            if u.is_hallucination:
                continue
            if u.is_structure:
                # only completed static defenses matter to a fight, and anti-air-only ones only if we have air
                if type_id not in DANGEROUS_STRUCTURES or u.build_progress < 1:
                    continue
                if type_id in ANTI_AIR_ONLY_STRUCTURES and not own_has_air:
                    continue
                result.append(u)
                continue
            if type_id in ENEMY_NON_ARMY_TYPES and type_id not in ENEMY_WORKER_TYPES:
                continue
            if type_id in ENEMY_WORKER_TYPES and workers_do_no_damage:
                continue
            result.append(u)
        return result

    # ------------------------------------------------------------------------------------------------------------
    # evaluation
    # ------------------------------------------------------------------------------------------------------------
    @staticmethod
    def plan(
        stance: Stance, engaged: bool, cautious: bool, own: Sequence[Unit], enemy: Sequence[Unit]
    ) -> List[Tuple[SimSetup, Sequence[Unit]]]:
        """The simulator runs a fight is judged by: (settings, our units in it). The worst of them is the answer.

        A fight that is under way (`engaged`: each side already has a weapon on the other) has no approach left to model, and neither
        has a MEETING - everything is in contact, the BASELINE. Otherwise the approach is modelled as the stance says, unless the units
        that would have to walk cannot (see the module docstring), in which case the BASELINE is all that can be trusted. `cautious`
        (decisions that commit units forward: starting a push, kiting in) never trusts the stance's model alone: the baseline has to
        agree, so the answer is never more optimistic than "everything in contact from the start"."""
        baseline = (BASELINE, own)
        if engaged or stance is Stance.MEETING:
            return [baseline]
        if stance is Stance.ATTACKING:
            # they hold, we walk in: our sieged tanks and other units that cannot walk are left out of that run - with them it
            # would be the enemy that walks, and it does not
            mobile = [u for u in own if u.movement_speed > 0]
            if not mobile:
                return [baseline]
            model = (SimSetup(timing_adjust=True, defender_player=2, good_positioning=False), mobile)
        else:
            # we hold, they walk in: enemy units that cannot walk (sieged tanks, static defense) would never arrive
            if any(u.movement_speed <= 0 for u in enemy):
                return [baseline]
            model = (SimSetup(timing_adjust=True, defender_player=1, good_positioning=True), own)
        return [baseline, model] if cautious else [model]

    def evaluate(
        self,
        own: Iterable[Unit],
        enemy: Iterable[Unit],
        *,
        stance: Stance = Stance.MEETING,
        engaged: bool = False,
        cautious: bool = False,
        workers_do_no_damage: bool = True,
        cache_seconds: float = 0.5,
    ) -> EngagementResult:
        """Predicted result of `own` fighting `enemy` in the given situation (see `plan`). Empty enemy -> emphatic victory, empty
        own -> emphatic loss. Never raises."""
        own_list = self.clean_own(own)
        own_has_air = any(u.is_flying for u in own_list)
        enemy_list = self.clean_enemy(enemy, own_has_air, workers_do_no_damage)
        if not enemy_list:
            return _VICTORY
        if not own_list:
            return _LOSS
        runs = self.plan(stance, engaged, cautious, own_list, enemy_list)
        return min(self._simulate(mine, enemy_list, setup, workers_do_no_damage, cache_seconds) for setup, mine in runs)

    def _simulate(
        self, own: Sequence[Unit], enemy: Sequence[Unit], setup: SimSetup, workers_do_no_damage: bool, cache_seconds: float
    ) -> EngagementResult:
        key = (
            tuple(sorted(u.tag for u in own)),
            tuple(sorted(u.tag for u in enemy)),
            setup, workers_do_no_damage,
        )
        now = self.ai.time
        cached = self._cache.get(key)
        if cached is not None and now - cached[0] <= cache_seconds:
            return cached[1]

        if self.sim_calls_this_step >= MAX_SIM_CALLS_PER_STEP:
            # over budget: a slightly stale answer beats a new expensive one, and beats nothing
            if cached is not None:
                return cached[1]
            return self._fallback(own, enemy)

        self._configure_simulator()
        try:
            self.sim_calls_this_step += 1
            self.total_sim_calls += 1
            # Ares' can_win_fight sets timing, positioning and workers the same way but cannot pass `defender_player`
            sim = self.ai.manager_hub.combat_sim_manager.combat_sim
            sim.enable_timing_adjustment(setup.timing_adjust)
            sim.assume_reasonable_positioning(setup.good_positioning)
            sim.workers_do_no_damage(workers_do_no_damage)
            won, health_left = sim.predict_engage(
                Units(list(own), self.ai), Units(list(enemy), self.ai), optimistic=False, defender_player=setup.defender_player
            )
            result = engagement_result(won, health_left, own, enemy)
        except BaseException as e:  # noqa: BLE001 - the Rust side can panic with a BaseException subclass
            if isinstance(e, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
                raise
            logger.warning(f"[fight] combat simulator failed ({e!r}); using power-ratio fallback")
            return self._fallback(own, enemy)
        self._cache[key] = (now, result)
        return result

    # ------------------------------------------------------------------------------------------------------------
    # convenience decisions
    # ------------------------------------------------------------------------------------------------------------
    def smallest_winning_subset(
        self,
        candidates: Sequence[Unit],
        enemy: Iterable[Unit],
        *,
        target: EngagementResult = DETACHMENT_RESULT,
        min_size: int = 1,
        **kwargs,
    ) -> Tuple[Optional[List[Unit]], EngagementResult]:
        """`candidates` is ordered best-first (usually nearest-first). Returns the shortest prefix that reaches
        `target` (binary search - more units never makes a fight worse) together with the result it reached, or
        (None, result_with_everyone) if even all of them fall short."""
        enemy_list = list(enemy)
        n = len(candidates)
        if n == 0:
            return None, _LOSS
        everyone = self.evaluate(candidates, enemy_list, **kwargs)
        if everyone < target:
            return None, everyone
        # invariant: the prefix of length `hi` reaches the target (true for n, checked above)
        lo, hi = max(1, min_size), n
        best_result = everyone
        while lo < hi:
            mid = (lo + hi) // 2
            result = self.evaluate(candidates[:mid], enemy_list, **kwargs)
            if result >= target:
                hi, best_result = mid, result
            else:
                lo = mid + 1
        return list(candidates[:max(hi, min_size)]), best_result

    # ------------------------------------------------------------------------------------------------------------
    # fallback
    # ------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _power(unit: Unit) -> float:
        return max(unit.ground_dps, unit.air_dps) * (unit.health + unit.shield)

    def _fallback(self, own: Sequence[Unit], enemy: Sequence[Unit]) -> EngagementResult:
        """Crude dps x hit-points comparison, only used when the real simulator is unavailable/over budget."""
        self.total_fallbacks += 1
        own_power = sum(self._power(u) for u in own)
        enemy_power = sum(self._power(u) for u in enemy)
        if enemy_power <= 0:
            return _VICTORY
        ratio = own_power / enemy_power
        if ratio >= 4.0:
            return EngagementResult.VICTORY_EMPHATIC
        if ratio >= 2.5:
            return EngagementResult.VICTORY_OVERWHELMING
        if ratio >= 1.6:
            return EngagementResult.VICTORY_DECISIVE
        if ratio >= 1.15:
            return EngagementResult.VICTORY_CLOSE
        if ratio >= 0.85:
            return EngagementResult.TIE
        if ratio >= 0.6:
            return EngagementResult.LOSS_CLOSE
        if ratio >= 0.35:
            return EngagementResult.LOSS_DECISIVE
        return EngagementResult.LOSS_OVERWHELMING
