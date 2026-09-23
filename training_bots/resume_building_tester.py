from sc2.bot_ai import BotAI, Race
from sc2.data import Result
from sc2.unit import Unit
from sc2.units import Units


class ResumeBuilding(BotAI):
    NAME: str = "WorkerRushBot"
    RACE: Race = Race.Terran

    attacking_scvs = []
    focus : Unit = None

    async def on_step(self, iteration: int):

        if iteration == 50:
            counter = 0
            for w in self.workers:
                self.attacking_scvs.append(w)
                w.attack(self.enemy_start_locations[0])
                counter += 1
                if counter > 2:
                    break
        
        if self.enemy_units.amount > 0 and self.focus is None:
            self.focus = self.enemy_units.first
        
        if self.focus is not None:
            for i in self.attacking_scvs:
                i.attack(self.focus)
