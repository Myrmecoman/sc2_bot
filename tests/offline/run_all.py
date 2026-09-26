"""Run every offline check, each in a fresh interpreter (a Rust panic in the combat simulator kills the whole process,
so the checks must not share one), and print a summary. Exit code 0 = everything passed.

    python tests/offline/run_all.py            # everything (a few minutes)
    python tests/offline/run_all.py --quick    # skip the long physics scenarios and the unit-type simulation matrix

Needs the environment described in the README (Python 3.12 with the requirements installed, and the compiled
extensions for this platform). Nothing here starts StarCraft II."""
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

# (label, script, extra environment, part of --quick?)
CHECKS = [
    ("api cross-check (Ares calls)", "api_check.py", {}, True),
    ("ladder zip: Linux builds, glibc, cython_extensions path", "ladder_check.py", {}, True),
    ("fights: who is in one, simulator settings, decisions", "test_fights.py", {}, True),
    ("army scenarios, stand-in Ares managers", "test_scenarios.py", {"REAL": "0"}, True),
    ("army scenarios, real Ares managers", "test_scenarios.py", {"REAL": "1"}, True),
    ("unit controllers, stand-in Ares managers", "test_controllers.py", {"REAL": "0"}, True),
    ("unit controllers, real Ares managers", "test_controllers.py", {"REAL": "1"}, True),
    ("whole bot on the real Ares hub, 120 frames", "test_dynamic.py", {"FRAMES": "120"}, True),
    ("whole bot, scripted events + step timing", "test_dynamic2.py", {}, True),
    ("whole bot, reaper grenade on real Ares paths", "test_reaper_grenade.py", {}, True),
    ("whole bot, SCV repairs: at most 4 per target, at most 70 walked, only near home", "test_repair_leash.py", {}, True),
    ("whole bot, workers dodge an Oracle instead of huddling under it", "test_worker_oracle.py", {}, True),
    ("scouting reactions: the rules, and the advisor's use of them", "test_reactions.py", {}, True),
    ("whole bot, reactions in production/macro + the 6/2/2 production limits", "test_production_reactions.py", {}, True),
    ("no numpy-typed points leak into orders", "np_contagion.py", {}, True),
    ("random armies vs random enemies, all races (fuzz)", "fuzz_army.py", {}, True),
    ("combat simulator, unusual unit states", "sim_variants.py", {}, True),
    ("combat simulator, every unit-type pair", "sim_matrix.py", {}, False),
    ("physics: defend a small attack", "test_physics.py", {"SCENARIO": "defend", "FRAMES": "400"}, False),
    ("physics: kite a ranged group", "test_physics.py", {"SCENARIO": "kite", "FRAMES": "400"}, False),
    ("physics: banelings are always kited away from", "test_physics.py", {"SCENARIO": "baneling", "FRAMES": "400"}, False),
    ("march round a cliff / stuck army gets going again", "test_terrain_march.py", {}, False),
    ("physics: overwhelming attack at home", "test_physics.py", {"SCENARIO": "big_defend", "FRAMES": "400"}, False),
    ("physics: air raid at home", "test_physics.py", {"SCENARIO": "air_defend", "FRAMES": "400"}, False),
    ("physics: full-supply attack with tank staging", "test_physics.py", {"SCENARIO": "attack", "FRAMES": "900"}, False),
    ("physics: every army unit type at once, defend then attack", "test_physics.py", {"SCENARIO": "zoo", "FRAMES": "800"}, False),
    ("physics: an army strung out on the march meets a waiting enemy", "test_physics.py", {"SCENARIO": "vanguard", "FRAMES": "500"}, False),
]


def main() -> int:
    quick = "--quick" in sys.argv
    results = []
    for label, script, extra_env, in_quick in CHECKS:
        if quick and not in_quick:
            continue
        start = time.perf_counter()
        env = dict(os.environ, PYTHONUNBUFFERED="1", **extra_env)
        proc = subprocess.run([sys.executable, str(HERE / script)], cwd=str(HERE.parents[1]), env=env,
                              capture_output=True, text=True, errors="replace")
        seconds = time.perf_counter() - start
        ok = proc.returncode == 0
        results.append((label, ok))
        print(f"{'PASS' if ok else 'FAIL'}  {label}  ({seconds:.0f}s)", flush=True)
        if not ok:
            tail = (proc.stdout + "\n" + proc.stderr).strip().splitlines()[-25:]
            print("      exit code", proc.returncode, "- last output:")
            print("\n".join("      " + line for line in tail), flush=True)
    failed = [label for label, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
