"""The crash a real game hit, end to end: a Reaper facing an enemy Queen, the whole bot on the real Ares hub.

ReaperGrenade asks Ares for a path (a list of Points whose coordinates are numpy int32 grid cells) and hands it to
PlacePredictiveAoE, which truth-tests the points on it (`if next_target:`). With mainline python-sc2's Point2.__bool__ - which
returns the numpy bool of `x != 0 or y != 0` as it is - that raised "__bool__ should return bool, returned numpy.bool" on every step
the Reaper was in grenade range, and the army manager logged "[army] reapers failed" each time.

Two layouts, one per way Ares' ReaperGrenade throws: a lone Queen straight ahead of a Reaper that faces it (the predictive throw,
PlacePredictiveAoE, over a real path) and a clump of Marines behind a Reaper that faces away (UseAOEAbility, which looks for the best
spot among them). The Reaper gets its grenade from the stand-in game API (dynamic.GRANTED_ABILITIES), like the real one lists it when it
is off cooldown. Units are built facing east (facing 0), which the first layout relies on.

`python test_reaper_grenade.py --without-fix` runs the same game with the Point2 patch of bot/ares_compat.py switched off and prints
the crash that came with it (a manual proof that this scenario would have caught it)."""
import _bootstrap  # noqa: F401  (repo root on sys.path - keep this first)
import asyncio, math, sys
from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U
from ares.consts import UnitRole

from dynamic import BASES, run_frame, start_game
from test_dynamic import build_game
import gamefix_more  # noqa: F401
from bot.bot import SmoothBrainBot

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail and not cond else ""))


def run(layout="chase", frames=60, without_point_fix=False):
    """returns (grenades thrown, ERROR-level logs, the bot, is the reaper handled by the reaper controller)"""
    if without_point_fix:
        import bot.ares_compat as compat
        compat.install_point_bool = lambda: False          # = the bot as it was before the fix (needs a fresh interpreter)
    errors = []
    logger.remove()
    logger.add(lambda m: errors.append(str(m)) if m.record["level"].no >= 40 else None, colorize=False)
    game = build_game()
    bot = SmoothBrainBot()
    loop = asyncio.new_event_loop()
    client, proto_gi = loop.run_until_complete(start_game(game, bot))
    cx, cy = BASES["our_main"]
    reaper = game.add(U.REAPER, (cx + 12, cy + 12), 1)
    if layout == "chase":
        game.add(U.QUEEN, (cx + 17.5, cy + 12), 4)           # 5.5 cells east of the reaper, which faces east
    else:
        reaper.facing = math.pi                              # looking the other way: no predictive throw
        for k in range(3):
            game.add(U.MARINE, (cx + 16 + k * 0.6, cy + 12 + (k % 2) * 0.6), 4)
    grenades = 0
    for i in range(frames):
        before = len(client.sent_actions)
        loop.run_until_complete(run_frame(game, bot, proto_gi, i))
        grenades += sum(1 for a in client.sent_actions[before:] if a.ability == AbilityId.KD8CHARGE_KD8CHARGE)
    role = bot.mediator.get_unit_role_dict[UnitRole.HARASSING_REAPER.name]
    return grenades, errors, bot, reaper.tag in role


def main():
    for layout, what in (("chase", "predictive throw at a queen ahead"), ("clump", "area throw at a clump of marines")):
        grenades, errors, bot, is_harasser = run(layout)
        check(f"{layout}: the reaper is handled by the reaper controller", is_harasser)
        check(f"{layout}: {what} runs on real Ares paths without errors", not errors and not bot.army._errors,
              str(errors[:1]) + str(bot.army._errors))
        check(f"{layout}: ...and the reaper actually throws a grenade", grenades > 0, f"{grenades} grenades")
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    if "--without-fix" in sys.argv:            # the same run with the Point2 patch switched off: it must show the crash
        grenades, errors, bot, _ = run(without_point_fix=True)
        print("army errors:", bot.army._errors, "| ERROR logs:", len(errors), "| grenades:", grenades)
        print(errors[0].strip().splitlines()[-1].encode("ascii", "replace").decode() if errors else "no error")
        sys.exit(0)
    sys.exit(main())
