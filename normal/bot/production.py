from sc2.ids.unit_typeid import UnitTypeId
from sc2.bot_ai import BotAI
from sc2.data import Race


def amount_of_enemies_of_type(self : BotAI, type : UnitTypeId):
    enemies = 0
    for i in self.army_advisor.known_enemy_units.keys():
        if self.army_advisor.known_enemy_units[i][1] == type:
            enemies += 1
    return enemies


def produce_single_type_unit(self : BotAI, structure : UnitTypeId, techlab : UnitTypeId, reactor : UnitTypeId, unit : UnitTypeId, dumpunit : UnitTypeId = None):
    for s in self.structures(structure).ready.idle:
        if s.has_add_on:
            add_on = self.structures.find_by_tag(s.add_on_tag)
            if add_on is None:
                continue
            if add_on.type_id == techlab and self.can_afford(unit):
                s.build(unit)
            elif add_on.type_id == reactor and self.can_afford(unit):
                s.build(unit)
                if self.can_afford(unit):
                    s.build(unit)
                elif dumpunit is not None and self.can_afford(dumpunit):
                    s.build(dumpunit)
        elif self.can_afford(unit):
            s.build(unit)


def produce(self : BotAI):

    if self.produce_from_starports:
        for st in self.structures(UnitTypeId.STARPORT).ready.idle:
            if st.has_add_on:
                add_on = self.structures.find_by_tag(st.add_on_tag)
                if add_on is None:
                    continue
                if add_on.type_id == UnitTypeId.STARPORTTECHLAB and self.can_afford(UnitTypeId.RAVEN) and self.units(UnitTypeId.RAVEN).amount < self.army_advisor.max_ravens:
                    st.build(UnitTypeId.RAVEN)
                elif add_on.type_id == UnitTypeId.STARPORTTECHLAB and self.structures(UnitTypeId.FUSIONCORE).amount > 0 and self.can_afford(UnitTypeId.BATTLECRUISER) and self.units(UnitTypeId.BATTLECRUISER).amount < self.army_advisor.max_battlecruisers:
                    st.build(UnitTypeId.BATTLECRUISER)
                elif add_on.type_id == UnitTypeId.STARPORTTECHLAB and self.can_afford(UnitTypeId.MEDIVAC) and self.units(UnitTypeId.MEDIVAC).amount < self.army_advisor.max_medivacs:
                    st.build(UnitTypeId.MEDIVAC)
                elif add_on.type_id == UnitTypeId.STARPORTTECHLAB and self.can_afford(UnitTypeId.VIKINGFIGHTER) and self.units(UnitTypeId.VIKINGFIGHTER).amount < self.army_advisor.max_vikings:
                    st.build(UnitTypeId.VIKINGFIGHTER)
                elif add_on.type_id == UnitTypeId.STARPORTREACTOR and self.can_afford(UnitTypeId.MEDIVAC) and self.units(UnitTypeId.MEDIVAC).amount < self.army_advisor.max_medivacs:
                    st.build(UnitTypeId.MEDIVAC)
                    if self.can_afford(UnitTypeId.MEDIVAC):
                        st.build(UnitTypeId.MEDIVAC)
                elif add_on.type_id == UnitTypeId.STARPORTREACTOR and self.can_afford(UnitTypeId.VIKINGFIGHTER) and self.units(UnitTypeId.VIKINGFIGHTER).amount < self.army_advisor.max_vikings:
                    st.build(UnitTypeId.VIKINGFIGHTER)
                    if self.can_afford(UnitTypeId.VIKINGFIGHTER):
                        st.build(UnitTypeId.VIKINGFIGHTER)
            elif self.can_afford(UnitTypeId.MEDIVAC) and self.units(UnitTypeId.MEDIVAC).amount < self.army_advisor.max_medivacs:
                st.build(UnitTypeId.MEDIVAC)
            elif self.can_afford(UnitTypeId.VIKINGFIGHTER) and self.units(UnitTypeId.VIKINGFIGHTER).amount < self.army_advisor.max_vikings:
                st.build(UnitTypeId.VIKINGFIGHTER)
    
    if self.produce_from_factories:
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

    if self.produce_from_barracks:
        total_marines = self.units.of_type({UnitTypeId.MARINE}).amount
        total_marauders = self.units.of_type({UnitTypeId.MARAUDER}).amount

        if self.units.of_type({UnitTypeId.REAPER}).amount < amount_of_enemies_of_type(self, UnitTypeId.REAPER): # if we have less reapers than enemy, make more reapers
            produce_single_type_unit(self, UnitTypeId.BARRACKS, UnitTypeId.BARRACKSTECHLAB, UnitTypeId.BARRACKSREACTOR, UnitTypeId.REAPER, UnitTypeId.MARINE)
        elif total_marauders != 0 and total_marines / (total_marines + total_marauders) < self.army_advisor.marine_marauder_ratio: # if not enough marines, make only of them
            for bar in self.structures(UnitTypeId.BARRACKS).ready.idle:
                if bar.has_add_on:
                    add_on = self.structures.find_by_tag(bar.add_on_tag)
                    if add_on is None:
                        continue
                    if add_on.type_id == UnitTypeId.BARRACKSTECHLAB and self.can_afford(UnitTypeId.MARINE):
                        bar.build(UnitTypeId.MARINE)
                    elif add_on.type_id == UnitTypeId.BARRACKSREACTOR and self.can_afford(UnitTypeId.MARINE):
                        bar.build(UnitTypeId.MARINE)
                        if self.can_afford(UnitTypeId.MARINE):
                            bar.build(UnitTypeId.MARINE)
                elif self.army_count == 0 or (self.army_count < 2 and self.enemy_race == Race.Terran):
                    if self.can_afford(UnitTypeId.REAPER):
                        bar.build(UnitTypeId.REAPER)
                elif self.can_afford(UnitTypeId.MARINE):
                    bar.build(UnitTypeId.MARINE)
        else:
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
                elif self.army_count == 0 or (self.army_count < 2 and self.enemy_race == Race.Terran):
                    if self.can_afford(UnitTypeId.REAPER):
                        bar.build(UnitTypeId.REAPER)
                elif self.can_afford(UnitTypeId.MARINE):
                    bar.build(UnitTypeId.MARINE)
