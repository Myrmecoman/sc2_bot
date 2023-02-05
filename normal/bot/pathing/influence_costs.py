"""
This is used in `pathing.py`
These are units where we want to define our own weights and costs
Some of these units don't have a "weapon" in the API so we provide values for range and cost here
Some of these units might have a weapon but we can declare custom values
For any units not declared here we take values from the API instead when adding influence
"""

from typing import Dict
from sc2.ids.unit_typeid import UnitTypeId

INFLUENCE_COSTS: Dict[UnitTypeId, Dict] = {
    UnitTypeId.ADEPT: {"AirCost": 0, "GroundCost": 9, "AirRange": 0, "GroundRange": 5},
    UnitTypeId.ADEPTPHASESHIFT: {
        "AirCost": 0,
        "GroundCost": 9,
        "AirRange": 0,
        "GroundRange": 5,
    },
    UnitTypeId.AUTOTURRET: {
        "AirCost": 31,
        "GroundCost": 31,
        "AirRange": 7,
        "GroundRange": 7,
    },
    UnitTypeId.MISSILETURRET: {
        "AirCost": 24,
        "GroundCost": 0,
        "AirRange": 7,
        "GroundRange": 0,
        "DetectionRange": 11,
    },
    UnitTypeId.ARCHON: {
        "AirCost": 40,
        "GroundCost": 40,
        "AirRange": 3,
        "GroundRange": 3,
    },
    UnitTypeId.BANELING: {
        "AirCost": 0,
        "GroundCost": 20,
        "AirRange": 0,
        "GroundRange": 3,
    },
    UnitTypeId.BANSHEE: {
        "AirCost": 0,
        "GroundCost": 12,
        "AirRange": 0,
        "GroundRange": 6,
    },
    UnitTypeId.BATTLECRUISER: {
        "AirCost": 31,
        "GroundCost": 50,
        "AirRange": 6,
        "GroundRange": 6,
    },
    UnitTypeId.BUNKER: {
        "AirCost": 22,
        "GroundCost": 22,
        "AirRange": 6,
        "GroundRange": 6,
    },
    UnitTypeId.CARRIER: {
        "AirCost": 20,
        "GroundCost": 20,
        "AirRange": 11,
        "GroundRange": 11,
    },
    UnitTypeId.CORRUPTOR: {
        "AirCost": 10,
        "GroundCost": 0,
        "AirRange": 6,
        "GroundRange": 0,
    },
    UnitTypeId.CYCLONE: {
        "AirCost": 27,
        "GroundCost": 27,
        "AirRange": 7,
        "GroundRange": 7,
    },
    UnitTypeId.GHOST: {
        "AirCost": 10,
        "GroundCost": 10,
        "AirRange": 6,
        "GroundRange": 6,
    },
    UnitTypeId.HELLION: {
        "AirCost": 0,
        "GroundCost": 8,
        "AirRange": 0,
        "GroundRange": 8,
    },
    UnitTypeId.HYDRALISK: {
        "AirCost": 20,
        "GroundCost": 20,
        "AirRange": 6,
        "GroundRange": 6,
    },
    UnitTypeId.INFESTOR: {
        "AirCost": 30,
        "GroundCost": 30,
        "AirRange": 10,
        "GroundRange": 10,
    },
    UnitTypeId.LIBERATOR: {
        "AirCost": 10,
        "GroundCost": 0,
        "AirRange": 5,
        "GroundRange": 0,
    },
    UnitTypeId.MARINE: {
        "AirCost": 10,
        "GroundCost": 10,
        "AirRange": 5,
        "GroundRange": 5,
    },
    UnitTypeId.MOTHERSHIP: {
        "AirCost": 23,
        "GroundCost": 23,
        "AirRange": 7,
        "GroundRange": 7,
    },
    UnitTypeId.MUTALISK: {
        "AirCost": 8,
        "GroundCost": 8,
        "AirRange": 3,
        "GroundRange": 3,
    },
    UnitTypeId.ORACLE: {
        "AirCost": 0,
        "GroundCost": 24,
        "AirRange": 0,
        "GroundRange": 4,
    },
    UnitTypeId.PHOENIX: {
        "AirCost": 15,
        "GroundCost": 0,
        "AirRange": 7,
        "GroundRange": 0,
    },
    UnitTypeId.PHOTONCANNON: {
        "AirCost": 22,
        "GroundCost": 22,
        "AirRange": 7,
        "GroundRange": 7,
        "DetectionRange": 11,
    },
    UnitTypeId.QUEEN: {
        "AirCost": 12.6,
        "GroundCost": 11.2,
        "AirRange": 7,
        "GroundRange": 5,
    },
    UnitTypeId.SENTRY: {
        "AirCost": 8.4,
        "GroundCost": 8.4,
        "AirRange": 5,
        "GroundRange": 5,
    },
    UnitTypeId.SPINECRAWLER: {
        "AirCost": 0,
        "GroundCost": 15,
        "AirRange": 0,
        "GroundRange": 7,
    },
    UnitTypeId.SPORECRAWLER: {
        "AirCost": 15,
        "GroundCost": 0,
        "AirRange": 7,
        "GroundRange": 0,
        "DetectionRange": 11,
    },
    UnitTypeId.STALKER: {
        "AirCost": 10,
        "GroundCost": 10,
        "AirRange": 6,
        "GroundRange": 6,
    },
    UnitTypeId.TEMPEST: {
        "AirCost": 17,
        "GroundCost": 17,
        "AirRange": 14,
        "GroundRange": 10,
    },
    UnitTypeId.THOR: {
        "AirCost": 28,
        "GroundCost": 28,
        "AirRange": 11,
        "GroundRange": 7,
    },
    UnitTypeId.VIKINGASSAULT: {
        "AirCost": 0,
        "GroundCost": 17,
        "AirRange": 0,
        "GroundRange": 6,
    },
    UnitTypeId.VIKINGFIGHTER: {
        "AirCost": 14,
        "GroundCost": 0,
        "AirRange": 9,
        "GroundRange": 0,
    },
    UnitTypeId.VOIDRAY: {
        "AirCost": 20,
        "GroundCost": 20,
        "AirRange": 6,
        "GroundRange": 6,
    },
    UnitTypeId.WIDOWMINEBURROWED: {
        "AirCost": 150,
        "GroundCost": 150,
        "AirRange": 5.5,
        "GroundRange": 5.5,
    },
    UnitTypeId.DRONE: {
        "AirCost": 0,
        "GroundCost": 5,
        "AirRange": 0,
        "GroundRange": 1,
    },
    UnitTypeId.PROBE: {
        "AirCost": 0,
        "GroundCost": 5,
        "AirRange": 0,
        "GroundRange": 1,
    },
    UnitTypeId.SCV: {
        "AirCost": 0,
        "GroundCost": 5,
        "AirRange": 0,
        "GroundRange": 1,
    },
    UnitTypeId.ZEALOT: {
        "AirCost": 0,
        "GroundCost": 16,
        "AirRange": 0,
        "GroundRange": 1,
    },
    UnitTypeId.ZERGLING: {
        "AirCost": 0,
        "GroundCost": 5,
        "AirRange": 0,
        "GroundRange": 1,
    },
    UnitTypeId.RAVEN: {
        "DetectionRange": 11,
    },
    UnitTypeId.OBSERVER: {
        "DetectionRange": 11,
    },
    UnitTypeId.OBSERVERSIEGEMODE: {
        "DetectionRange": 17,
    },
    UnitTypeId.OVERSEER: {
        "DetectionRange": 11,
    },
    UnitTypeId.OVERSEERSIEGEMODE: {
        "DetectionRange": 17,
    },
}
