from sc2.bot_ai import BotAI, Race
from sc2.data import Result


class WorkerRushBot(BotAI):
    NAME: str = "WorkerRushBot"
    RACE: Race = Race.Terran

    async def on_step(self, iteration: int):
        total_health = 0
        for w in self.workers:
            total_health += w.health + w.shield

        if total_health < 220:
            for worker in self.workers:
                worker.move(self.start_location)
        
        if total_health > 260:
            for worker in self.workers:
                worker.attack(self.enemy_start_locations[0])
