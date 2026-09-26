from typing import Optional, Tuple

from sc2.ids.unit_typeid import UnitTypeId
from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.data import Race


made_banshee = False
made_raven = False

# the units the scouting can call for money to be held back for (see reactions.py): where each is made (and whether that building needs a
# tech lab), and how many we want of it
_PRIORITY_MAKERS = {
    UnitTypeId.SIEGETANK: (UnitTypeId.FACTORY, True),
    UnitTypeId.RAVEN: (UnitTypeId.STARPORT, True),
    UnitTypeId.VIKINGFIGHTER: (UnitTypeId.STARPORT, False),
}


def priority_reserve(self : BotAI) -> Optional[Tuple[UnitTypeId, int, int]]:
    """The unit money is being held back for right now, with its price: (unit, minerals, gas) - or None.

    Cheap units that are bought all the time (Marines: 50 minerals, from several Barracks) never let the bank reach the price of an
    expensive one (a Siege Tank: 150) - whatever comes in is spent as it arrives, and the Factory that stands ready to build the tank
    waits for ever. So when the scouting has made a unit our priority (army_advisor.priority_units) and a building that can make it is
    standing ready and idle, everything else in `produce` may only spend what is left over after its price.

    Nothing is held back when it would be for nothing: the unit is not wanted any more (enough of them), nothing that can make it is
    idle, or the gas or the supply for it is missing (holding minerals for that would stall everything and buy nothing)."""
    advisor = self.army_advisor
    for unit in advisor.priority_units:
        if unit not in _PRIORITY_MAKERS:
            continue
        maker, needs_techlab = _PRIORITY_MAKERS[unit]
        if unit == UnitTypeId.SIEGETANK:
            wanted = advisor.max_tanks
            have = self.units.of_type({UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED}).amount
            allowed = self.produce_from_factories
        elif unit == UnitTypeId.RAVEN:
            wanted, have, allowed = 1, self.units(UnitTypeId.RAVEN).amount, self.produce_from_starports
        else:
            wanted, have, allowed = advisor.max_vikings, self.units(UnitTypeId.VIKINGFIGHTER).amount, self.produce_from_starports
        if not allowed or have + self.already_pending(unit) >= wanted:
            continue
        idle = [b for b in self.structures(maker).ready.idle if b.has_techlab or not needs_techlab]
        cost = self.calculate_cost(unit)
        if not idle or self.vespene < cost.vespene or self.supply_left < self.calculate_supply_cost(unit):
            continue
        return unit, cost.minerals, cost.vespene
    return None


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

    # what may be spent on `unit_type` without keeping the priority unit (see priority_reserve) from being afforded
    reserve = priority_reserve(self)

    def afford(unit_type) -> bool:
        if not self.can_afford(unit_type):
            return False
        if reserve is None or reserve[0] == unit_type:
            return True
        cost = self.calculate_cost(unit_type)
        return self.minerals - cost.minerals >= reserve[1] and self.vespene - cost.vespene >= reserve[2]

    less_reapers = self.units.of_type({UnitTypeId.REAPER}).amount < self.army_advisor.amount_of_enemies_of_type(UnitTypeId.REAPER)

    if self.produce_from_starports:
        for st in self.structures(UnitTypeId.STARPORT).ready.idle:

            # first get a banshee, then a raven, then free to choose - or the raven first, when what we scouted needs a detector (Dark
            # Templar, burrowed Lurkers or mines: army_advisor.raven_first). has_techlab gates the OUTER condition, not just the inner
            # build: a Reactor/bare Starport can never build either one, so it used to just sit here doing nothing every call (hitting
            # the unconditional continue below) instead of falling through to Medivac/Viking production while waiting for a techlab
            # Starport to afford the first Banshee/Raven
            spoken_for = False
            for unit_type in ((UnitTypeId.RAVEN, UnitTypeId.BANSHEE) if self.army_advisor.raven_first else (UnitTypeId.BANSHEE, UnitTypeId.RAVEN)):
                banshee = unit_type == UnitTypeId.BANSHEE
                cap = self.army_advisor.max_banshees if banshee else self.army_advisor.max_ravens
                if st.has_techlab and self.units(unit_type).amount == 0 and cap > 0 and not (made_banshee if banshee else made_raven):
                    if afford(unit_type):
                        st.build(unit_type)
                        if banshee:
                            made_banshee = True
                        else:
                            made_raven = True
                    spoken_for = True
                    break
            if spoken_for:
                continue

            # Vikings jump the rest of this queue once something has made them our actual answer
            # (skytoss right now) - every other Starport choice below is a nice-to-have by
            # comparison, and previously got built first regardless, delaying our real counter
            if self.army_advisor.prioritize_vikings and afford(UnitTypeId.VIKINGFIGHTER) and self.units(UnitTypeId.VIKINGFIGHTER).amount < self.army_advisor.max_vikings:
                st.build(UnitTypeId.VIKINGFIGHTER)
                # +1: account for the one just queued above, which .amount won't reflect yet -
                # otherwise this can queue one past max_vikings every time a reactor Starport has
                # exactly 1 slot of headroom left (matches the Liberator branch's correct pattern below)
                if st.has_reactor and afford(UnitTypeId.VIKINGFIGHTER) and self.units(UnitTypeId.VIKINGFIGHTER).amount + 1 < self.army_advisor.max_vikings:
                    st.build(UnitTypeId.VIKINGFIGHTER)
                continue

            total_liberators = self.units(UnitTypeId.LIBERATOR).amount + self.units(UnitTypeId.LIBERATORAG).amount
            if st.has_techlab and afford(UnitTypeId.RAVEN) and self.units(UnitTypeId.RAVEN).amount < self.army_advisor.max_ravens:
                st.build(UnitTypeId.RAVEN)
            elif st.has_techlab and self.structures(UnitTypeId.FUSIONCORE).amount > 0 and afford(UnitTypeId.BATTLECRUISER) and self.units(UnitTypeId.BATTLECRUISER).amount < self.army_advisor.max_battlecruisers:
                st.build(UnitTypeId.BATTLECRUISER)
            # no techlab/reactor requirement - only ever nonzero vs Terran once we've actually
            # spotted their Siege Tanks (see army_composition_advisor.py), so treat it with the
            # same urgency as Raven/BC rather than waiting behind Medivac/Banshee for no reason
            elif afford(UnitTypeId.LIBERATOR) and total_liberators < self.army_advisor.max_liberators:
                st.build(UnitTypeId.LIBERATOR)
                if st.has_reactor and afford(UnitTypeId.LIBERATOR) and total_liberators + 1 < self.army_advisor.max_liberators:
                    st.build(UnitTypeId.LIBERATOR)
            elif st.has_techlab and afford(UnitTypeId.MEDIVAC) and self.units(UnitTypeId.MEDIVAC).amount < self.army_advisor.max_medivacs:
                st.build(UnitTypeId.MEDIVAC)
            elif st.has_techlab and afford(UnitTypeId.VIKINGFIGHTER) and self.units(UnitTypeId.VIKINGFIGHTER).amount < self.army_advisor.max_vikings:
                st.build(UnitTypeId.VIKINGFIGHTER)
            elif st.has_techlab and afford(UnitTypeId.BANSHEE) and self.units(UnitTypeId.BANSHEE).amount < self.army_advisor.max_banshees:
                st.build(UnitTypeId.BANSHEE)
            elif st.has_reactor and afford(UnitTypeId.MEDIVAC) and self.units(UnitTypeId.MEDIVAC).amount < self.army_advisor.max_medivacs:
                st.build(UnitTypeId.MEDIVAC)
                # +1: account for the one just queued - this previously had no cap check on the
                # second build at all, so it could queue straight past max_medivacs every time
                if afford(UnitTypeId.MEDIVAC) and self.units(UnitTypeId.MEDIVAC).amount + 1 < self.army_advisor.max_medivacs:
                    st.build(UnitTypeId.MEDIVAC)
            elif st.has_reactor and afford(UnitTypeId.VIKINGFIGHTER) and self.units(UnitTypeId.VIKINGFIGHTER).amount < self.army_advisor.max_vikings:
                st.build(UnitTypeId.VIKINGFIGHTER)
                if afford(UnitTypeId.VIKINGFIGHTER) and self.units(UnitTypeId.VIKINGFIGHTER).amount + 1 < self.army_advisor.max_vikings:
                    st.build(UnitTypeId.VIKINGFIGHTER)
            elif afford(UnitTypeId.MEDIVAC) and self.units(UnitTypeId.MEDIVAC).amount < self.army_advisor.max_medivacs:
                st.build(UnitTypeId.MEDIVAC)
            elif afford(UnitTypeId.VIKINGFIGHTER) and self.units(UnitTypeId.VIKINGFIGHTER).amount < self.army_advisor.max_vikings:
                st.build(UnitTypeId.VIKINGFIGHTER)
        
        for st in self.structures(UnitTypeId.STARPORT).ready:
            if not st.has_reactor:
                continue
            if len(st.orders) != 1:
                continue
            if self.army_advisor.prioritize_vikings and afford(UnitTypeId.VIKINGFIGHTER) and self.units(UnitTypeId.VIKINGFIGHTER).amount < self.army_advisor.max_vikings:
                st.build(UnitTypeId.VIKINGFIGHTER)
            elif afford(UnitTypeId.MEDIVAC) and self.units(UnitTypeId.MEDIVAC).amount < self.army_advisor.max_medivacs:
                st.build(UnitTypeId.MEDIVAC)
            elif afford(UnitTypeId.VIKINGFIGHTER) and self.units(UnitTypeId.VIKINGFIGHTER).amount < self.army_advisor.max_vikings:
                st.build(UnitTypeId.VIKINGFIGHTER)
    
    if self.produce_from_factories:
        for fac in self.structures(UnitTypeId.FACTORY).ready.idle:
                if fac.has_techlab:
                    if afford(UnitTypeId.SIEGETANK) and self.units.of_type({UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED}).amount < self.army_advisor.max_tanks:
                        fac.build(UnitTypeId.SIEGETANK)
                    elif afford(UnitTypeId.CYCLONE) and self.units(UnitTypeId.CYCLONE).amount < self.army_advisor.max_cyclones:
                        fac.build(UnitTypeId.CYCLONE)
                elif fac.has_reactor:
                    if afford(UnitTypeId.CYCLONE) and self.units(UnitTypeId.CYCLONE).amount < self.army_advisor.max_cyclones:
                        fac.build(UnitTypeId.CYCLONE)
                        # the first one isn't counted in units() yet, so + 1 - otherwise the pair overshoots the cap by one
                        if afford(UnitTypeId.CYCLONE) and self.units(UnitTypeId.CYCLONE).amount + 1 < self.army_advisor.max_cyclones:
                            fac.build(UnitTypeId.CYCLONE)
                    elif afford(UnitTypeId.HELLION) and self.units(UnitTypeId.HELLION).amount < self.army_advisor.max_hellions:
                        fac.build(UnitTypeId.HELLION)
                        if afford(UnitTypeId.HELLION) and self.units(UnitTypeId.HELLION).amount + 1 < self.army_advisor.max_hellions:
                            fac.build(UnitTypeId.HELLION)
                elif afford(UnitTypeId.CYCLONE) and self.units(UnitTypeId.CYCLONE).amount < self.army_advisor.max_cyclones:
                    fac.build(UnitTypeId.CYCLONE)
                elif afford(UnitTypeId.HELLION) and self.units(UnitTypeId.HELLION).amount < self.army_advisor.max_hellions:
                    fac.build(UnitTypeId.HELLION)

        for fac in self.structures(UnitTypeId.FACTORY).ready:
            if not fac.has_reactor:
                continue
            if len(fac.orders) == 1:
                if afford(UnitTypeId.CYCLONE) and self.units(UnitTypeId.CYCLONE).amount < self.army_advisor.max_cyclones:
                    fac.build(UnitTypeId.CYCLONE)
                elif afford(UnitTypeId.HELLION) and self.units(UnitTypeId.HELLION).amount < self.army_advisor.max_hellions:
                    fac.build(UnitTypeId.HELLION)

    if self.produce_from_barracks:
        total_marines = self.units.of_type({UnitTypeId.MARINE}).amount
        total_marauders = self.units.of_type({UnitTypeId.MARAUDER}).amount

        #if less_reapers: # if we have less reapers than enemy, make more reapers (can also be fixed by rushing cyclone)
        #    produce_single_type_unit(self, UnitTypeId.BARRACKS, UnitTypeId.REAPER, UnitTypeId.MARINE)
        if total_marauders != 0 and total_marines / (total_marines + total_marauders) < self.army_advisor.marine_marauder_ratio: # if not enough marines, make only of them
            for bar in self.structures(UnitTypeId.BARRACKS).ready.idle:
                if bar.has_techlab and afford(UnitTypeId.MARINE):
                    bar.build(UnitTypeId.MARINE)
                elif bar.has_reactor and afford(UnitTypeId.MARINE):
                    bar.build(UnitTypeId.MARINE)
                    if afford(UnitTypeId.MARINE):
                        bar.build(UnitTypeId.MARINE)
                elif self.army_count == 0 and (afford(UnitTypeId.REAPER) or (self.minerals >= 50 and self.vespene >= 40)): # if can buy or almost buy
                    bar.build(UnitTypeId.REAPER)
                elif afford(UnitTypeId.MARINE):
                    bar.build(UnitTypeId.MARINE)
            
            for bar in self.structures(UnitTypeId.BARRACKS).ready:
                if not bar.has_reactor:
                    continue
                if len(bar.orders) == 1 and afford(UnitTypeId.MARINE):
                    bar.build(UnitTypeId.MARINE)

        else:
            for bar in self.structures(UnitTypeId.BARRACKS).ready.idle:
                if bar.has_techlab and afford(UnitTypeId.MARAUDER):
                    bar.build(UnitTypeId.MARAUDER)
                elif bar.has_reactor and afford(UnitTypeId.MARINE):
                    bar.build(UnitTypeId.MARINE)
                    if afford(UnitTypeId.MARINE):
                        bar.build(UnitTypeId.MARINE)
                elif self.army_count == 0 and (afford(UnitTypeId.REAPER) or (self.minerals >= 50 and self.vespene >= 40)): # if can buy or almost buy
                    bar.build(UnitTypeId.REAPER)
                elif afford(UnitTypeId.MARINE):
                    bar.build(UnitTypeId.MARINE)

            for bar in self.structures(UnitTypeId.BARRACKS).ready:
                if not bar.has_reactor:
                    continue
                if len(bar.orders) == 1 and afford(UnitTypeId.MARINE):
                    bar.build(UnitTypeId.MARINE)