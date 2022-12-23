from sc2.bot_ai import BotAI, Race
from sc2.data import Result
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2


class Lift(BotAI):
    NAME: str = "Lift"
    RACE: Race = Race.Terran

    async def on_step(self, iteration: int):

        top_right = Point2((self.game_info.playable_area.right, self.game_info.playable_area.top))
        bottom_right = Point2((self.game_info.playable_area.right, 0))
        bottom_left = Point2((0, 0))
        top_left = Point2((0, self.game_info.playable_area.top))
        corners = [top_right, bottom_right, bottom_left, top_left]
        max_index = 0
        max_value = 100000
        for i in range(len(corners)):
            dist = self.start_location.distance_to(corners[i])
            if dist < max_value:
                max_value = dist
                max_index = i
        if not self.structures.first.is_flying:
            self.structures.first(AbilityId.LIFT)
        else:
            self.structures.first.move(corners[max_index])
        
        for i in self.workers:
            i.move(self.start_location)
