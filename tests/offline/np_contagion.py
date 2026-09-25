"""Every Point2 that ends up in a GroupOrders (and the positioning helpers feeding it) must hold plain Python floats."""
import _bootstrap  # noqa: F401  (repo root on sys.path - keep this first)
import asyncio
from loguru import logger
from sc2.ids.upgrade_id import UpgradeId
import dynamic
from dynamic import run_frame, start_game
from physics import Physics
from test_dynamic import build_game
import test_physics
import bot.army.orders as orders_mod
logger.remove()
from bot.bot import SmoothBrainBot

seen = {}
original_init = orders_mod.GroupOrders.__init__
def spying_init(self, *a, **k):
    original_init(self, *a, **k)
    for name in ("target", "hold_point", "front", "bio_position", "anchor", "staging"):
        v = getattr(self, name)
        if v is not None:
            kinds = {type(v[0]).__name__, type(v[1]).__name__}
            seen.setdefault((self.label, name), set()).update(kinds)
orders_mod.GroupOrders.__init__ = spying_init

for scenario in ("attack", "defend"):
    seen.clear()
    game = build_game(); bot = SmoothBrainBot(); loop = asyncio.new_event_loop()
    client, proto_gi = loop.run_until_complete(start_game(game, bot))
    physics = Physics(game); test_physics.populate(game, physics, scenario); physics.adopt_existing(); physics._regenerate()
    for i in range(300):
        before = len(client.sent_actions)
        loop.run_until_complete(run_frame(game, bot, proto_gi, i, supply_used=198 if scenario == "attack" else 60, supply_cap=200, upgrades=[UpgradeId.STIMPACK]))
        physics.apply(client.sent_actions[before:]); physics.step(2)
    bad = {k: v for k, v in seen.items() if v != {"float"}}
    print(scenario, "| orders fields checked:", len(seen), "| with non-float coordinates:", bad or "none")
    print("   approach point:", bot.army.positioning._approach, type(bot.army.positioning._approach[0]).__name__)
    assert not bad, bad
