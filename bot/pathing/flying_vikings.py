import numpy as np
from typing import Optional
from bot.pathing.consts import ALL_STRUCTURES, ATTACK_TARGET_IGNORE, DANGEROUS_STRUCTURES
from bot.pathing.order_utils import is_already_attacking, is_already_attack_moving_to
from bot.pathing.pathing import Pathing
from sc2.bot_ai import BotAI
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.ability_id import AbilityId


class FlyingVikings:
    def __init__(self, ai: BotAI, pathing: Pathing):
        self.ai: BotAI = ai
        self.pathing: Pathing = pathing

    async def handle_attackers(self, units: Units, attack_target: Point2) -> None:
        grid = self.pathing.air_grid
        for unit in units:
            
            close_enemies = self.ai.enemy_units.filter(lambda u: u.distance_to(unit) < 15.0 and u.is_flying)

            # check for nearby target fire
            target: Optional[Unit] = None
            if close_enemies:
                in_attack_range: Units = close_enemies.in_attack_range_of(unit)
                if in_attack_range:
                    target = self.pick_enemy_target(in_attack_range)
                else:
                    target = self.pick_enemy_target(close_enemies)

            if target and unit.weapon_cooldown == 0:
                if not is_already_attacking(unit, target):
                    unit.attack(target)
                continue

            # in danger, always run away - unlike bio.py's marines, Vikings never hold and trade.
            # Vikings are a dedicated hit-and-run unit (135 HP, no shields, no real armor) fighting
            # other air, not a line that can afford to eat a free hit for the sake of holding
            # ground. Even a kite that can't fully outrun the threat still buys a hit avoided, and
            # for a unit this fragile that's worth more than whatever "holding" would have gained
            if not self.pathing.is_position_safe(grid, unit.position):
                self.move_to_safety(unit, grid)
                continue

            # get to the target
            if unit.distance_to(attack_target) > unit.air_range:
                # only make pathing queries if enemies are close
                if close_enemies:
                    unit.move(self.pathing.find_path_next_point(unit.position, attack_target, grid))
                else:
                    unit.move(attack_target)
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

    async def retreat_to(self, units: Units, pos: Point2):
        """
        Hold near pos, but fire at anything already in range while waiting (previously this did
        neither - a holding Viking wouldn't even shoot back). Always retreats from danger rather
        than holding or pushing in when something isn't in range yet either - see
        handle_attackers for why Vikings specifically always kite instead of judging it case by
        case the way bio.py's marines do.
        """
        grid = self.pathing.air_grid
        for unit in units:
            close_enemies = self.ai.enemy_units.filter(lambda u: u.distance_to(unit) < 15.0 and u.is_flying)

            target: Optional[Unit] = None
            if close_enemies:
                in_attack_range: Units = close_enemies.in_attack_range_of(unit)
                if in_attack_range:
                    target = self.pick_enemy_target(in_attack_range)

            if target and unit.weapon_cooldown == 0:
                if not is_already_attacking(unit, target):
                    unit.attack(target)
                continue

            if not self.pathing.is_position_safe(grid, unit.position):
                self.move_to_safety(unit, grid)
                continue

            move_to: Point2 = self.pathing.find_path_next_point(unit.position, pos, grid)
            unit.move(move_to)

    @staticmethod
    def pick_enemy_target(enemies: Units) -> Unit:
        """For best enemy target from the provided enemies
        TODO: If there are multiple units that can be killed in one shot, pick the highest value one
        """
        return min(enemies, key=lambda e: (e.health + e.shield, e.tag),)