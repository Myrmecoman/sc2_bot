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

            # first get a banshee, then a raven, then free to choose - has_techlab gates the OUTER
            # condition, not just the inner build: a Reactor/bare Starport can never build either
            # one, so it used to just sit here doing nothing every call (hitting the unconditional
            # continue below) instead of falling through to Medivac/Viking production while waiting
            # for a techlab Starport to afford the first Banshee/Raven
            if st.has_techlab and self.units(UnitTypeId.BANSHEE).amount == 0 and self.army_advisor.max_banshees > 0 and not made_banshee:
                if self.can_afford(UnitTypeId.BANSHEE):
                    st.build(UnitTypeId.BANSHEE)
                    made_banshee = True
                continue
            if st.has_techlab and self.units(UnitTypeId.RAVEN).amount == 0 and self.army_advisor.max_ravens > 0 and not made_raven:
                if self.can_afford(UnitTypeId.RAVEN):
                    st.build(UnitTypeId.RAVEN)
                    made_raven = True
                continue

            # Vikings jump the rest of this queue once something has made them our actual answer
            # (skytoss right now) - every other Starport choice below is a nice-to-have by
            # comparison, and previously got built first regardless, delaying our real counter
            if self.army_advisor.prioritize_vikings and self.can_afford(UnitTypeId.VIKINGFIGHTER) and self.units(UnitTypeId.VIKINGFIGHTER).amount < self.army_advisor.max_vikings:
                st.build(UnitTypeId.VIKINGFIGHTER)
                # +1: account for the one just queued above, which .amount won't reflect yet -
                # otherwise this can queue one past max_vikings every time a reactor Starport has
                # exactly 1 slot of headroom left (matches the Liberator branch's correct pattern below)
                if st.has_reactor and self.can_afford(UnitTypeId.VIKINGFIGHTER) and self.units(UnitTypeId.VIKINGFIGHTER).amount + 1 < self.army_advisor.max_vikings:
                    st.build(UnitTypeId.VIKINGFIGHTER)
                continue

            total_liberators = self.units(UnitTypeId.LIBERATOR).amount + self.units(UnitTypeId.LIBERATORAG).amount
            if st.has_techlab and self.can_afford(UnitTypeId.RAVEN) and self.units(UnitTypeId.RAVEN).amount < self.army_advisor.max_ravens:
                st.build(UnitTypeId.RAVEN)
            elif st.has_techlab and self.structures(UnitTypeId.FUSIONCORE).amount > 0 and self.can_afford(UnitTypeId.BATTLECRUISER) and self.units(UnitTypeId.BATTLECRUISER).amount < self.army_advisor.max_battlecruisers:
                st.build(UnitTypeId.BATTLECRUISER)
            # no techlab/reactor requirement - only ever nonzero vs Terran once we've actually
            # spotted their Siege Tanks (see army_composition_advisor.py), so treat it with the
            # same urgency as Raven/BC rather than waiting behind Medivac/Banshee for no reason
            elif self.can_afford(UnitTypeId.LIBERATOR) and total_liberators < self.army_advisor.max_liberators:
                st.build(UnitTypeId.LIBERATOR)
                if st.has_reactor and self.can_afford(UnitTypeId.LIBERATOR) and total_liberators + 1 < self.army_advisor.max_liberators:
                    st.build(UnitTypeId.LIBERATOR)
            elif st.has_techlab and self.can_afford(UnitTypeId.MEDIVAC) and self.units(UnitTypeId.MEDIVAC).amount < self.army_advisor.max_medivacs:
                st.build(UnitTypeId.MEDIVAC)
            elif st.has_techlab and self.can_afford(UnitTypeId.VIKINGFIGHTER) and self.units(UnitTypeId.VIKINGFIGHTER).amount < self.army_advisor.max_vikings:
                st.build(UnitTypeId.VIKINGFIGHTER)
            elif st.has_techlab and self.can_afford(UnitTypeId.BANSHEE) and self.units(UnitTypeId.BANSHEE).amount < self.army_advisor.max_banshees:
                st.build(UnitTypeId.BANSHEE)
            elif st.has_reactor and self.can_afford(UnitTypeId.MEDIVAC) and self.units(UnitTypeId.MEDIVAC).amount < self.army_advisor.max_medivacs:
                st.build(UnitTypeId.MEDIVAC)
                # +1: account for the one just queued - this previously had no cap check on the
                # second build at all, so it could queue straight past max_medivacs every time
                if self.can_afford(UnitTypeId.MEDIVAC) and self.units(UnitTypeId.MEDIVAC).amount + 1 < self.army_advisor.max_medivacs:
                    st.build(UnitTypeId.MEDIVAC)
            elif st.has_reactor and self.can_afford(UnitTypeId.VIKINGFIGHTER) and self.units(UnitTypeId.VIKINGFIGHTER).amount < self.army_advisor.max_vikings:
                st.build(UnitTypeId.VIKINGFIGHTER)
                if self.can_afford(UnitTypeId.VIKINGFIGHTER) and self.units(UnitTypeId.VIKINGFIGHTER).amount + 1 < self.army_advisor.max_vikings:
                    st.build(UnitTypeId.VIKINGFIGHTER)
            elif self.can_afford(UnitTypeId.MEDIVAC) and self.units(UnitTypeId.MEDIVAC).amount < self.army_advisor.max_medivacs:
                st.build(UnitTypeId.MEDIVAC)
            elif self.can_afford(UnitTypeId.VIKINGFIGHTER) and self.units(UnitTypeId.VIKINGFIGHTER).amount < self.army_advisor.max_vikings:
                st.build(UnitTypeId.VIKINGFIGHTER)
        
        for st in self.structures(UnitTypeId.STARPORT).ready:
            if not st.has_reactor:
                continue
            if len(st.orders) != 1:
                continue
            if self.army_advisor.prioritize_vikings and self.can_afford(UnitTypeId.VIKINGFIGHTER) and self.units(UnitTypeId.VIKINGFIGHTER).amount < self.army_advisor.max_vikings:
                st.build(UnitTypeId.VIKINGFIGHTER)
            elif self.can_afford(UnitTypeId.MEDIVAC) and self.units(UnitTypeId.MEDIVAC).amount < self.army_advisor.max_medivacs:
                st.build(UnitTypeId.MEDIVAC)
            elif self.can_afford(UnitTypeId.VIKINGFIGHTER) and self.units(UnitTypeId.VIKINGFIGHTER).amount < self.army_advisor.max_vikings:
                st.build(UnitTypeId.VIKINGFIGHTER)
    
    if self.produce_from_factories:
        for fac in self.structures(UnitTypeId.FACTORY).ready.idle:
                if fac.has_techlab:
                    if self.can_afford(UnitTypeId.SIEGETANK) and self.units.of_type({UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED}).amount < self.army_advisor.max_tanks:
                        fac.build(UnitTypeId.SIEGETANK)
                    elif self.can_afford(UnitTypeId.CYCLONE) and self.units(UnitTypeId.CYCLONE).amount < self.army_advisor.max_cyclones:
                        fac.build(UnitTypeId.CYCLONE)
                elif fac.has_reactor:
                    if self.can_afford(UnitTypeId.CYCLONE) and self.units(UnitTypeId.CYCLONE).amount < self.army_advisor.max_cyclones:
                        fac.build(UnitTypeId.CYCLONE)
                        if self.can_afford(UnitTypeId.CYCLONE) and self.units(UnitTypeId.CYCLONE).amount < self.army_advisor.max_cyclones:
                            fac.build(UnitTypeId.CYCLONE)
                    elif self.can_afford(UnitTypeId.HELLION) and self.units(UnitTypeId.HELLION).amount < self.army_advisor.max_hellions:
                        fac.build(UnitTypeId.HELLION)
                        if self.can_afford(UnitTypeId.HELLION) and self.units(UnitTypeId.HELLION).amount < self.army_advisor.max_hellions:
                            fac.build(UnitTypeId.HELLION)
                elif self.can_afford(UnitTypeId.CYCLONE) and self.units(UnitTypeId.CYCLONE).amount < self.army_advisor.max_cyclones:
                    fac.build(UnitTypeId.CYCLONE)
                elif self.can_afford(UnitTypeId.HELLION) and self.units(UnitTypeId.HELLION).amount < self.army_advisor.max_hellions:
                    fac.build(UnitTypeId.HELLION)

        for fac in self.structures(UnitTypeId.FACTORY).ready:
            if not fac.has_reactor:
                continue
            if len(fac.orders) == 1:
                if self.can_afford(UnitTypeId.CYCLONE) and self.units(UnitTypeId.CYCLONE).amount < self.army_advisor.max_cyclones:
                    fac.build(UnitTypeId.CYCLONE)
                elif self.can_afford(UnitTypeId.HELLION) and self.units(UnitTypeId.HELLION).amount < self.army_advisor.max_hellions:
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
                elif self.army_count == 0 and (self.can_afford(UnitTypeId.REAPER) or (self.minerals >= 50 and self.vespene >= 40)): # if can buy or almost buy
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
                elif self.army_count == 0 and (self.can_afford(UnitTypeId.REAPER) or (self.minerals >= 50 and self.vespene >= 40)): # if can buy or almost buy
                    bar.build(UnitTypeId.REAPER)
                elif self.can_afford(UnitTypeId.MARINE):
                    bar.build(UnitTypeId.MARINE)

            for bar in self.structures(UnitTypeId.BARRACKS).ready:
                if not bar.has_reactor:
                    continue
                if len(bar.orders) == 1 and self.can_afford(UnitTypeId.MARINE):
                    bar.build(UnitTypeId.MARINE)