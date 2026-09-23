import numpy as np
from typing import Optional
from bot.pathing.consts import ALL_STRUCTURES, ATTACK_TARGET_IGNORE, DANGEROUS_STRUCTURES
from bot.pathing.order_utils import is_already_attacking, is_already_attack_moving_to, spread_out_point
from bot.pathing.pathing import Pathing
from sc2.bot_ai import BotAI
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.ability_id import AbilityId

LOCAL_FIGHT_RADIUS = 14.0          # how far around a unit counts as "this particular fight" for the overwhelming-advantage check below
OVERWHELMING_LOCAL_POWER_RATIO = 2.0  # how much local power advantage counts as "very very high" confidence - deliberately much higher than the strategic should_attack bar, since this overrides a per-shot danger reaction, not a whole-army commitment
MELEE_RANGE_THRESHOLD = 1.0        # a nearby enemy at or below this ground_range counts as melee (Zealot/Zergling/Ultralisk/...)


class Bio:
    def __init__(self, ai: BotAI, pathing: Pathing):
        self.ai: BotAI = ai
        self.pathing: Pathing = pathing

    def _winning_locally(self, unit: Unit, units: Units, close_enemies: Units) -> bool:
        """True when the fight actually happening right around this unit - our own nearby units vs
        the enemies actually nearby, not the whole armies - is so lopsided that kiting away between
        shots would just waste time and let a losing enemy disengage. close_enemies here is every
        valid target map-wide (see handle_attackers), so it still needs its own distance filter."""
        nearby_enemies: Units = close_enemies.closer_than(LOCAL_FIGHT_RADIUS, unit)
        if not nearby_enemies:
            return False
        # kiting a melee-only group is free value, not a tradeoff - we give up nothing by staying
        # at range (there's no cost to weigh against "we'd win anyway"), so there's no reason to
        # ever trade it away. Only worth overriding the retreat when at least one nearby enemy
        # actually has reach, i.e. kiting has a real cost (repositioning time, missed shots)
        if all(e.ground_range <= MELEE_RANGE_THRESHOLD for e in nearby_enemies):
            return False
        nearby_allies: Units = units.closer_than(LOCAL_FIGHT_RADIUS, unit)
        advisor = self.ai.army_advisor
        local_enemy_power: float = sum(advisor.unit_power(e) for e in nearby_enemies)
        if local_enemy_power <= 0:
            return False
        local_our_power: float = sum(advisor.unit_power(a) for a in nearby_allies)
        return local_our_power > OVERWHELMING_LOCAL_POWER_RATIO * local_enemy_power

    async def handle_attackers(self, units: Units, attack_target: Point2) -> None:
        grid = self.pathing.ground_grid
        for unit in units:

            close_enemies: Units = None
            if unit.type_id == UnitTypeId.MARAUDER:
                # marauders can't hit air at all - a lifted (flying) structure has to be excluded
                # here too, not just enemy_units, or it'll get picked as an unreachable target
                close_enemies = self.ai.enemy_units.filter(lambda u: not u.is_flying and u.type_id not in ATTACK_TARGET_IGNORE) | self.ai.enemy_structures.not_flying#.filter(lambda s: s.distance_to(unit) < 15.0 and s.type_id in DANGEROUS_STRUCTURES)
            else:
                close_enemies = self.ai.enemy_units.filter(lambda u: u.type_id not in ATTACK_TARGET_IGNORE) | self.ai.enemy_structures#.filter(lambda s: s.distance_to(unit) < 15.0 and s.type_id in DANGEROUS_STRUCTURES)

            # check for nearby target fire
            target: Optional[Unit] = None
            if close_enemies:
                in_attack_range: Units = close_enemies.in_attack_range_of(unit)
                if in_attack_range:
                    target = self.pick_enemy_target(unit, in_attack_range, True)
                else:
                    target = self.pick_enemy_target(unit, close_enemies, False)

            if target and unit.weapon_cooldown == 0:
                self.attack_and_stim(unit, target)
                continue

            # no target and in danger, run away - but not if the thing actually threatening us
            # both outranges AND isn't slower than us (e.g. a Stalker vs a Marine). Backing off a
            # step between shots doesn't get us out of reach of an enemy we can't outrun anyway -
            # it just wastes movement and keeps drifting us in and out of our own attack range for
            # nothing, which is exactly what made marines vs stalkers look so bad. Hold and trade
            # instead. If we're actually faster than what outranges us, real kiting can still work
            # (we can out-reposition it between its shots), so this only suppresses the fruitless case.
            # real_speed (not movement_speed) because that accounts for buffs/upgrades currently
            # active on either unit - e.g. our own stim, or a slow we just landed on the enemy.
            # Also futile against a near-immobile target (a sieged tank, a defensive structure)
            # even though it "loses" the speed check - whenever something outranges us at all,
            # being in OUR range means being in ITS range too (range ordering guarantees it), so
            # real kiting only pays off if we can escape its ENTIRE threat radius faster than it
            # can re-threaten us. A sieged tank's radius never moves, so escaping it costs a full
            # retreat-and-reapproach every cycle - against a big range gap like 13 vs 5-6, that
            # trade is strictly worse than holding: it was landing free hits while we contributed
            # nothing, exactly the "push in, eat one shot, retreat without firing back" pattern
            futile_to_kite: bool = (
                target is not None
                and target.ground_range > unit.ground_range
                and (target.real_speed >= unit.real_speed or target.real_speed < 0.5)
            )
            # never worth backing off from something that can't hurt us at all, either - a
            # building (a Command Center, a depot, anything with no weapon) poses zero risk, so
            # retreating from it only wastes time we could spend closing in and finishing it off.
            # Symmetric to the melee case above: a target with 0 range in every domain is always
            # safe to press in on, kiting in instead of away
            target_harmless: bool = target is not None and target.ground_range == 0 and target.air_range == 0
            # also don't bother kiting away when we're crushing this specific fight anyway - with
            # that much of a local edge, backing off between shots only slows down a fight we're
            # already winning and gives a losing enemy a chance to disengage. Deliberately checked
            # last (only when we'd otherwise retreat) since it's real per-unit work (two nearby-
            # unit scans), not worth paying for on every marine every step
            if (
                not futile_to_kite
                and not target_harmless
                and not self.pathing.is_position_safe(grid, unit.position)
                and not self._winning_locally(unit, units, close_enemies)
            ):
                self.move_to_safety(unit, grid)
                continue

            # get to the target
            if unit.distance_to(attack_target) > unit.ground_range:
                # only make pathing queries if enemies are close
                if target:
                    if not is_already_attacking(unit, target):
                        unit.attack(target)
                else:
                    # no threats nearby: spread out a bit while marching in so we don't
                    # clump into one AOE-friendly blob before contact (banelings/tanks/storm)
                    spread_point: Point2 = spread_out_point(unit, units, attack_target)
                    if not is_already_attack_moving_to(unit, spread_point):
                        unit.attack(spread_point)
            else:
                if not is_already_attack_moving_to(unit, attack_target):
                    unit.attack(attack_target)

    def move_to_safety(self, unit: Unit, grid: np.ndarray):
        """
        Find a close safe spot on our grid
        Then path to it
        """
        safe_spot: Point2 = self.pathing.find_closest_safe_spot(unit.position, grid)
        move_to: Point2 = self.pathing.find_path_next_point(unit.position, safe_spot, grid)
        unit.move(move_to)

    def attack_and_stim(self, unit: Unit, enemy: Unit):
        if unit.health == unit.health_max and self.ai.already_pending_upgrade(UpgradeId.STIMPACK) == 1 and enemy.distance_to(unit) < unit.ground_range:
            if unit.type_id == UnitTypeId.MARINE and unit.is_using_ability(AbilityId.EFFECT_STIM_MARINE) == False:
                unit(AbilityId.EFFECT_STIM_MARINE)
            elif unit.type_id == UnitTypeId.MARAUDER and unit.is_using_ability(AbilityId.EFFECT_STIM_MARAUDER) == False:
                unit(AbilityId.EFFECT_STIM_MARAUDER)
        if not is_already_attacking(unit, enemy):
            unit.attack(enemy)

    async def retreat_to(self, units: Units, pos: Point2):
        """
        Hold near pos, but keep firing at anything already in range while we wait (e.g. an enemy
        stuck at a closed wall) instead of ignoring a free kill - a wall blocks their path to us,
        not our weapons' reach through/over it.

        If something nearby is hitting us (or about to) without being in OUR range yet - it
        outranges us, or is just closing in - don't just sit at pos absorbing it doing nothing:
        retreat if this isn't a fight worth taking, or close the distance and engage if it clearly
        is. Same reasoning handle_attackers already uses (futile_to_kite / is_position_safe /
        _winning_locally) - holding was the one place a unit could take free damage indefinitely
        without either fighting back or backing off, because "hold at pos" had no danger-awareness
        at all. A big enough army sitting at a rally point doing nothing while being picked apart is
        exactly a fight it could have won, refused for no reason.
        """
        grid = self.pathing.ground_grid
        for unit in units:
            close_enemies: Units = None
            if unit.type_id == UnitTypeId.MARAUDER:
                close_enemies = self.ai.enemy_units.filter(lambda u: not u.is_flying and u.type_id not in ATTACK_TARGET_IGNORE) | self.ai.enemy_structures.not_flying
            else:
                close_enemies = self.ai.enemy_units.filter(lambda u: u.type_id not in ATTACK_TARGET_IGNORE) | self.ai.enemy_structures

            target: Optional[Unit] = None
            if close_enemies:
                in_attack_range: Units = close_enemies.in_attack_range_of(unit)
                if in_attack_range:
                    target = self.pick_enemy_target(unit, in_attack_range, True)

            if target and unit.weapon_cooldown == 0:
                self.attack_and_stim(unit, target)
                continue

            nearby_threats: Units = close_enemies.closer_than(LOCAL_FIGHT_RADIUS, unit) if close_enemies else close_enemies
            if not nearby_threats:
                move_to: Point2 = self.pathing.find_path_next_point(unit.position, pos, grid)
                unit.move(move_to)
                continue

            nearest: Unit = nearby_threats.closest_to(unit)
            futile_to_kite: bool = (
                nearest.ground_range > unit.ground_range
                and (nearest.real_speed >= unit.real_speed or nearest.real_speed < 0.5)
            )
            if (
                not futile_to_kite
                and not self.pathing.is_position_safe(grid, unit.position)
                and not self._winning_locally(unit, units, close_enemies)
            ):
                self.move_to_safety(unit, grid)
                continue

            # not retreating - close the distance instead of standing at pos while it keeps
            # hitting us. Plain attack (not grid-routed) matches handle_attackers' own approach to
            # a picked target - pathing is for retreating through danger, not for closing a fight
            # we've already decided to take
            if not is_already_attacking(unit, nearest):
                unit.attack(nearest)

    @staticmethod
    def pick_enemy_target(unit: Unit, enemies: Units, in_range: bool = True) -> Unit:
        """For best enemy target from the provided enemies
        TODO: If there are multiple units that can be killed in one shot, pick the highest value one
        """
        if in_range:
            return min(enemies, key=lambda e: (e.health + e.shield, e.tag),)
        else:
            return enemies.closest_to(unit)
