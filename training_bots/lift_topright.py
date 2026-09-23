from sc2.bot_ai import BotAI, Race
from sc2.data import Result
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2


class LiftTopRight(BotAI):
    NAME: str = "LiftTopRight"
    RACE: Race = Race.Terran
    lifted = False

    async def on_step(self, iteration: int):
        top_right = Point2((self.game_info.playable_area.right, self.game_info.playable_area.top))
        min_dist = 100000
        pos = None
        for value in self.expansion_locations_list:
            dist = top_right.distance_to(value)
            if dist < min_dist:
                min_dist = dist
                pos = value
        if not self.structures.first.is_flying and self.lifted == False:
            self.structures.first(AbilityId.LIFT)
            self.lifted = True
        elif self.structures.first.is_flying:
            self.structures.first(AbilityId.LAND, pos)
        
        for i in self.workers:
            i.move(self.start_location)
