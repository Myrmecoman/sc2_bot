from sc2.bot_ai import BotAI, Race
from sc2.data import Result
from sc2.ids.unit_typeid import UnitTypeId


class WorkerRushBot(BotAI):
    NAME: str = "WorkerRushBot"
    RACE: Race = Race.Terran

    async def on_step(self, iteration: int):

        if iteration < 25:
            return

        total_health = 0
        for w in self.workers:
            total_health += w.health + w.shield

        mfs = self.mineral_field.closer_than(10, self.townhalls.first)

        if total_health < 240:               # leave if we don't have any more health
            for worker in self.workers:
                mf = mfs.closest_to(worker)
                worker.gather(mf)
        
        if total_health > 260:               # attack again when enough health
            for worker in self.workers:
                if worker.weapon_cooldown > 5:
                    mf = mfs.closest_to(worker)
                    worker.gather(mf)
                elif worker.health + worker.shield > 10:
                    worker.attack(self.enemy_start_locations[0])
                else:
                    mf = mfs.closest_to(worker)
                    worker.gather(mf)

        if self.townhalls.idle.amount > 0 and self.can_afford(UnitTypeId.PROBE):
            self.townhalls.idle.first.train(UnitTypeId.PROBE)
