"""Shared constants for army control: unit-type groups and the fight-confidence thresholds.

The thresholds are expressed in Ares' EngagementResult scale (0 = LOSS_EMPHATIC ... 5 = TIE ... 10 = VICTORY_EMPHATIC).
For a WIN the label says how much of OUR health is left afterwards (>=90% EMPHATIC, >=75% OVERWHELMING,
>=60% DECISIVE, >40% CLOSE, >20% MARGINAL); for a LOSS how much of THEIRS is left. All of them are tunables -
they were picked by reasoning, not by playtesting.
"""
from typing import FrozenSet

from ares.consts import EngagementResult
from sc2.ids.unit_typeid import UnitTypeId as U

# single definition of these lives with the shared pathing constants (the training bots use them too)
from bot.pathing.consts import (  # noqa: F401  (re-exported)
    ATTACK_TARGET_IGNORE,
    ATTACK_TARGET_IGNORE_WITH_WORKERS,
    DANGEROUS_STRUCTURES,
    SKYTOSS_TYPES,
)

# ----------------------------------------------------------------------------------------------------------------
# unit-type groups
# ----------------------------------------------------------------------------------------------------------------
BIO_TYPES: FrozenSet[U] = frozenset({U.MARINE, U.MARAUDER})
TANK_TYPES: FrozenSet[U] = frozenset({U.SIEGETANK, U.SIEGETANKSIEGED})
LIBERATOR_TYPES: FrozenSet[U] = frozenset({U.LIBERATOR, U.LIBERATORAG})
VIKING_TYPES: FrozenSet[U] = frozenset({U.VIKINGFIGHTER})
MEDIVAC_TYPES: FrozenSet[U] = frozenset({U.MEDIVAC})
RAVEN_TYPES: FrozenSet[U] = frozenset({U.RAVEN})
CYCLONE_TYPES: FrozenSet[U] = frozenset({U.CYCLONE})
BANSHEE_TYPES: FrozenSet[U] = frozenset({U.BANSHEE})
REAPER_TYPES: FrozenSet[U] = frozenset({U.REAPER})

# everything that is not a dedicated micro class above falls into the generic kiting controller
# (hellions/hellbats, thors, battlecruisers, widow mines, ghosts, landed vikings, ...)
DEDICATED_TYPES: FrozenSet[U] = (
    BIO_TYPES | TANK_TYPES | LIBERATOR_TYPES | VIKING_TYPES | MEDIVAC_TYPES | RAVEN_TYPES | CYCLONE_TYPES
    | BANSHEE_TYPES | REAPER_TYPES
)

NON_ARMY_TYPES: FrozenSet[U] = frozenset({U.SCV, U.MULE})

# Banelings are the one enemy every kiting unit ALWAYS backs away from - whatever the simulator says about the fight, whatever
# else outranges us, no "kite in" (see units/common.kite_from_banelings). Ares' danger grid only marks a radius of 3 around a
# baneling, about a second of its running time, so the trigger is the distance itself and not the grid.
BANELING_TYPES: FrozenSet[U] = frozenset({U.BANELING, U.BANELINGBURROWED})

# enemy units that are not part of "their army" when sizing up a fight or tracking what we've seen
ENEMY_WORKER_TYPES: FrozenSet[U] = frozenset({U.SCV, U.PROBE, U.DRONE, U.DRONEBURROWED, U.MULE})
ENEMY_NON_ARMY_TYPES: FrozenSet[U] = frozenset(
    ENEMY_WORKER_TYPES | ATTACK_TARGET_IGNORE | {U.OVERLORD, U.OVERLORDTRANSPORT, U.OBSERVER, U.OBSERVERSIEGEMODE}
)

# static defenses that can only shoot AIR: the combat simulator is known to have them shoot ground units too,
# so they are left out of fights between ground forces (see FightEvaluator)
ANTI_AIR_ONLY_STRUCTURES: FrozenSet[U] = frozenset({U.MISSILETURRET, U.SPORECRAWLER, U.SPORECRAWLERUPROOTED})

# ----------------------------------------------------------------------------------------------------------------
# fight confidence thresholds (EngagementResult scale)
# ----------------------------------------------------------------------------------------------------------------
# strategic attack: commit the main army to a push only when the sim says we'd win keeping >=60% of our health
# against everything we know about
START_ATTACK_RESULT = EngagementResult.VICTORY_DECISIVE
# once committed, keep going until the sim says we are clearly losing (a close loss can still be turned by micro)
CONTINUE_ATTACK_RESULT = EngagementResult.LOSS_MARGINAL
# sizing detachments (base defense, small threats): smallest group that wins with a healthy margin
DETACHMENT_RESULT = EngagementResult.VICTORY_DECISIVE
# a fight right around a squad is lopsided enough to push in instead of kiting away ("very very high" confidence)
KITE_IN_RESULT = EngagementResult.VICTORY_OVERWHELMING
# a local fight where the sim says we get crushed - disengage instead of trading (unless cornered / futile to run)
LOCAL_RETREAT_RESULT = EngagementResult.LOSS_CLOSE

# ----------------------------------------------------------------------------------------------------------------
# ranges and timings
# ----------------------------------------------------------------------------------------------------------------
NEAR_ENEMY_RADIUS = 15.0        # enemies within this of one of our units count as "in this fight" for its micro
BANELING_KITE_MARGIN = 1.0      # a unit backs away from banelings once one is inside ITS OWN weapon range plus this: any farther and it
                                # would retreat without shooting (it cannot reach them yet) and get caught anyway; any closer is too late
BANELING_RETREAT_DISTANCE = 6.0 # ... towards a point this far from them, on the side away from their centre
LOCAL_FIGHT_RADIUS = 14.0       # radius (around a squad) used for the local fight assessment - user-tuned value
SQUAD_RADIUS = 9.0              # Ares squad clustering radius for the main army (units farther apart split off)
THREAT_CLUSTER_RADIUS = 9.0     # enemy units this close to each other form one "threat"
BASE_THREAT_RADIUS = 30.0       # an enemy this close to one of our structures is a threat to that base
GROUPED_FRACTION = 0.75         # fraction of the ground army that must be in the main squad to START a push

# army "maxed" rule (kept from the previous version): attack at full supply regardless of the sim
MAXED_SUPPLY_CAP = 196
MAXED_SUPPLY_LEFT = 4

# ---- assault staging (creeping tanks up to static defense before the army commits) ---------------------------------
STAGING_MIN_TANKS = 2           # only worth staging with at least this many tanks
STAGING_STANDOFF = 12.5         # stage this far from the nearest static defense / sieged tank - inside a sieged tank's 13 range, outside theirs (6-7)
STAGING_TRIGGER_RANGE = 45.0    # start staging once the army is within this of such a defense
STAGING_TIMEOUT = 30.0          # never wait at the staging point longer than this
STAGING_COOLDOWN = 60.0         # after staging (or giving up), push straight in for this long before staging again
STAGING_ARRIVAL_RANGE = 8.0     # a tank this close to the staging point sieges up
