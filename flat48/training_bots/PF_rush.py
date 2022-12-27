from sc2.bot_ai import BotAI, Race
from sc2.data import Result
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2


class PFrush(BotAI):
    NAME: str = "PFrush"
    RACE: Race = Race.Terran
    lifted = False

    async def on_step(self, iteration: int):
        global lifted

        target_pos = self.enemy_start_locations[0].towards(self.game_info.map_center, 8)
        if not self.structures.first.is_flying and self.lifted == False:
            self.structures.first(AbilityId.LIFT)
            self.lifted = True
        elif self.structures.first.is_flying and target_pos.distance_to(self.structures.first) > 1:
            self.structures.first.move(target_pos)
        else:
            self.structures.first(AbilityId.LAND, target_pos)
        
        for i in self.workers:
            i.move(self.start_location)
