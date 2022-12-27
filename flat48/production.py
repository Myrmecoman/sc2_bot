from sc2.ids.unit_typeid import UnitTypeId
from sc2.bot_ai import BotAI


def produce(self : BotAI):
    for bar in self.structures(UnitTypeId.BARRACKS).ready.idle:
        if self.can_afford(UnitTypeId.MARINE):
            bar.build(UnitTypeId.MARINE)
