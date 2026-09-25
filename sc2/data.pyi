"""Type stubs for sc2.data module

This stub provides static type information for dynamically generated enums.
The enums in sc2.data are created at runtime using enum.Enum() with protobuf
enum descriptors, which makes them invisible to static type checkers.

This stub file (PEP 561 compliant) allows type checkers like Pylance, Pyright,
and mypy to understand the structure and members of these enums.
"""

from __future__ import annotations

from enum import Enum

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId

class CreateGameError(Enum):
    MissingMap = 1
    InvalidMapPath = 2
    InvalidMapData = 3
    InvalidMapName = 4
    InvalidMapHandle = 5
    MissingPlayerSetup = 6
    InvalidPlayerSetup = 7
    MultiplayerUnsupported = 8

class PlayerType(Enum):
    Participant = 1
    Computer = 2
    Observer = 3

class Difficulty(Enum):
    VeryEasy = 1
    Easy = 2
    Medium = 3
    MediumHard = 4
    Hard = 5
    Harder = 6
    VeryHard = 7
    CheatVision = 8
    CheatMoney = 9
    CheatInsane = 10

class AIBuild(Enum):
    RandomBuild = 1
    Rush = 2
    Timing = 3
    Power = 4
    Macro = 5
    Air = 6

class Status(Enum):
    launched = 1
    init_game = 2
    in_game = 3
    in_replay = 4
    ended = 5
    quit = 6
    unknown = 7

class Result(Enum):
    Victory = 1
    Defeat = 2
    Tie = 3
    Undecided = 4

class Alert(Enum):
    AlertError = 1
    AddOnComplete = 2
    BuildingComplete = 3
    BuildingUnderAttack = 4
    LarvaHatched = 5
    MergeComplete = 6
    MineralsExhausted = 7
    MorphComplete = 8
    MothershipComplete = 9
    MULEExpired = 10
    NuclearLaunchDetected = 11
    NukeComplete = 12
    NydusWormDetected = 13
    ResearchComplete = 14
    TrainError = 15
    TrainUnitComplete = 16
    TrainWorkerComplete = 17
    TransformationComplete = 18
    UnitUnderAttack = 19
    UpgradeComplete = 20
    VespeneExhausted = 21
    WarpInComplete = 22

class ChatChannel(Enum):
    Broadcast = 1
    Team = 2

class Race(Enum):
    """StarCraft II race enum.

    Members:
        NoRace: No race specified
        Terran: Terran race
        Zerg: Zerg race
        Protoss: Protoss race
        Random: Random race selection
    """

    NoRace = 0
    Terran = 1
    Zerg = 2
    Protoss = 3
    Random = 4

# Enums created from raw_pb2
class DisplayType(Enum):
    Visible = 1
    Snapshot = 2
    Hidden = 3
    Placeholder = 4

class Alliance(Enum):
    Self = 1
    Ally = 2
    Neutral = 3
    Enemy = 4

class CloakState(Enum):
    CloakedUnknown = 1
    Cloaked = 2
    CloakedDetected = 3
    NotCloaked = 4
    CloakedAllied = 5

class Attribute(Enum):
    Light = 1
    Armored = 2
    Biological = 3
    Mechanical = 4
    Robotic = 5
    Psionic = 6
    Massive = 7
    Structure = 8
    Hover = 9
    Heroic = 10
    Summoned = 11

class TargetType(Enum):
    Ground = 1
    Air = 2
    Any = 3
    Invalid = 4

class Target(Enum):
    # Note: The protobuf enum member 'None' is a Python keyword,
    # so at runtime it may need special handling
    Point = 1
    Unit = 2
    PointOrUnit = 3
    PointOrNone = 4

class ActionResult(Enum):
    """Action result codes from game engine.

    This enum contains a large number of members (~200+) representing
    various action results and error conditions.
    """

    Success = 1
    NotSupported = 2
    Error = 3
    CantQueueThatOrder = 4
    Retry = 5
    Cooldown = 6
    QueueIsFull = 7
    RallyQueueIsFull = 8
    NotEnoughMinerals = 9
    NotEnoughVespene = 10
    NotEnoughTerrazine = 11
    NotEnoughCustom = 12
    NotEnoughFood = 13
    FoodUsageImpossible = 14
    NotEnoughLife = 15
    NotEnoughShields = 16
    NotEnoughEnergy = 17
    LifeSuppressed = 18
    ShieldsSuppressed = 19
    EnergySuppressed = 20
    NotEnoughCharges = 21
    CantAddMoreCharges = 22
    TooMuchMinerals = 23
    TooMuchVespene = 24
    TooMuchTerrazine = 25
    TooMuchCustom = 26
    TooMuchFood = 27
    TooMuchLife = 28
    TooMuchShields = 29
    TooMuchEnergy = 30
    MustTargetUnitWithLife = 31
    MustTargetUnitWithShields = 32
    MustTargetUnitWithEnergy = 33
    CantTrade = 34
    CantSpend = 35
    CantTargetThatUnit = 36
    CouldntAllocateUnit = 37
    UnitCantMove = 38
    TransportIsHoldingPosition = 39
    BuildTechRequirementsNotMet = 40
    CantFindPlacementLocation = 41
    CantBuildOnThat = 42
    CantBuildTooCloseToDropOff = 43
    CantBuildLocationInvalid = 44
    CantSeeBuildLocation = 45
    CantBuildTooCloseToCreepSource = 46
    CantBuildTooCloseToResources = 47
    CantBuildTooFarFromWater = 48
    CantBuildTooFarFromCreepSource = 49
    CantBuildTooFarFromBuildPowerSource = 50
    CantBuildOnDenseTerrain = 51
    CantTrainTooFarFromTrainPowerSource = 52
    CantLandLocationInvalid = 53
    CantSeeLandLocation = 54
    CantLandTooCloseToCreepSource = 55
    CantLandTooCloseToResources = 56
    CantLandTooFarFromWater = 57
    CantLandTooFarFromCreepSource = 58
    CantLandTooFarFromBuildPowerSource = 59
    CantLandTooFarFromTrainPowerSource = 60
    CantLandOnDenseTerrain = 61
    AddOnTooFarFromBuilding = 62
    MustBuildRefineryFirst = 63
    BuildingIsUnderConstruction = 64
    CantFindDropOff = 65
    CantLoadOtherPlayersUnits = 66
    NotEnoughRoomToLoadUnit = 67
    CantUnloadUnitsThere = 68
    CantWarpInUnitsThere = 69
    CantLoadImmobileUnits = 70
    CantRechargeImmobileUnits = 71
    CantRechargeUnderConstructionUnits = 72
    CantLoadThatUnit = 73
    NoCargoToUnload = 74
    LoadAllNoTargetsFound = 75
    NotWhileOccupied = 76
    CantAttackWithoutAmmo = 77
    CantHoldAnyMoreAmmo = 78
    TechRequirementsNotMet = 79
    MustLockdownUnitFirst = 80
    MustTargetUnit = 81
    MustTargetInventory = 82
    MustTargetVisibleUnit = 83
    MustTargetVisibleLocation = 84
    MustTargetWalkableLocation = 85
    MustTargetPawnableUnit = 86
    YouCantControlThatUnit = 87
    YouCantIssueCommandsToThatUnit = 88
    MustTargetResources = 89
    RequiresHealTarget = 90
    RequiresRepairTarget = 91
    NoItemsToDrop = 92
    CantHoldAnyMoreItems = 93
    CantHoldThat = 94
    TargetHasNoInventory = 95
    CantDropThisItem = 96
    CantMoveThisItem = 97
    CantPawnThisUnit = 98
    MustTargetCaster = 99
    CantTargetCaster = 100
    MustTargetOuter = 101
    CantTargetOuter = 102
    MustTargetYourOwnUnits = 103
    CantTargetYourOwnUnits = 104
    MustTargetFriendlyUnits = 105
    CantTargetFriendlyUnits = 106
    MustTargetNeutralUnits = 107
    CantTargetNeutralUnits = 108
    MustTargetEnemyUnits = 109
    CantTargetEnemyUnits = 110
    MustTargetAirUnits = 111
    CantTargetAirUnits = 112
    MustTargetGroundUnits = 113
    CantTargetGroundUnits = 114
    MustTargetStructures = 115
    CantTargetStructures = 116
    MustTargetLightUnits = 117
    CantTargetLightUnits = 118
    MustTargetArmoredUnits = 119
    CantTargetArmoredUnits = 120
    MustTargetBiologicalUnits = 121
    CantTargetBiologicalUnits = 122
    MustTargetHeroicUnits = 123
    CantTargetHeroicUnits = 124
    MustTargetRoboticUnits = 125
    CantTargetRoboticUnits = 126
    MustTargetMechanicalUnits = 127
    CantTargetMechanicalUnits = 128
    MustTargetPsionicUnits = 129
    CantTargetPsionicUnits = 130
    MustTargetMassiveUnits = 131
    CantTargetMassiveUnits = 132
    MustTargetMissile = 133
    CantTargetMissile = 134
    MustTargetWorkerUnits = 135
    CantTargetWorkerUnits = 136
    MustTargetEnergyCapableUnits = 137
    CantTargetEnergyCapableUnits = 138
    MustTargetShieldCapableUnits = 139
    CantTargetShieldCapableUnits = 140
    MustTargetFlyers = 141
    CantTargetFlyers = 142
    MustTargetBuriedUnits = 143
    CantTargetBuriedUnits = 144
    MustTargetCloakedUnits = 145
    CantTargetCloakedUnits = 146
    MustTargetUnitsInAStasisField = 147
    CantTargetUnitsInAStasisField = 148
    MustTargetUnderConstructionUnits = 149
    CantTargetUnderConstructionUnits = 150
    MustTargetDeadUnits = 151
    CantTargetDeadUnits = 152
    MustTargetRevivableUnits = 153
    CantTargetRevivableUnits = 154
    MustTargetHiddenUnits = 155
    CantTargetHiddenUnits = 156
    CantRechargeOtherPlayersUnits = 157
    MustTargetHallucinations = 158
    CantTargetHallucinations = 159
    MustTargetInvulnerableUnits = 160
    CantTargetInvulnerableUnits = 161
    MustTargetDetectedUnits = 162
    CantTargetDetectedUnits = 163
    CantTargetUnitWithEnergy = 164
    CantTargetUnitWithShields = 165
    MustTargetUncommandableUnits = 166
    CantTargetUncommandableUnits = 167
    MustTargetPreventDefeatUnits = 168
    CantTargetPreventDefeatUnits = 169
    MustTargetPreventRevealUnits = 170
    CantTargetPreventRevealUnits = 171
    MustTargetPassiveUnits = 172
    CantTargetPassiveUnits = 173
    MustTargetStunnedUnits = 174
    CantTargetStunnedUnits = 175
    MustTargetSummonedUnits = 176
    CantTargetSummonedUnits = 177
    MustTargetUser1 = 178
    CantTargetUser1 = 179
    MustTargetUnstoppableUnits = 180
    CantTargetUnstoppableUnits = 181
    MustTargetResistantUnits = 182
    CantTargetResistantUnits = 183
    MustTargetDazedUnits = 184
    CantTargetDazedUnits = 185
    CantLockdown = 186
    CantMindControl = 187
    MustTargetDestructibles = 188
    CantTargetDestructibles = 189
    MustTargetItems = 190
    CantTargetItems = 191
    NoCalldownAvailable = 192
    WaypointListFull = 193
    MustTargetRace = 194
    CantTargetRace = 195
    MustTargetSimilarUnits = 196
    CantTargetSimilarUnits = 197
    CantFindEnoughTargets = 198
    AlreadySpawningLarva = 199
    CantTargetExhaustedResources = 200
    CantUseMinimap = 201
    CantUseInfoPanel = 202
    OrderQueueIsFull = 203
    CantHarvestThatResource = 204
    HarvestersNotRequired = 205
    AlreadyTargeted = 206
    CantAttackWeaponsDisabled = 207
    CouldntReachTarget = 208
    TargetIsOutOfRange = 209
    TargetIsTooClose = 210
    TargetIsOutOfArc = 211
    CantFindTeleportLocation = 212
    InvalidItemClass = 213
    CantFindCancelOrder = 214

# Module-level dictionaries
race_worker: dict[Race, UnitTypeId]
race_townhalls: dict[Race, set[UnitTypeId]]
warpgate_abilities: dict[AbilityId, AbilityId]
race_gas: dict[Race, UnitTypeId]
