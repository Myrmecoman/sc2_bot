# sc2_bot - SmoothBrain bot

Simple sc2 bot using burnysc2 api.
Its name is SmoothBrain on the ai arena ladders.
This bot is able to almost always beat the CheaterInsane AIs against every race.

If you are a novice bot writter I suggest you pick some ideas from this bot and copy a few blocks of code. However I do not recommend to straight up copy it and modify it because you need to understand how everything works else you will break everything. :)

## How it is put together

A Terran macro bot. The macro side (build order, expansions, production, upgrades, mining, repair, worker defense) is plain
python-sc2 code. **Everything the army does runs on [Ares](https://github.com/AresSC2/ares-sc2)**: unit roles and squads,
influence grids, pathing, KD-tree unit queries, the Rust combat simulator and the micro behaviors.

```
bot/
  bot.py                     SmoothBrainBot(AresBot). One step = Ares managers -> macro -> workers -> army
  build_order.py macro.py production.py speedmining.py custom_utils.py scouting.py repair.py
  worker_rush_defense.py worker_micro.py army_composition_advisor.py reactions.py     the macro side (not Ares based)
  army/                      the Ares based army, see below
  ares_compat.py             the bridge between the vendored python-sc2 and Ares, see "python-sc2 and Ares" below
  pathing/                   order helpers used everywhere; grid_pathing/pathing_fallback/influence_costs are the in-house
                             pathing from before Ares, kept but unused
ares/                        Ares (ares-sc2 3.13.1), vendored
sc2/                         python-sc2 (mainline BurnySc2), vendored
map_analyzer/  sc2_helper/   compiled helpers Ares needs: map analysis (C) and the combat simulator (Rust)
vendor_linux/                the Linux build of cython-extensions-sc2 for the ladder, which has no pip package for it (see Setup)
arena-submission.py          zips the bot for the AI Arena ladder (see Setup)
training_bots/               bots to test against
tests/offline/               checks that need no StarCraft II, see the end of this file
```

### The macro side: repairs, reactions to the scouting, production limits

* **Repairs** (`repair.py`) keep three rules: never more than 4 SCVs on one unit or building; never a walk longer than 70 to come and
  repair something (the ground path, measured with Ares' pathing - not the straight line - and an SCV that has walked 70 on one job goes
  back to mining); only near home (what is repaired stands within 25 of a landed townhall, and only SCVs within 35 of one are sent). Only
  SCVs that are mining or idle are sent, never the scout or the scripted build order's builder.
* **Reactions to the scouting** (`reactions.py`): a table of rules, "we have seen X -> change Y", applied on top of the advisor's usual
  per-race numbers every step (so nothing sticks once its trigger is gone) and logged once each as `[react] ...`. A Dark Shrine (or Dark
  Templar): the Starport makes a Raven before a Banshee, is built at once, a missile turret goes into every mineral line. A Roach Warren:
  Siege Tanks, and **money is held back for the tank** - cheap units bought all the time (Marines, 50 minerals, from several Barracks) never
  let the bank reach 150, so while a Factory stands ready and only the money is missing, production spends only what is left over
  (`priority_reserve` in `production.py`; nothing is held back when the gas or the supply is missing, or enough tanks are out). More rules
  for Lurkers, mines, Banshees, Mutalisks, Brood Lords, Colossi, Banelings, Ultralisks, Hydralisks, Battlecruisers - and against skytoss (a
  Stargate or an air unit seen) no more than 2 Siege Tanks, since they cannot shoot up (the Factory makes Cyclones instead). Add a rule by
  adding a `Reaction(...)` to the table; `tests/offline/test_reactions.py` shows how a rule is tested.
* **Production buildings**: what the number of bases calls for, never more than 6 Barracks, 2 Factories and 2 Starports, and while the bank
  keeps piling up late in the game (1000+ minerals, 100+ supply used; the gas buildings also need 350+ gas) one more at a time up to
  those limits (`production_targets` in `macro.py`).

### The army (`bot/army/`)

`manager.py` runs once per step, after Ares' managers, and gives every combat unit one of these roles:

| role | what it is |
| --- | --- |
| `ATTACKING` | the main army: **hold** (pre-positioned at the rally point, tanks dug in on a slot line facing the enemy's approach path), **attack**, or **defend** |
| `BASE_DEFENDER` | a detachment split off to answer one enemy group near a base; sized with the combat simulator as the smallest group that wins (`defense.py`); the whole army answers when no detachment can |
| `CONTROL_GROUP_ONE` | a small diversion squad sent at a different enemy base to split their defense (only with enough bio) |
| `HARASSING_BANSHEE` / `HARASSING_REAPER` | harassers with their own targeting (`units/banshees.py`, `units/reapers.py`) |
| `SCOUTING` | a hidden-base sweep, protected from the rest of the army manager (`scouting.py`) |

* **Push or hold** is decided by the combat simulator (`fight.py`) run on our whole army against everything we know of theirs
  (`enemy_tracker.py`, which never forgets what it saw), plus the old "attack at full supply" rule. Thresholds are in `consts.py`. Once a
  push is on and the army is fighting, it is judged on the fight it is in (next bullet), not on the whole matchup; a push called off that
  way waits out the retreat before the whole-army verdict may start it again.
* **Fights** (`local_fight.py`). The simulator ignores where units stand - the same marines beat the same roaches whether they are 2 or
  110 cells apart - so the units it is handed ARE the fight. A unit is in a fight when it could get a weapon on the other side within
  4 seconds (in range now, or able to walk there; a sieged tank has to be in range already). Units still on their way and farther off, on
  either side, are left out until they arrive; two skirmishes are two fights; enemy units that dropped out of sight in the last 12
  seconds still count where they were last seen. Every unit is told the verdict of ITS OWN fight. Bio and cyclones push in ("kite in")
  only once the fight is under way (each side can already shoot the other - walking up to sieged tanks or spines is not kiting in), on
  a "very very high" verdict that also holds when they walk into a side that stands its ground, and only after it has held for 2
  seconds. Never against melee-only enemies, and never against banelings, which bio, cyclones and reapers always step back from whatever
  the simulator says (no push-in, no "futile to run").
* **The simulator is set up for the situation** (`Stance` in `fight.py`; its settings are undocumented, each was probed). Holding a
  position (`HOLD`, base defense) the enemy walks into us and the side with the longer reach gets the first volley; walking into a held
  position (`ATTACK`, kiting in) they get it; a meeting, or a fight that is under way, is everything in contact from the start. Units that
  cannot walk (sieged tanks, static defense) break the simulator's approach model - in it 20 marines beat 4 sieged tanks without losing one -
  so such fights fall back to the plain model, and whatever commits units (starting a push, kiting in, sizing a detachment) needs the plain
  model to agree too. Every unit type has its own controller in `units/`; the numbers the previous controllers were tuned with (siege
  range, liberator zones, kiting rules, ...) were kept.
* **Pre-positioning**: the hold point comes from the rally-point logic in `custom_utils.py`, the fight direction from the enemy's
  ground path to it, and before a push the tanks creep up to a stand-off point in front of static defense or sieged tanks (`staging`).
* **Marching**: ground units never hop to a point ahead of them that lies behind terrain they cannot stand on (they go for the far target
  and the engine finds the way), floating enemy buildings are not chased while ground ones exist, and an army that stops getting anywhere
  without fighting gives its target up for a while and goes for the next one (`progress.py`).
* **Sieging**: tanks stay sieged while they can shoot anything, buildings included (measured edge to edge - a Hatchery can be 16 away centre
  to centre and still be in range). Liberators are ordered into Defender Mode without waiting for the game to list the morph as usable (an
  order that never takes effect is given up on after a few tries), hold it for a shooting window after it first shows up, and come down as
  soon as nothing is inside the zone they were ordered to cover - whatever stands next to them.
* **Cyclones** kite while a Lock On runs: it keeps firing at the unit up to 15 range for as long as the unit stays in view, so the Cyclone
  steps out of enemy fire - never so far that the target leaves that range - and follows a target that is walking away; it does not spend
  a second lock while one is running. A lock that ended (the target died or left view, got out of range, the cast never took) hands the
  Cyclone back to the normal logic.
* **Banshees** skip targets they cannot shoot without flying into anti-air (unless they can cloak) and write off a target they have not
  managed to fire at for a few seconds. They never just wait: over a base with nothing to shoot they move on to the next one, and with no
  base worth a visit they rejoin the army for a while; a hurt one waits over a townhall (where the SCVs repair, only near a base) and goes
  back to work if nobody comes.
* **Bio against sieged tanks** spreads out on the way in (`TANK_SPLIT_*` in `units/bio.py`) until something is in weapon range, so a shell
  hits a few marines instead of a dozen. **Ravens** drop Auto-Turrets in front of themselves, towards the enemy (damage and something to
  shoot at), flying up to do it when the spot is safe - not under themselves.
* **Speed**: a step with a maxed army in contact takes about 45 ms offline, and the combat simulator is only ~5% of that (a few calls per
  step, cached); the rest is python-sc2/Ares bookkeeping and per-unit Python. What the army code does per unit is therefore worked out once
  per step where it can be (enemy classification in `ArmyContext`, neighbour search in `Crowd`, the workers' flee check in one distance
  table).
* Every stage of a step is guarded: a bug in one controller costs that group one step, not the game, and an emergency a-move keeps units
  from idling.

The tunables are constants at the top of the files. **None of them has been playtested** - they were picked by reasoning and by the
offline checks below.

## Setup

* **Python 3.12** (Ares supports 3.11 and 3.12 only; everything here is developed and tested on 3.12).
* Install with the same interpreter that runs the bot:
  ```
  python -m pip install -r requirements.txt
  python -m pip install --no-deps "cython-extensions-sc2>=0.18,<0.19"
  ```
  The second line is separate on purpose: `cython-extensions-sc2` (Ares' compiled helpers) declares `burnysc2` and `jupyterlab` as
  dependencies, which are not needed here (python-sc2 is vendored in `sc2/`) and would overwrite files of an older `sc2` package.
* Ares is required: there is no fallback. If it cannot be imported (wrong Python, missing compiled extension, missing
  `cython_extensions`) the bot does not start.
* The compiled helpers are per platform and Python version. Linux/macOS builds for 3.10-3.12 (`sc2_helper` also 3.13) are in git. The
  Windows `.pyd` builds are **not**: `.gitignore` has `*.py[cod]`, which also matches `.pyd`, so they only exist on the machine that
  built them. `map_analyzer/cext/mapanalyzerext.cp312-win_amd64.pyd` and `sc2_helper/sc2_helper.cp312-win_amd64.pyd` must be there.
* Local game: `python run.py`. Ladder: `run.py --LadderServer`, see `ladderbots.json`.
* **The ladder** (AI Arena: Python 3.12 on Debian, x86_64) does not read `requirements.txt` and has none of Ares' compiled helpers, so
  the zip has to carry them: Linux builds of `sc2_helper` and `map_analyzer/cext` are in their folders, and the Linux build of
  `cython-extensions-sc2` is in `vendor_linux/cython_extensions/` (`run.py` adds `vendor_linux/` to the END of `sys.path`, on Linux only,
  so a pip-installed copy still wins; provenance and update steps in `vendor_linux/README.md`). The package is GPL-3.0; its `LICENSE` is
  in the folder.
* **Uploading to the ladder**: `python arena-submission.py` builds `dist/SmoothBrainBot.zip` (git-ignored, about 8 MB; the ladder takes at
  most 50 MB) with `run.py` at its root and only what the ladder runs: `bot/`, `ares/`, `sc2/`, `map_analyzer/`, `sc2_helper/`,
  `vendor_linux/`, `run.py`, `__init__.py`, `ladderbots.json` and the `LICENSE`. Tests, training bots, `.git`, caches and every compiled file that
  is not a Linux binary (Windows `.pyd`, macOS `.so`) stay out. It runs `tests/offline/ladder_check.py` first and refuses to build if that
  fails (`--skip-check` overrides), and it is made from the working tree - the summary says which commit it started from and whether the
  zipped files have uncommitted changes. `--list` shows what would go in without building.

## python-sc2 and Ares

`sc2/` is mainline python-sc2 (BurnySc2). Ares is written against its author's fork of it (august-k/python-sc2, branch `develop`,
the dependency named in Ares' own `pyproject.toml`), and mainline lacks five things that fork has: an awaited `async` `_prepare_step`,
`_used_tumors`, `Unit.abilities`, raw integers in `UnitTypeData.attributes`, and a `Point2.__bool__` that also works for the numpy
coordinates of Ares' paths. Without any one of them the bot crashes on its first frame, Ares' ability behaviors raise, Ares' Rust combat
simulator panics and kills the process, or Ares' own `if point:` tests fail mid-game (the reaper's grenade). `bot/ares_compat.py` provides them
(read its docstring). When `sc2/` is replaced by that fork the bridge becomes redundant; `python tests/offline/bridge_status.py` says,
piece by piece, whether the `sc2/` in this folder already provides each of them.

## Offline checks

`tests/offline/` runs the bot without StarCraft II: real `Unit` objects built from hand-made game data, the real Ares managers and
combat simulator, and a synthetic map. It also has a crude physics simulation that turns the bot's commands into movement and damage so
that behaviour over time (kiting, defending, sieging, staging, order thrashing) can be watched, and a fuzzer (`fuzz_army.py`) that
throws random armies, enemies and unit states (facing, cooldowns, abilities, ...) at the whole bot and lists every exception the army
guards swallow - the kind of crash that only shows when a rare state meets one of Ares' behaviors. It is a safety net for crashes and
obviously wrong decisions, not a substitute for playing games.

```
python tests/offline/run_all.py            # everything, a couple of minutes
python tests/offline/run_all.py --quick    # skip the long physics scenarios
python tests/offline/bridge_status.py      # which parts of bot/ares_compat.py this sc2/ makes redundant
python tests/offline/ladder_check.py       # will the zip load on the AI Arena ladder (Linux builds, glibc, vendor_linux)
```

# TODO

