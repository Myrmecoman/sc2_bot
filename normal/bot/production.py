from sc2.ids.unit_typeid import UnitTypeId
from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.data import Race


made_banshee = False
made_raven = False


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
    global made_banshee
    global made_raven

    less_reapers = self.units.of_type({UnitTypeId.REAPER}).amount < self.army_advisor.amount_of_enemies_of_type(UnitTypeId.REAPER)

    if self.produce_from_starports:
        for st in self.structures(UnitTypeId.STARPORT).ready.idle:

            # first get a banshee, then a raven, then free to choose
            if self.units(UnitTypeId.BANSHEE).amount == 0 and self.army_advisor.max_banshees > 0 and not made_banshee:
                if st.has_techlab and self.can_afford(UnitTypeId.BANSHEE):
                    st.build(UnitTypeId.BANSHEE)
                    made_banshee = True
                continue
            if self.units(UnitTypeId.RAVEN).amount == 0 and self.army_advisor.max_ravens > 0 and not made_raven:
                if st.has_techlab and self.can_afford(UnitTypeId.RAVEN):
                    st.build(UnitTypeId.RAVEN)
                    made_raven = True
                continue

            if st.has_techlab and self.can_afford(UnitTypeId.RAVEN) and self.units(UnitTypeId.RAVEN).amount < self.army_advisor.max_ravens:
                st.build(UnitTypeId.RAVEN)
            elif st.has_techlab and self.structures(UnitTypeId.FUSIONCORE).amount > 0 and self.can_afford(UnitTypeId.BATTLECRUISER) and self.units(UnitTypeId.BATTLECRUISER).amount < self.army_advisor.max_battlecruisers:
                st.build(UnitTypeId.BATTLECRUISER)
            elif st.has_techlab and self.can_afford(UnitTypeId.MEDIVAC) and self.units(UnitTypeId.MEDIVAC).amount < self.army_advisor.max_medivacs:
                st.build(UnitTypeId.MEDIVAC)
            elif st.has_techlab and self.can_afford(UnitTypeId.VIKINGFIGHTER) and self.units(UnitTypeId.VIKINGFIGHTER).amount < self.army_advisor.max_vikings:
                st.build(UnitTypeId.VIKINGFIGHTER)
            elif st.has_techlab and self.can_afford(UnitTypeId.BANSHEE) and self.units(UnitTypeId.BANSHEE).amount < self.army_advisor.max_banshees:
                st.build(UnitTypeId.BANSHEE)
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
                if fac.has_techlab:
                    if self.can_afford(UnitTypeId.SIEGETANK) and self.units(UnitTypeId.SIEGETANK).amount < self.army_advisor.max_tanks:
                        fac.build(UnitTypeId.SIEGETANK)
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

        #if less_reapers: # if we have less reapers than enemy, make more reapers (can also be fixed by rushing cyclone)
        #    produce_single_type_unit(self, UnitTypeId.BARRACKS, UnitTypeId.REAPER, UnitTypeId.MARINE)
        if total_marauders != 0 and total_marines / (total_marines + total_marauders) < self.army_advisor.marine_marauder_ratio: # if not enough marines, make only of them
            for bar in self.structures(UnitTypeId.BARRACKS).ready.idle:
                if bar.has_techlab and self.can_afford(UnitTypeId.MARINE):
                    bar.build(UnitTypeId.MARINE)
                elif bar.has_reactor and self.can_afford(UnitTypeId.MARINE):
                    bar.build(UnitTypeId.MARINE)
                    if self.can_afford(UnitTypeId.MARINE):
                        bar.build(UnitTypeId.MARINE)
                elif self.army_count == 0 and self.can_afford(UnitTypeId.REAPER):
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
                elif self.army_count == 0 and self.can_afford(UnitTypeId.REAPER):
                    bar.build(UnitTypeId.REAPER)
                elif self.can_afford(UnitTypeId.MARINE):
                    bar.build(UnitTypeId.MARINE)

            for bar in self.structures(UnitTypeId.BARRACKS).ready:
                if not bar.has_reactor:
                    continue
                if len(bar.orders) == 1 and self.can_afford(UnitTypeId.MARINE):
                    bar.build(UnitTypeId.MARINE)