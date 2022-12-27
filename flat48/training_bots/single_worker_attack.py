from sc2.bot_ai import BotAI, Race
from sc2.data import Result


class SingleWorker(BotAI):
    NAME: str = "SingleWorker"
    RACE: Race = Race.Terran

    async def on_step(self, iteration: int):
        if iteration == 30:
            self.workers.random.attack(self.enemy_start_locations[0])
