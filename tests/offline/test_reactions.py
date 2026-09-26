"""What we scouted -> what we change (bot/reactions.py and its use in the composition advisor). The rules on plain data first, then the
advisor on a scene: the reactions must not stick when their trigger is gone, and a Random opponent gets its race's numbers once seen."""
import _bootstrap  # noqa: F401  (repo root on sys.path - keep this first)
from types import SimpleNamespace

from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId as U

import gamefix_more  # noqa: F401  (the tech structures)
from fakes import Scene
from bot.army_composition_advisor import ArmyCompositionAdvisor
from bot.reactions import KNOBS, REACTIONS, Scouted, react

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail and not cond else ""))


def fresh(**kw):
    """the advisor's usual numbers"""
    advice = SimpleNamespace(marine_marauder_ratio=0.7, max_tanks=8, max_cyclones=0, max_hellions=6, max_ravens=1, max_medivacs=4,
                             max_vikings=4, max_liberators=0, max_battlecruisers=1, max_banshees=2, prioritize_vikings=False,
                             raven_first=False, priority_units=[], turrets_per_base=0, starport_now=False)
    for k, v in kw.items():
        setattr(advice, k, v)
    return advice


def run(race, structures=(), units=None, **kw):
    """react() on what was scouted; returns (advice, names of the rules that fired)"""
    advice = fresh(**kw)
    seen_units = dict(units or {})
    fired = react(Scouted(race, {t: 1 for t in structures} if not isinstance(structures, dict) else structures, seen_units), advice)
    return advice, fired


def test_the_table():
    check("reactions: every knob a rule may touch is one the advisor resets each step", all(hasattr(fresh(), k) for k in KNOBS))
    check("reactions: rule names are unique", len({r.name for r in REACTIONS}) == len(REACTIONS))
    advice, fired = run(Race.Zerg)
    check("reactions: nothing scouted, nothing changes", not fired and vars(advice) == vars(fresh()), str(fired))
    advice, fired = run(Race.Zerg, structures=[U.DARKSHRINE])
    check("reactions: a rule only fires for its own race", "dark shrine" not in fired, str(fired))


def test_dark_shrine_raven_first():
    advice, fired = run(Race.Protoss, structures=[U.DARKSHRINE])
    check("dark shrine: the Starport makes a Raven first", advice.raven_first and advice.priority_units == [U.RAVEN], str(vars(advice)))
    check("dark shrine: the Starport comes early, a turret in every base, a second Raven",
          advice.starport_now and advice.turrets_per_base == 1 and advice.max_ravens == 2, str(vars(advice)))
    advice, fired = run(Race.Protoss, units={U.DARKTEMPLAR: 1})
    check("dark shrine: a Dark Templar seen is as good as the shrine", advice.raven_first and "dark shrine" in fired, str(fired))
    advice, fired = run(Race.Protoss, structures=[U.GATEWAY])
    check("dark shrine: a plain Gateway calls for nothing", not advice.raven_first and not fired, str(fired))


def test_roach_warren_holds_money_for_tanks():
    advice, fired = run(Race.Zerg, structures=[U.ROACHWARREN], max_tanks=8)
    check("roach warren: money is held back for Siege Tanks, and there may be more of them",
          advice.priority_units == [U.SIEGETANK] and advice.max_tanks == 10, str(vars(advice)))
    check("roach warren: more Marauders (armored) than the usual mix", advice.marine_marauder_ratio == 0.6, str(advice.marine_marauder_ratio))
    advice, _ = run(Race.Zerg, units={U.ROACH: 2})
    check("roach warren: two roaches are a scout, not an army", not advice.priority_units, str(advice.priority_units))
    advice, _ = run(Race.Zerg, units={U.ROACH: 3})
    check("roach warren: three roaches are", advice.priority_units == [U.SIEGETANK])
    advice, _ = run(Race.Zerg, structures=[U.ROACHWARREN], max_tanks=14, marine_marauder_ratio=0.4)
    check("roach warren: caps only go up, the marine share only down (14 tanks stay 14, 0.4 stays 0.4)",
          advice.max_tanks == 14 and advice.marine_marauder_ratio == 0.4, str(vars(advice)))


def test_detection_comes_before_tanks():
    advice, fired = run(Race.Zerg, structures=[U.ROACHWARREN, U.LURKERDENMP])
    check("lurkers + roaches: the Raven is what money is held back for first, then the tank", advice.priority_units == [U.RAVEN, U.SIEGETANK] and advice.raven_first, str(advice.priority_units))
    check("lurkers: more tanks and Liberators (they outrange Lurkers)", advice.max_tanks >= 10 and advice.max_liberators >= 2, str(vars(advice)))
    advice, _ = run(Race.Terran, units={U.WIDOWMINEBURROWED: 1})
    check("widow mines: Raven first", advice.raven_first and advice.priority_units == [U.RAVEN])
    advice, _ = run(Race.Terran, units={U.BANSHEE: 1})
    check("enemy banshee: a turret in every base and a second Raven - but the usual Starport order", advice.turrets_per_base == 1 and advice.max_ravens == 2 and not advice.raven_first, str(vars(advice)))


def test_air_and_the_marine_share():
    advice, fired = run(Race.Zerg, structures=[U.ROACHWARREN, U.SPIRE])
    check("spire + roaches: air wins the marine share (Marines shoot up)", advice.marine_marauder_ratio == 0.85, str(advice.marine_marauder_ratio))
    check("spire: turrets, Cyclones, Liberators, Vikings", advice.turrets_per_base == 1 and advice.max_cyclones == 4 and advice.max_liberators == 2 and advice.max_vikings == 6, str(vars(advice)))
    advice, _ = run(Race.Zerg, structures=[U.SPIRE], units={U.MUTALISK: 8})
    check("mutalisk flock: two turrets in every base", advice.turrets_per_base == 2, str(advice.turrets_per_base))
    advice, _ = run(Race.Zerg, units={U.BROODLORD: 2})
    check("brood lords: Vikings first", advice.prioritize_vikings and advice.max_vikings == 10, str(vars(advice)))
    advice, _ = run(Race.Protoss, structures=[U.STARGATE])
    check("stargate: a turret in every mineral line", advice.turrets_per_base == 1)
    advice, _ = run(Race.Protoss, units={U.COLOSSUS: 1})
    check("colossus: Vikings up to 6, not yet first", advice.max_vikings == 6 and not advice.prioritize_vikings, str(vars(advice)))
    advice, _ = run(Race.Protoss, units={U.COLOSSUS: 3})
    check("three colossi: Vikings first", advice.prioritize_vikings and advice.max_vikings == 10, str(vars(advice)))
    advice, _ = run(Race.Zerg, structures=[U.BANELINGNEST])
    check("baneling nest: more Marauders and tanks", advice.marine_marauder_ratio == 0.5 and advice.max_tanks == 8)
    advice, _ = run(Race.Terran, structures=[U.FUSIONCORE])
    check("fusion core: Vikings first, Cyclones", advice.prioritize_vikings and advice.max_cyclones == 4 and advice.max_vikings == 10, str(vars(advice)))


# ---------------------------------------------------------------------------------------------------------------- the advisor
def make_advisor(race):
    sc = Scene(enemy_race=race)
    advisor = ArmyCompositionAdvisor(sc.ai)
    advisor.provide_advices_startup()
    return sc, advisor


def test_advisor_reacts_and_lets_go():
    sc, advisor = make_advisor(Race.Protoss)
    advisor.provide_advices()
    check("advisor: nothing scouted, the usual Protoss numbers", not advisor.raven_first and advisor.turrets_per_base == 0 and advisor.max_tanks == 6, str(advisor.active_reactions))
    shrine = sc.enemy(U.DARKSHRINE, (150, 150))
    advisor.provide_advices()
    check("advisor: a Dark Shrine scouted -> Raven first, turrets, Starport now",
          advisor.raven_first and advisor.turrets_per_base == 1 and advisor.starport_now and advisor.priority_units == [U.RAVEN], str(advisor.active_reactions))
    check("advisor: ...and it is logged once", advisor.reactions_fired == {"dark shrine"}, str(advisor.reactions_fired))
    sc.ai._enemies.remove(shrine)                                          # the shrine is gone (we killed it)
    advisor.provide_advices()
    check("advisor: the shrine gone, the reaction goes with it (nothing sticks)",
          not advisor.raven_first and advisor.turrets_per_base == 0 and not advisor.starport_now and advisor.priority_units == [], str(advisor.active_reactions))


def test_advisor_random_opponent_gets_its_races_numbers_once_seen():
    sc, advisor = make_advisor(Race.Random)
    advisor.provide_advices()
    check("advisor: an unknown race keeps the defaults", advisor.max_medivacs == 4, str(advisor.max_medivacs))
    sc.ai.enemy_race = Race.Zerg                                            # a Zergling was seen
    advisor.provide_advices()
    check("advisor: seen to be Zerg, it starts over with the Zerg numbers (6 medivacs, 8 tanks, ...)", advisor.max_medivacs == 6 and advisor.max_tanks == 8, str((advisor.max_medivacs, advisor.max_tanks)))
    sc.enemy(U.ROACHWARREN, (150, 150))
    advisor.provide_advices()
    check("advisor: ...and reacts to what it sees of them", advisor.priority_units == [U.SIEGETANK] and advisor.max_tanks == 10, str(vars(advisor)))


def main():
    import sys
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    for t in tests:
        print(f"--- {t.__name__}")
        t()
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
