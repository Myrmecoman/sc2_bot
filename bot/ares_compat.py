"""The bridge between the python-sc2 vendored in `sc2/` and the Ares library in `ares/`.

Ares is not written against mainline python-sc2 (BurnySc2, which is what `sc2/` holds) but against its author's fork
(august-k/python-sc2, branch `develop` - the python-sc2 dependency in Ares' own pyproject.toml). The fork has five things
mainline python-sc2 does not have, and without each of them Ares or the bot breaks:

  1. `_prepare_step` is `async` and awaited by the fork's main loop; Ares overrides it as `async def`. Mainline calls it
     synchronously and never awaits it, so Ares' version would only create a coroutine that is thrown away: no unit list is
     ever built and the bot sees an empty game (and resigns).                              -> Sc2Bridge._prepare_step
  2. `self._used_tumors`, read by Ares' `_prepare_units` every frame, is defined by the fork's `_initialize_variables`.
                                                                                           -> Sc2Bridge.__init__
  3. `Unit.abilities` - the abilities the unit can use right now - is read by many Ares behaviors (`ReaperGrenade`,
     `UseAbility`, `GroupUseAbility`, ...); the fork fills it for every unit every step. Here it is a property backed by a
     cache that the army refreshes with ONE batched `get_available_abilities` query, only for the unit types that need it
     (ABILITY_UNIT_TYPES); a unit that is not in the cache reports no abilities, so the behavior declines instead of crashing.
                                                                             -> install_unit_abilities, refresh_ability_cache
  4. `UnitTypeData.attributes` holds the protocol's raw integers in the fork; mainline wraps them into `Attribute` enum
     members, which Ares' Rust combat simulator cannot convert - it PANICS, and the panic kills the whole process.
                                                                                       -> install_raw_type_attributes
  5. `Point2.__bool__` always hands back a real `bool`. Mainline returns `self[0] != 0 or self[1] != 0`, which is a numpy
     bool when the coordinates are numpy numbers - and Ares' paths are made of exactly those (int32 grid cells) - so every
     `if point:` in Ares (e.g. `PlacePredictiveAoE`, reached through `ReaperGrenade`) dies with "__bool__ should return
     bool, returned numpy.bool".                                                            -> install_point_bool

All of this goes away the day `sc2/` is replaced by that fork: delete this module, drop `Sc2Bridge` from the bases of
SmoothBrainBot (bot/bot.py) and remove the `refresh_ability_cache` call in bot/army/manager.py.
"""
from typing import Dict, FrozenSet, Iterable, Set

from loguru import logger

from sc2.bot_ai import BotAI
from sc2.data import Attribute
from sc2.game_data import UnitTypeData
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

# units whose usable abilities the army code (or an Ares behavior it runs) reads. Deliberately small:
# marines/marauders/tanks/... never need this (stim is checked via its buff, siege via the unit type)
ABILITY_UNIT_TYPES: FrozenSet[UnitTypeId] = frozenset({
    UnitTypeId.MEDIVAC,
    UnitTypeId.RAVEN,
    UnitTypeId.BANSHEE,
    UnitTypeId.REAPER,
    UnitTypeId.CYCLONE,
    UnitTypeId.GHOST,
    UnitTypeId.WIDOWMINE,
    UnitTypeId.WIDOWMINEBURROWED,
    UnitTypeId.BATTLECRUISER,
    UnitTypeId.LIBERATOR,
    UnitTypeId.LIBERATORAG,
    UnitTypeId.HELLION,
    UnitTypeId.HELLIONTANK,
})

_NO_ABILITIES: FrozenSet[AbilityId] = frozenset()
_INSTALLED_FLAG = "_ares_compat_abilities_installed"


def _abilities_of(self: Unit) -> FrozenSet[AbilityId]:
    cache = getattr(self._bot_object, "ability_cache", None)
    if not cache:
        return _NO_ABILITIES
    return cache.get(self.tag, _NO_ABILITIES)


def install_unit_abilities() -> bool:
    """Idempotently add `Unit.abilities` if this python-sc2 doesn't already provide it. Returns True when the
    shim is active (either we installed it just now, or an earlier call did)."""
    if getattr(Unit, _INSTALLED_FLAG, False):
        return True
    if hasattr(Unit, "abilities"):
        # a python-sc2 that already ships its own - leave it alone
        return False
    Unit.abilities = property(_abilities_of)  # type: ignore[attr-defined]
    setattr(Unit, _INSTALLED_FLAG, True)
    return True


_RAW_ATTRIBUTES_FLAG = "_ares_compat_raw_attributes_installed"


def _raw_attributes(self: UnitTypeData):
    return self._proto.attributes


def _has_attribute(self: UnitTypeData, attr: Attribute) -> bool:
    assert isinstance(attr, Attribute)
    return attr.value in self._proto.attributes


def install_raw_type_attributes() -> bool:
    """Make `UnitTypeData.attributes` return the protocol's raw integers (point 4 above).

    Ares' combat simulator (`sc2_helper`, a Rust extension behind `mediator.can_win_fight`) reads
    `unit._type_data.attributes` and converts every entry to an integer. Nothing else reads the property (the `Unit.is_*`
    checks use `_proto.attributes` directly), so `has_attribute` is rewritten to work on the raw values too."""
    if getattr(UnitTypeData, _RAW_ATTRIBUTES_FLAG, False):
        return True
    UnitTypeData.attributes = property(_raw_attributes)  # type: ignore[assignment]
    UnitTypeData.has_attribute = _has_attribute  # type: ignore[assignment]
    setattr(UnitTypeData, _RAW_ATTRIBUTES_FLAG, True)
    return True


_POINT_BOOL_FLAG = "_ares_compat_point_bool_installed"


def _point_bool(self) -> bool:
    # an `if` evaluates a numpy bool fine; returning `a != 0 or b != 0` as it is would hand the numpy bool to Python
    if self[0] != 0 or self[1] != 0:
        return True
    return False


def install_point_bool() -> bool:
    """`Point2.__bool__` that always returns a real bool, like the fork's (point 5 above). Idempotent."""
    if getattr(Point2, _POINT_BOOL_FLAG, False):
        return True
    Point2.__bool__ = _point_bool  # type: ignore[assignment]
    setattr(Point2, _POINT_BOOL_FLAG, True)
    return True


def install_compat() -> None:
    """The class-level patches (points 3, 4 and 5). Idempotent."""
    install_unit_abilities()
    install_raw_type_attributes()
    install_point_bool()


class Sc2Bridge:
    """Mixin for the bot class, FIRST in its bases (`class SmoothBrainBot(Sc2Bridge, AresBot)`): points 1-5 above."""

    def __init__(self, *args, **kwargs):
        self._used_tumors: Set[int] = set()                            # point 2
        self.ability_cache: Dict[int, FrozenSet[AbilityId]] = {}       # point 3: unit tag -> abilities usable right now
        install_compat()                                               # points 3, 4 and 5
        super().__init__(*args, **kwargs)

    def _prepare_step(self, state, proto_game_info):
        """Point 1. Run Ares' own `_prepare_step` logic synchronously: its realtime frame skipping, then mainline's sync
        `BotAI._prepare_step`, which builds the unit lists through Ares' `_prepare_units` override."""
        self.state = state
        loop = state.game_loop
        if self.realtime and self.last_game_loop + 4 > loop and loop != 0:
            return None
        self.last_game_loop = loop
        return BotAI._prepare_step(self, state, proto_game_info)


async def refresh_ability_cache(ai, units: Iterable[Unit]) -> None:
    """One batched API query for every unit in `units` whose type is in ABILITY_UNIT_TYPES; replaces
    `ai.ability_cache` wholesale so stale entries (dead units) can never linger. Never raises: a failed query
    just leaves the cache empty for this step, which makes ability behaviors decline rather than misfire."""
    wanted = [u for u in units if u.type_id in ABILITY_UNIT_TYPES]
    cache: Dict[int, Set[AbilityId]] = {}
    if wanted:
        try:
            results = await ai.get_available_abilities(wanted)
            for unit, abilities in zip(wanted, results):
                cache[unit.tag] = frozenset(abilities)
        except Exception as e:  # noqa: BLE001 - a hiccup here must never take the whole step down
            logger.warning(f"[ares_compat] ability query failed ({e!r}); ability behaviors idle this step")
            cache = {}
    ai.ability_cache = cache
