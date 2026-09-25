"""The army marches on a target that is straight ahead of it but behind a cliff mass 38 wide; the way round is through a gap far
to the north. Units move like the engine moves them (physics.TerrainPhysics): a unit sent to a spot inside the cliff goes to the
closest spot it can reach and stops there.

The march used to send every unit in a clump to a point a few cells ahead of it IN A STRAIGHT LINE towards the target - inside
the cliff - so the whole army stood against the cliff for good. Two things now stop that: a unit only takes that hop when the
line to it is standable (otherwise it is sent to the far target and the engine finds the way round), and an army that stops
getting anywhere gives its target up (progress.ProgressWatch). Each is checked without the other."""
import _bootstrap  # noqa: F401  (repo root on sys.path - keep this first)
import asyncio, sys
from loguru import logger
logger.remove()
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.ids.upgrade_id import UpgradeId
import dynamic
from dynamic import BASES, run_frame, start_game
from physics import TerrainPhysics
from test_dynamic import build_game
import gamefix_more  # noqa: F401
from bot.bot import SmoothBrainBot

_original_make_map = dynamic.make_map


def _cliff_map():
    pathing, placement, height = _original_make_map()
    pathing[20:60, 62:100] = 0
    placement[20:60, 62:100] = 0
    return pathing, placement, height


def march(frames=800):
    """returns (was the hatchery behind the cliff destroyed, did the army ever get to the enemy main, ERROR logs, the bot)"""
    errors = []
    logger.add(lambda m: errors.append(str(m)) if m.record["level"].no >= 40 else None)
    dynamic.make_map = _cliff_map
    try:
        game = build_game()
    finally:
        dynamic.make_map = _original_make_map
    bot = SmoothBrainBot()
    loop = asyncio.new_event_loop()
    client, proto_gi = loop.run_until_complete(start_game(game, bot))
    physics = TerrainPhysics(game, bot)
    for k in range(30):
        physics.add(U.MARINE, (50 + (k % 6) * 0.7, 35 + (k // 6) * 0.7), 1)
    for k in range(3):
        physics.add(U.SIEGETANK, (47.5 - k * 2.5, 36), 1)
    hatchery = physics.add(U.HATCHERY, (110.5, 35.5), 4)
    physics.adopt_existing()
    physics._regenerate()
    reached_main = False
    for i in range(frames):
        before = len(client.sent_actions)
        loop.run_until_complete(run_frame(game, bot, proto_gi, i, supply_used=198, supply_cap=200, upgrades=[UpgradeId.STIMPACK]))
        physics.apply(client.sent_actions[before:])
        physics.step(2)
        marines = [u for u in physics.units.values() if u.alliance == 1 and u.type_id == U.MARINE]
        if marines:
            mx, my = sum(m.x for m in marines) / len(marines), sum(m.y for m in marines) / len(marines)
            enemy_main = BASES["enemy_main"]
            reached_main = reached_main or ((mx - enemy_main[0]) ** 2 + (my - enemy_main[1]) ** 2) ** 0.5 < 12
    return hatchery.tag not in physics.units, reached_main, errors, bot


RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail and not cond else ""))


def main():
    destroyed, _, errors, bot = march()
    check("army walks round the cliff (through the gap) and destroys the hatchery behind it", destroyed)
    check("...without errors", not errors and not bot.army._errors, str(errors[:1]) + str(bot.army._errors))

    # the wall check switched off: the army does press itself against the cliff - and the stuck watch must free it
    import bot.pathing.order_utils as order_utils
    real_check = order_utils.segment_walkable
    order_utils.segment_walkable = lambda *a, **k: True
    try:
        destroyed, reached_main, errors, bot = march()
    finally:
        order_utils.segment_walkable = real_check
    check("without the wall check the stuck watch gives the target up and the army marches on to the enemy main", reached_main and not destroyed)
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
