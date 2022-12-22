from sc2.main import run_game
from sc2.data import Race, Difficulty
from sc2.ids.unit_typeid import UnitTypeId
from sc2.bot_ai import BotAI


def produce(self : BotAI):
    for bar in self.structures(UnitTypeId.BARRACKS).ready.idle:
        if bar.has_add_on:
            add_on = self.structures.find_by_tag(bar.add_on_tag)
            if add_on is None:
                continue
            if add_on.type_id == UnitTypeId.BARRACKSTECHLAB and self.can_afford(UnitTypeId.MARAUDER):
                bar.build(UnitTypeId.MARAUDER)
            elif add_on.type_id == UnitTypeId.BARRACKSREACTOR and self.can_afford(UnitTypeId.MARINE):
                bar.build(UnitTypeId.MARINE)
                if self.can_afford(UnitTypeId.MARINE):
                    bar.build(UnitTypeId.MARINE)
        elif self.army_count == 0:
            if self.can_afford(UnitTypeId.REAPER):
                bar.build(UnitTypeId.REAPER)
        elif self.can_afford(UnitTypeId.MARINE):
            bar.build(UnitTypeId.MARINE)

    for fac in self.structures(UnitTypeId.FACTORY).ready.idle:
        if fac.has_add_on:
            add_on = self.structures.find_by_tag(fac.add_on_tag)
            if add_on is None:
                continue
            if add_on.type_id == UnitTypeId.FACTORYTECHLAB and self.can_afford(UnitTypeId.SIEGETANK):
                fac.build(UnitTypeId.SIEGETANK)
            elif add_on.type_id == UnitTypeId.FACTORYREACTOR and self.can_afford(UnitTypeId.HELLION):
                fac.build(UnitTypeId.HELLION)
                if self.can_afford(UnitTypeId.HELLION):
                    fac.build(UnitTypeId.HELLION)
        elif self.can_afford(UnitTypeId.HELLION):
            fac.build(UnitTypeId.HELLION)

    for st in self.structures(UnitTypeId.STARPORT).ready.idle:
        if st.has_add_on:
            add_on = self.structures.find_by_tag(st.add_on_tag)
            if add_on is None:
                continue
            if add_on.type_id == UnitTypeId.STARPORTTECHLAB and self.can_afford(UnitTypeId.RAVEN) and self.units(UnitTypeId.RAVEN).amount < 4:
                st.build(UnitTypeId.RAVEN)
            elif add_on.type_id == UnitTypeId.STARPORTTECHLAB and self.can_afford(UnitTypeId.MEDIVAC) and self.units(UnitTypeId.MEDIVAC).amount < 6:
                st.build(UnitTypeId.MEDIVAC)
            elif add_on.type_id == UnitTypeId.STARPORTTECHLAB and self.can_afford(UnitTypeId.VIKINGFIGHTER) and self.units(UnitTypeId.VIKINGFIGHTER).amount < 8:
                st.build(UnitTypeId.VIKINGFIGHTER)
            elif add_on.type_id == UnitTypeId.STARPORTREACTOR and self.can_afford(UnitTypeId.MEDIVAC) and self.units(UnitTypeId.MEDIVAC).amount < 6:
                st.build(UnitTypeId.MEDIVAC)
                if self.can_afford(UnitTypeId.MEDIVAC):
                    st.build(UnitTypeId.MEDIVAC)
            elif add_on.type_id == UnitTypeId.STARPORTREACTOR and self.can_afford(UnitTypeId.VIKINGFIGHTER) and self.units(UnitTypeId.VIKINGFIGHTER).amount < 8:
                st.build(UnitTypeId.VIKINGFIGHTER)
                if self.can_afford(UnitTypeId.VIKINGFIGHTER):
                    st.build(UnitTypeId.VIKINGFIGHTER)
        elif self.can_afford(UnitTypeId.MEDIVAC) and self.units(UnitTypeId.MEDIVAC).amount < 6:
            st.build(UnitTypeId.MEDIVAC)
        elif self.can_afford(UnitTypeId.VIKINGFIGHTER) and self.units(UnitTypeId.VIKINGFIGHTER).amount < 8:
            st.build(UnitTypeId.VIKINGFIGHTER)
