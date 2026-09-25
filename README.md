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
  build_order.py macro.py production.py speedmining.py custom_utils.py scouting.py
  worker_rush_defense.py worker_micro.py army_composition_advisor.py        the macro side (not Ares based)
  army/                      the Ares based army, see below
  ares_compat.py             the bridge between the vendored python-sc2 and Ares, see "python-sc2 and Ares" below
  pathing/                   order helpers used everywhere; grid_pathing/pathing_fallback/influence_costs are the in-house
                             pathing from before Ares, kept but unused
ares/                        Ares (ares-sc2 3.13.1), vendored
sc2/                         python-sc2 (mainline BurnySc2), vendored
map_analyzer/  sc2_helper/   compiled helpers Ares needs: map analysis (C) and the combat simulator (Rust)
training_bots/               bots to test against
tests/offline/               checks that need no StarCraft II, see the end of this file
```

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
  (`enemy_tracker.py`, which never forgets what it saw), plus the old "attack at full supply" rule. Thresholds are in `consts.py`.
* **Fights** are assessed per squad; bio kites, stims, and pushes in only when the simulator is very confident - except against
  banelings, which bio, cyclones and reapers always step back from (no push-in, no "futile to run", whatever the simulator says). Every
  unit type has its own controller in `units/`; the numbers the previous controllers were tuned with (siege range, liberator zones,
  kiting rules, ...) were kept.
* **Pre-positioning**: the hold point comes from the rally-point logic in `custom_utils.py`, the fight direction from the enemy's
  ground path to it, and before a push the tanks creep up to a stand-off point in front of static defense or sieged tanks (`staging`).
* **Marching**: ground units never hop to a point ahead of them that lies behind terrain they cannot stand on (they go for the far target
  and the engine finds the way), floating enemy buildings are not chased while ground ones exist, and an army that stops getting anywhere
  without fighting gives its target up for a while and goes for the next one (`progress.py`).
* **Sieging**: tanks stay sieged while they can shoot anything, buildings included (measured edge to edge - a Hatchery can be 16 away centre
  to centre and still be in range). Liberators hold Defender Mode for a shooting window after it first shows up and while an enemy is inside
  the zone they were ordered to cover. Banshees skip targets they cannot shoot without flying into anti-air (unless they can cloak) and
  write off a target they have not managed to fire at for a few seconds.
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
* Local game: `python run.py`. Ladder: `run.py --LadderServer`, see `ladderbots.json`. `cython-extensions-sc2` is a compiled pip
  package that is not vendored in this repository; see the Ares documentation on how to ship it to a ladder that does not install it for you.

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
```

# TODO

