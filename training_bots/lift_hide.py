from sc2.bot_ai import BotAI, Race
from sc2.data import Result
from sc2.ids.ability_id import AbilityId


class Lift(BotAI):
    NAME: str = "Lift"
    RACE: Race = Race.Terran

    async def on_step(self, iteration: int):
        if not self.structures.first.is_flying:
            self.structures.first(AbilityId.LIFT)
        else:
            self.structures.first.move(self.start_location.towards(self.game_info.map_center, -30))
