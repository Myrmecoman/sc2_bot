from sc2.ids.unit_typeid import UnitTypeId
from sc2.bot_ai import BotAI
from sc2.data import Race


def produce_single_type_unit(self : BotAI, structure : UnitTypeId, unit : UnitTypeId, dumpunit : UnitTypeId = None):
    for s in self.structures(structure).ready.idle:
        if s.has_techlab and self.can_afford(unit):
            s.build(unit)
        elif s.has_reactor and self.can_afford(unit):
            s.build(unit)
            if self.can_afford(unit):
                s.build(unit)
            elif dumpunit is not None and self.can_afford(dumpunit):
                s.build(dumpunit)
        elif self.can_afford(unit):
            s.build(unit)
    
    for s in self.structures(structure).ready:
        if not s.has_reactor:
            continue
        if len(s.orders) == 1 and self.can_afford(unit):
            s.build(unit)
        elif len(s.orders) == 1 and dumpunit is not None and self.can_afford(dumpunit):
            s.build(dumpunit)


def produce(self : BotAI):

    less_reapers = self.units.of_type({UnitTypeId.REAPER}).amount < self.army_advisor.amount_of_enemies_of_type(UnitTypeId.REAPER)

    if self.produce_from_starports:
        for st in self.structures(UnitTypeId.STARPORT).ready.idle:
            if st.has_techlab and self.can_afford(UnitTypeId.RAVEN) and self.units(UnitTypeId.RAVEN).amount < self.army_advisor.max_ravens:
                st.build(UnitTypeId.RAVEN)
            elif st.has_techlab and self.structures(UnitTypeId.FUSIONCORE).amount > 0 and self.can_afford(UnitTypeId.BATTLECRUISER) and self.units(UnitTypeId.BATTLECRUISER).amount < self.army_advisor.max_battlecruisers:
                st.build(UnitTypeId.BATTLECRUISER)
            elif st.has_techlab and self.can_afford(UnitTypeId.MEDIVAC) and self.units(UnitTypeId.MEDIVAC).amount < self.army_advisor.max_medivacs:
                st.build(UnitTypeId.MEDIVAC)
            elif st.has_techlab and self.can_afford(UnitTypeId.VIKINGFIGHTER) and self.units(UnitTypeId.VIKINGFIGHTER).amount < self.army_advisor.max_vikings:
                st.build(UnitTypeId.VIKINGFIGHTER)
            elif st.has_reactor and self.can_afford(UnitTypeId.MEDIVAC) and self.units(UnitTypeId.MEDIVAC).amount < self.army_advisor.max_medivacs:
                st.build(UnitTypeId.MEDIVAC)
                if self.can_afford(UnitTypeId.MEDIVAC):
                    st.build(UnitTypeId.MEDIVAC)
            elif st.has_reactor and self.can_afford(UnitTypeId.VIKINGFIGHTER) and self.units(UnitTypeId.VIKINGFIGHTER).amount < self.army_advisor.max_vikings:
                st.build(UnitTypeId.VIKINGFIGHTER)
                if self.can_afford(UnitTypeId.VIKINGFIGHTER):
                    st.build(UnitTypeId.VIKINGFIGHTER)
            elif self.can_afford(UnitTypeId.MEDIVAC) and self.units(UnitTypeId.MEDIVAC).amount < self.army_advisor.max_medivacs:
                st.build(UnitTypeId.MEDIVAC)
            elif self.can_afford(UnitTypeId.VIKINGFIGHTER) and self.units(UnitTypeId.VIKINGFIGHTER).amount < self.army_advisor.max_vikings:
                st.build(UnitTypeId.VIKINGFIGHTER)
        
        for st in self.structures(UnitTypeId.STARPORT).ready:
            if not st.has_reactor:
                continue
            if len(st.orders) == 1 and self.can_afford(UnitTypeId.MEDIVAC) and self.units(UnitTypeId.MEDIVAC).amount < self.army_advisor.max_medivacs:
                st.build(UnitTypeId.MEDIVAC)
            elif len(st.orders) == 1 and self.can_afford(UnitTypeId.VIKINGFIGHTER) and self.units(UnitTypeId.VIKINGFIGHTER).amount < self.army_advisor.max_vikings:
                st.build(UnitTypeId.VIKINGFIGHTER)
    
    if self.produce_from_factories:
        for fac in self.structures(UnitTypeId.FACTORY).ready.idle:
                if fac.has_techlab and self.can_afford(UnitTypeId.SIEGETANK):
                    fac.build(UnitTypeId.SIEGETANK)
                elif fac.has_techlab and self.can_afford(UnitTypeId.HELLION):
                    if less_reapers:
                        fac.build(UnitTypeId.HELLION)
                elif fac.has_reactor and self.can_afford(UnitTypeId.HELLION):
                    fac.build(UnitTypeId.HELLION)
                    if self.can_afford(UnitTypeId.HELLION):
                        fac.build(UnitTypeId.HELLION)
                elif self.can_afford(UnitTypeId.HELLION):
                    fac.build(UnitTypeId.HELLION)
        
        for fac in self.structures(UnitTypeId.FACTORY).ready:
            if not fac.has_reactor:
                continue
            if len(fac.orders) == 1 and self.can_afford(UnitTypeId.HELLION):
                fac.build(UnitTypeId.HELLION)

    if self.produce_from_barracks:
        total_marines = self.units.of_type({UnitTypeId.MARINE}).amount
        total_marauders = self.units.of_type({UnitTypeId.MARAUDER}).amount

        if less_reapers: # if we have less reapers than enemy, make more reapers
            produce_single_type_unit(self, UnitTypeId.BARRACKS, UnitTypeId.REAPER, UnitTypeId.MARINE)

        elif total_marauders != 0 and total_marines / (total_marines + total_marauders) < self.army_advisor.marine_marauder_ratio: # if not enough marines, make only of them
            for bar in self.structures(UnitTypeId.BARRACKS).ready.idle:
                if bar.has_techlab and self.can_afford(UnitTypeId.MARINE):
                    bar.build(UnitTypeId.MARINE)
                elif bar.has_reactor and self.can_afford(UnitTypeId.MARINE):
                    bar.build(UnitTypeId.MARINE)
                    if self.can_afford(UnitTypeId.MARINE):
                        bar.build(UnitTypeId.MARINE)
                elif self.army_count == 0 or (self.army_count < 2 and self.enemy_race == Race.Terran):
                    if self.can_afford(UnitTypeId.REAPER):
                        bar.build(UnitTypeId.REAPER)
                elif self.can_afford(UnitTypeId.MARINE):
                    bar.build(UnitTypeId.MARINE)
            
            for bar in self.structures(UnitTypeId.BARRACKS).ready:
                if not bar.has_reactor:
                    continue
                if len(bar.orders) == 1 and self.can_afford(UnitTypeId.MARINE):
                    bar.build(UnitTypeId.MARINE)

        else:
            for bar in self.structures(UnitTypeId.BARRACKS).ready.idle:
                if bar.has_techlab and self.can_afford(UnitTypeId.MARAUDER):
                    bar.build(UnitTypeId.MARAUDER)
                elif bar.has_reactor and self.can_afford(UnitTypeId.MARINE):
                    bar.build(UnitTypeId.MARINE)
                    if self.can_afford(UnitTypeId.MARINE):
                        bar.build(UnitTypeId.MARINE)
                elif self.army_count == 0 or (self.army_count < 2 and self.enemy_race == Race.Terran):
                    if self.can_afford(UnitTypeId.REAPER):
                        bar.build(UnitTypeId.REAPER)
                elif self.can_afford(UnitTypeId.MARINE):
                    bar.build(UnitTypeId.MARINE)

            for bar in self.structures(UnitTypeId.BARRACKS).ready:
                if not bar.has_reactor:
                    continue
                if len(bar.orders) == 1 and self.can_afford(UnitTypeId.MARINE):
                    bar.build(UnitTypeId.MARINE)