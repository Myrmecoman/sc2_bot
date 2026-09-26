"""What we scouted -> what to change. A table of rules: each names a thing the enemy shows us (a tech structure, an army unit) and the
adjustment it calls for in what we build.

The composition advisor (army_composition_advisor.py) first works out its usual per-race numbers, then `react()` runs every rule whose
trigger has been seen and turns the advisor's knobs (unit caps, the marine/marauder split, ...) and the few switches production and
macro read:

    raven_first      the Starport's first unit is a Raven, not a Banshee (production.py)
    priority_units   units that money is held back for: production stops buying cheaper things (marines) that would keep a Factory or
                     Starport that stands ready from affording them (production.py, `priority_reserve`)
    turrets_per_base missile turrets in every mineral line (macro.py, `build_turrets`)
    starport_now     the Starport is built at once, not once a second base is up (macro.py)

Caps only ever go UP (`raise_to`), so two rules never undo each other - the one exception is the last rule, which puts a ceiling on the
tanks against skytoss; the marine share goes down for armored armies (more Marauders)
and up against air (Marines shoot up) - where both apply, the later rule in the table wins, and air is listed after the ground armies. The
advisor resets its knobs to their usual values before every run, so a rule never sticks after its trigger is gone. A rule that is wrong
costs a few units of the wrong kind - never the whole build - and every rule that fires is logged once ("[react] ...") so a game shows
what the bot made of its scouting.

`Scouted` is plain data (counts of the structures and units seen), so the rules can be tested without a game."""
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Mapping, Optional

from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId as U

from bot.pathing.consts import SKYTOSS_TYPES

# the knobs the advisor keeps, and the values they start each step from (see ArmyCompositionAdvisor.provide_advices)
KNOBS = (
    "marine_marauder_ratio", "max_tanks", "max_cyclones", "max_hellions", "max_ravens", "max_medivacs", "max_vikings",
    "max_liberators", "max_battlecruisers", "max_banshees", "prioritize_vikings", "raven_first", "priority_units",
    "turrets_per_base", "starport_now",
)


@dataclass(frozen=True)
class Scouted:
    """What we know of the enemy: its race and how many of each structure and army unit we have seen (structures the enemy has lost
    are gone from the counts; units are counted until we see them die)."""
    race: Race
    structures: Mapping[U, int]
    units: Mapping[U, int]

    def structure(self, *types: U) -> int:
        return sum(self.structures.get(t, 0) for t in types)

    def unit(self, *types: U) -> int:
        return sum(self.units.get(t, 0) for t in types)


def raise_to(advice, **floors) -> None:
    """Never below these (a cap only ever goes up)."""
    for name, value in floors.items():
        setattr(advice, name, max(getattr(advice, name), value))


def lower_to(advice, **ceilings) -> None:
    """Never above these (the marine share goes down for armored armies; the tanks are capped against skytoss)."""
    for name, value in ceilings.items():
        setattr(advice, name, min(getattr(advice, name), value))


def want_first(advice, unit: U) -> None:
    """Hold money back for `unit` (after whatever earlier rules already claimed)."""
    if unit not in advice.priority_units:
        advice.priority_units.append(unit)


@dataclass(frozen=True)
class Reaction:
    name: str
    race: Optional[Race]                       # the enemy's race (None: any)
    seen: Callable[[Scouted], bool]            # the trigger
    apply: Callable[[object], None]            # the adjustment
    why: str                                   # for the log, and for whoever reads this table


# ---- the rules, most urgent first (an earlier rule claims the money first: `want_first`) ------------------------------------
def _detection(advice) -> None:
    advice.raven_first = True
    advice.starport_now = True
    raise_to(advice, max_ravens=2, turrets_per_base=1)
    want_first(advice, U.RAVEN)


REACTIONS: List[Reaction] = [
    # ---- things we cannot shoot without a detector ----
    Reaction(
        "dark shrine", Race.Protoss, lambda s: s.structure(U.DARKSHRINE) > 0 or s.unit(U.DARKTEMPLAR) > 0, _detection,
        "Dark Templar are invisible: the Starport's first unit is a Raven (not a Banshee), the Starport comes early, a turret in every base",
    ),
    Reaction(
        "lurkers", Race.Zerg, lambda s: s.structure(U.LURKERDENMP, U.LURKERDEN) > 0 or s.unit(U.LURKERMP, U.LURKERMPBURROWED, U.LURKER, U.LURKERBURROWED) > 0,
        lambda a: (_detection(a), raise_to(a, max_tanks=10, max_liberators=2)),
        "Burrowed Lurkers need a detector, and tanks and Liberators outrange them: Raven first, more tanks and Liberators",
    ),
    Reaction(
        "widow mines", Race.Terran, lambda s: s.unit(U.WIDOWMINE, U.WIDOWMINEBURROWED) > 0, _detection,
        "Burrowed mines are invisible until detected: Raven first",
    ),
    Reaction(
        "banshees", Race.Terran, lambda s: s.unit(U.BANSHEE) > 0,
        lambda a: raise_to(a, max_ravens=2, turrets_per_base=1, max_vikings=6),
        "An enemy Banshee may be cloaked: a turret in every base, a second Raven, Vikings",
    ),
    # ---- armored ground armies: tanks, and the money for them ----
    Reaction(
        "roach warren", Race.Zerg, lambda s: s.structure(U.ROACHWARREN) > 0 or s.unit(U.ROACH) >= 3,
        lambda a: (want_first(a, U.SIEGETANK), raise_to(a, max_tanks=10), lower_to(a, marine_marauder_ratio=0.6)),
        "Roaches are armored: Siege Tanks (money is held back for them, not spent on Marines) and more Marauders",
    ),
    Reaction(
        "hydralisk den", Race.Zerg, lambda s: s.structure(U.HYDRALISKDEN) > 0 or s.unit(U.HYDRALISK) >= 3,
        lambda a: (want_first(a, U.SIEGETANK), raise_to(a, max_tanks=8)),
        "Hydralisks die to splash at range: Siege Tanks",
    ),
    Reaction(
        "baneling nest", Race.Zerg, lambda s: s.structure(U.BANELINGNEST) > 0 or s.unit(U.BANELING) >= 3,
        lambda a: (raise_to(a, max_tanks=8), lower_to(a, marine_marauder_ratio=0.5)),
        "Banelings shred Marines (light) but not Marauders (armored): more Marauders, Siege Tanks",
    ),
    Reaction(
        "ultralisks", Race.Zerg, lambda s: s.structure(U.ULTRALISKCAVERN) > 0 or s.unit(U.ULTRALISK) >= 2,
        lambda a: (raise_to(a, max_tanks=10), lower_to(a, marine_marauder_ratio=0.4)),
        "Ultralisks are armored and armored-proof against Marines: Marauders and Siege Tanks",
    ),
    # ---- air ----
    Reaction(
        "spire", Race.Zerg, lambda s: s.structure(U.SPIRE, U.GREATERSPIRE) > 0 or s.unit(U.MUTALISK) >= 3,
        lambda a: raise_to(a, max_liberators=2, max_cyclones=4, max_vikings=6, turrets_per_base=1, marine_marauder_ratio=0.85),
        "Mutalisks: Marines (they shoot up), a turret in every base, Cyclones, Liberators and Vikings",
    ),
    Reaction(
        "mutalisk flock", Race.Zerg, lambda s: s.unit(U.MUTALISK) >= 8, lambda a: raise_to(a, turrets_per_base=2),
        "A big Mutalisk flock: two turrets in every base",
    ),
    Reaction(
        "brood lords", Race.Zerg, lambda s: s.structure(U.GREATERSPIRE) > 0 or s.unit(U.BROODLORD) >= 2,
        lambda a: (raise_to(a, max_vikings=10), setattr(a, "prioritize_vikings", True)),
        "Brood Lords outrange everything on the ground: Vikings first",
    ),
    Reaction(
        "stargate", Race.Protoss, lambda s: s.structure(U.STARGATE) > 0,
        lambda a: raise_to(a, turrets_per_base=1),
        "A Stargate means Oracles: a turret in every mineral line (the skytoss answer itself is in the advisor)",
    ),
    Reaction(
        "colossi", Race.Protoss, lambda s: s.structure(U.ROBOTICSBAY) > 0 or s.unit(U.COLOSSUS) > 0,
        lambda a: raise_to(a, max_vikings=6),
        "Colossi wipe out Marines and only Vikings outrange them",
    ),
    Reaction(
        "many colossi", Race.Protoss, lambda s: s.unit(U.COLOSSUS) >= 3,
        lambda a: (raise_to(a, max_vikings=10), setattr(a, "prioritize_vikings", True)),
        "Three Colossi or more: Vikings before anything else the Starport could make",
    ),
    Reaction(
        "battlecruisers", Race.Terran, lambda s: s.structure(U.FUSIONCORE) > 0 or s.unit(U.BATTLECRUISER) >= 2,
        lambda a: (raise_to(a, max_cyclones=4, max_vikings=10), setattr(a, "prioritize_vikings", True)),
        "Battlecruisers: Vikings first, Cyclones",
    ),
    # ---- last: a ceiling, so that nothing above can raise it again ----
    Reaction(
        "skytoss", Race.Protoss, lambda s: s.structure(U.STARGATE) > 0 or s.unit(*SKYTOSS_TYPES) > 0,
        lambda a: lower_to(a, max_tanks=2),
        "Siege Tanks cannot shoot up: no more than 2 against skytoss (the Factory makes Cyclones instead)",
    ),
]


def react(scouted: Scouted, advice) -> List[str]:
    """Apply every rule whose trigger has been seen to `advice` (an object with the knobs in KNOBS); returns the names of the ones that
    fired."""
    fired: List[str] = []
    for rule in REACTIONS:
        if (rule.race is None or rule.race == scouted.race) and rule.seen(scouted):
            rule.apply(advice)
            fired.append(rule.name)
    return fired
