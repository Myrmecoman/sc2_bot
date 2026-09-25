"""Which parts of bot/ares_compat.py does the python-sc2 in ./sc2 already make redundant?

Ares is written against august-k's python-sc2 fork; mainline python-sc2 lacks five things Ares needs, and `bot/ares_compat.py`
supplies them (see its docstring). Run this after replacing `sc2/`: every line that says "provided by sc2" is a piece of the
bridge that can be deleted; when all five do, delete `bot/ares_compat.py` altogether (and `Sc2Bridge` from the bot's bases and
the `refresh_ability_cache` call in bot/army/manager.py).

    python tests/offline/bridge_status.py

Read-only: it inspects `sc2` and never installs the bridge. Exit code 0 always; the output is the answer."""
import _bootstrap  # noqa: F401  (repo root on sys.path - keep this first)
import inspect

import numpy as np
from s2clientprotocol import data_pb2

from sc2.bot_ai import BotAI
from sc2.game_data import UnitTypeData
from sc2.position import Point2
from sc2.unit import Unit


class _Probe(BotAI):
    async def on_step(self, iteration: int):
        pass


def prepare_step_is_async() -> bool:
    return inspect.iscoroutinefunction(BotAI._prepare_step)


def defines_used_tumors() -> bool:
    probe = _Probe()
    probe._initialize_variables()
    return hasattr(probe, "_used_tumors")


def unit_has_abilities() -> bool:
    return hasattr(Unit, "abilities")


def attributes_are_raw_integers() -> bool:
    proto = data_pb2.UnitTypeData()
    proto.attributes.extend([1, 3])
    return all(type(a) is int for a in UnitTypeData(None, proto).attributes)


def point_bool_is_a_real_bool() -> bool:
    try:
        bool(Point2((np.int32(48), np.int32(72))))
    except TypeError:
        return False
    return True


CHECKS = [
    ("1  `_prepare_step` is async (and the main loop awaits it)", prepare_step_is_async, "Sc2Bridge._prepare_step"),
    ("2  `_used_tumors` is defined", defines_used_tumors, "Sc2Bridge.__init__ (_used_tumors)"),
    ("3  `Unit.abilities` exists", unit_has_abilities, "install_unit_abilities + refresh_ability_cache"),
    ("4  `UnitTypeData.attributes` holds raw integers", attributes_are_raw_integers, "install_raw_type_attributes"),
    ("5  `Point2.__bool__` works for numpy coordinates", point_bool_is_a_real_bool, "install_point_bool"),
]


def main() -> int:
    redundant = 0
    for label, check, bridge_piece in CHECKS:
        provided = bool(check())
        redundant += provided
        print(f"{'provided by sc2 - can go ' if provided else 'MISSING in sc2 - still needed'}  {label}   [{bridge_piece}]")
    print()
    if redundant == len(CHECKS):
        print("The vendored python-sc2 provides everything Ares needs: bot/ares_compat.py can be deleted.")
    else:
        print(f"{redundant}/{len(CHECKS)} pieces are redundant. The rest are still needed: deleting them breaks the bot "
              "(a crash on the first frame, a Rust panic that kills the process, or Ares' behaviors failing in the middle of a game).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
