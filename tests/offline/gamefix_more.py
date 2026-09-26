"""More unit types (approximate LotV stats) for the offline fixture: importing this module extends gamefix.STATS."""
from sc2.ids.unit_typeid import UnitTypeId as U
import gamefix
from gamefix import GROUND, AIR, ANY, LIGHT, ARMORED, BIO, MECH, ROBOTIC, PSI, MASSIVE, STRUCT
U_ = U
gamefix.STATS.update({
    U.GHOST: (100, 0, 0, 3.94, [(ANY, 10, 1, 6, 1.07, [(LIGHT, 10)])], [LIGHT, BIO, PSI], 150, 125, 2),
    U.HELLIONTANK: (135, 0, 0, 3.15, [(GROUND, 18, 1, 2, 1.43, [(LIGHT, 12)])], [ARMORED, BIO, MECH], 100, 0, 2),
    U.THOR: (400, 0, 2, 2.62, [(GROUND, 30, 2, 7, 0.91, []), (AIR, 6, 4, 10, 2.14, [(LIGHT, 6)])], [ARMORED, MECH, MASSIVE], 300, 200, 6),
    U.THORAP: (400, 0, 2, 2.62, [(GROUND, 30, 2, 7, 0.91, []), (AIR, 25, 1, 10, 1.75, [(MASSIVE, 10)])], [ARMORED, MECH, MASSIVE], 300, 200, 6),
    U.WIDOWMINE: (90, 0, 0, 3.94, [(ANY, 125, 1, 5, 29, [])], [LIGHT, MECH], 75, 25, 2),
    U.WIDOWMINEBURROWED: (90, 0, 0, 0.0, [(ANY, 125, 1, 5, 29, [])], [LIGHT, MECH], 75, 25, 2),
    U.VIKINGASSAULT: (135, 0, 0, 3.15, [(GROUND, 12, 1, 6, 0.71, [(MECH, 8)])], [ARMORED, MECH], 150, 75, 2),
    U.SENTRY: (40, 40, 1, 3.15, [(ANY, 6, 1, 5, 0.71, [])], [LIGHT, MECH, PSI], 50, 100, 2),
    U.ADEPT: (70, 70, 1, 3.5, [(GROUND, 10, 1, 4, 1.61, [(LIGHT, 12)])], [LIGHT, BIO], 100, 25, 2),
    U.HIGHTEMPLAR: (40, 40, 0, 2.62, [], [LIGHT, BIO, PSI], 50, 150, 2),
    U.DARKTEMPLAR: (40, 80, 1, 3.94, [(GROUND, 45, 1, 0.1, 1.21, [])], [LIGHT, BIO, PSI], 125, 125, 2),
    U.ARCHON: (10, 350, 0, 3.94, [(ANY, 25, 1, 3, 1.25, [(BIO, 10)])], [PSI, MASSIVE], 100, 300, 4),
    U.COLOSSUS: (200, 150, 1, 3.15, [(GROUND, 10, 2, 7, 1.07, [(LIGHT, 5)])], [ARMORED, MECH, ROBOTIC, MASSIVE], 300, 200, 6),
    U.DISRUPTOR: (100, 100, 1, 3.15, [], [ARMORED, MECH, ROBOTIC], 150, 150, 3),
    U.PHOENIX: (120, 60, 0, 5.95, [(AIR, 5, 2, 5, 0.79, [(LIGHT, 5)])], [LIGHT, MECH], 150, 100, 2),
    U.CARRIER: (300, 150, 2, 2.62, [(ANY, 5, 8, 8, 2.14, [])], [ARMORED, MECH, MASSIVE], 350, 250, 6),
    U.TEMPEST: (200, 100, 2, 3.15, [(GROUND, 40, 1, 10, 2.36, []), (AIR, 30, 1, 14, 2.36, [(MASSIVE, 22)])], [ARMORED, MECH, MASSIVE], 250, 175, 5),
    U.ORACLE: (100, 60, 0, 5.6, [(GROUND, 15, 1, 4, 0.61, [(LIGHT, 7)])], [ARMORED, MECH], 150, 150, 3),
    U.MOTHERSHIP: (350, 350, 2, 2.62, [(ANY, 6, 6, 7, 2.14, [])], [ARMORED, MECH, MASSIVE], 400, 400, 8),
    U.OBSERVER: (40, 20, 0, 2.63, [], [LIGHT, MECH, ROBOTIC], 25, 75, 1),
    U.WARPPRISM: (80, 100, 0, 4.13, [], [ARMORED, MECH, ROBOTIC, PSI], 250, 0, 2),
    U.SHIELDBATTERY: (150, 150, 1, 0.0, [], [ARMORED, MECH, STRUCT], 100, 0, 0),
    U.INTERCEPTOR: (40, 40, 0, 10.5, [(ANY, 5, 2, 2, 3.0, [])], [LIGHT, MECH], 15, 0, 0),
    U.BANELING: (30, 0, 0, 3.5, [(GROUND, 16, 1, 0.25, 0.5, [(LIGHT, 19)])], [LIGHT, BIO], 25, 25, 0.5),
    U.RAVAGER: (120, 0, 1, 3.85, [(GROUND, 16, 1, 6, 1.14, [])], [BIO], 100, 100, 3),
    U.LURKERMP: (200, 0, 1, 4.13, [(GROUND, 20, 1, 8, 1.43, [(ARMORED, 10)])], [ARMORED, BIO], 150, 150, 3),
    U.LURKERMPBURROWED: (200, 0, 1, 0.0, [(GROUND, 20, 1, 8, 1.43, [(ARMORED, 10)])], [ARMORED, BIO], 150, 150, 3),
    U.QUEEN: (175, 0, 1, 1.31, [(GROUND, 4, 2, 5, 0.71, []), (AIR, 9, 1, 7, 0.71, [])], [BIO, PSI], 150, 0, 2),
    U.CORRUPTOR: (200, 0, 2, 4.72, [(AIR, 14, 1, 6, 1.36, [(MASSIVE, 6)])], [ARMORED, BIO], 150, 100, 2),
    U.BROODLORD: (225, 0, 1, 1.97, [(GROUND, 20, 1, 10, 1.79, [])], [ARMORED, BIO, MASSIVE], 300, 250, 4),
    U.INFESTOR: (90, 0, 0, 3.15, [], [ARMORED, BIO, PSI], 100, 150, 2),
    U.SWARMHOSTMP: (160, 0, 1, 3.15, [], [ARMORED, BIO], 100, 75, 3),
    U.VIPER: (120, 0, 1, 4.13, [], [ARMORED, BIO, PSI], 100, 200, 3),
    U.LOCUSTMP: (50, 0, 0, 2.62, [(GROUND, 10, 1, 3, 0.43, [])], [LIGHT, BIO], 0, 0, 0),
    U.INFESTEDTERRAN: (50, 0, 0, 3.15, [(GROUND, 8, 1, 5, 0.61, [])], [LIGHT, BIO], 0, 0, 0),
    U.SPORECRAWLER: (400, 0, 1, 0.0, [(AIR, 15, 1, 7, 0.61, [(BIO, 15)])], [ARMORED, BIO, STRUCT], 75, 0, 0),
    U.OVERSEER: (200, 0, 1, 2.62, [], [ARMORED, BIO], 50, 50, 0),
    U.BROODLING: (30, 0, 0, 5.37, [(GROUND, 4, 1, 0.1, 0.46, [])], [LIGHT, BIO], 0, 0, 0),
    U.ROACHBURROWED: (145, 0, 1, 3.15, [(GROUND, 16, 1, 4, 1.43, [])], [ARMORED, BIO], 75, 25, 2),
    U.ZERGLINGBURROWED: (35, 0, 0, 4.13, [(GROUND, 5, 1, 0.1, 0.497, [])], [LIGHT, BIO], 25, 0, 0.5),
})
gamefix.FLYING_TYPES.update({U.PHOENIX, U.CARRIER, U.TEMPEST, U.ORACLE, U.MOTHERSHIP, U.OBSERVER, U.WARPPRISM, U.VOIDRAY,
                             U.MUTALISK, U.CORRUPTOR, U.BROODLORD, U.VIPER, U.OVERSEER, U.INTERCEPTOR})

# a Raven's Auto-Turret (ours, a structure, next to whatever the Raven is fighting - possibly at the enemy's base)
gamefix.STATS[U.AUTOTURRET] = (150, 0, 1, 0.0, [(ANY, 18, 1, 6, 0.57, [])], [ARMORED, MECH, STRUCT], 0, 0, 0)

# a mineral field (neutral): the reapers' tour of the enemy's mineral lines and the banshees' repair spot look at where they are
gamefix.STATS[U.MINERALFIELD] = (100, 0, 0, 0.0, [], [], 0, 0, 0)

# tech structures the enemy shows us (what the scouting reactions look for, bot/reactions.py); approximate LotV stats
_TECH = lambda hp, mins, gas: (hp, 0, 1, 0.0, [], [ARMORED, STRUCT], mins, gas, 0)
gamefix.STATS.update({
    U.DARKSHRINE: _TECH(500, 150, 150), U.ROACHWARREN: _TECH(550, 150, 0), U.HYDRALISKDEN: _TECH(850, 100, 100),
    U.BANELINGNEST: _TECH(850, 100, 50), U.SPIRE: _TECH(850, 200, 200), U.GREATERSPIRE: _TECH(1000, 300, 350),
    U.LURKERDENMP: _TECH(850, 100, 150), U.STARGATE: _TECH(600, 150, 150), U.ROBOTICSBAY: _TECH(450, 150, 150),
    U.ULTRALISKCAVERN: _TECH(850, 150, 200), U.FUSIONCORE: _TECH(750, 150, 150),
})
