"""How likely is a fight to go our way?  A thin, defensive layer over Ares' `mediator.can_win_fight`.

Ares hands the actual prediction to the Rust combat simulator (`sc2_helper`). This wrapper adds what a bot that
calls it dozens of times per step needs: input filtering (workers, changelings, structures that make the sim
misbehave), a short-lived result cache, a per-step call budget, and a plain power-ratio fallback so a simulator
failure degrades a decision instead of crashing the step.
"""
import asyncio
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
        """Set the simulator options Ares' can_win_fight does NOT set itself (it only sets timing, positioning and
        workers per call). The simulator object is shared, so this needs doing once."""
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
    def evaluate(
        self,
        own: Iterable[Unit],
        enemy: Iterable[Unit],
        *,
        timing_adjust: bool = False,
        good_positioning: bool = False,
        workers_do_no_damage: bool = True,
        cache_seconds: float = 0.5,
    ) -> EngagementResult:
        """Predicted result of `own` fighting `enemy`. Empty enemy -> emphatic victory, empty own -> emphatic loss.
        Never raises."""
        own_list = self.clean_own(own)
        own_has_air = any(u.is_flying for u in own_list)
        enemy_list = self.clean_enemy(enemy, own_has_air, workers_do_no_damage)
        if not enemy_list:
            return _VICTORY
        if not own_list:
            return _LOSS

        key = (
            tuple(sorted(u.tag for u in own_list)),
            tuple(sorted(u.tag for u in enemy_list)),
            timing_adjust, good_positioning, workers_do_no_damage,
        )
        now = self.ai.time
        cached = self._cache.get(key)
        if cached is not None and now - cached[0] <= cache_seconds:
            return cached[1]

        if self.sim_calls_this_step >= MAX_SIM_CALLS_PER_STEP:
            # over budget: a slightly stale answer beats a new expensive one, and beats nothing
            if cached is not None:
                return cached[1]
            return self._fallback(own_list, enemy_list)

        self._configure_simulator()
        try:
            self.sim_calls_this_step += 1
            self.total_sim_calls += 1
            result = self.ai.mediator.can_win_fight(
                own_units=Units(own_list, self.ai),
                enemy_units=Units(enemy_list, self.ai),
                timing_adjust=timing_adjust,
                good_positioning=good_positioning,
                workers_do_no_damage=workers_do_no_damage,
            )
        except BaseException as e:  # noqa: BLE001 - the Rust side can panic with a BaseException subclass
            if isinstance(e, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
                raise
            logger.warning(f"[fight] combat simulator failed ({e!r}); using power-ratio fallback")
            return self._fallback(own_list, enemy_list)
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
