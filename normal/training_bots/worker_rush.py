from sc2.bot_ai import BotAI, Race
from sc2.data import Result


class WorkerRushBot(BotAI):
    NAME: str = "WorkerRushBot"
    RACE: Race = Race.Terran

    async def on_step(self, iteration: int):
        if iteration == 0:
            for worker in self.workers:
                worker.attack(self.enemy_start_locations[0])

