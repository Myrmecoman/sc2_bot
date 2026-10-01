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
  SCVs that are mining or idle are sent, never the scout or the scripted build order's builder. A flying unit is only repaired where an
  SCV can stand under it: over the middle of a townhall (a 5x5 block, checked on Ares' clean ground grid) the SCV stops at the edge, out
  of repair range.
* **The worker-rush defense** (`worker_rush_defense.py`) pulls workers (the rushers' number + 1) only against enemy workers within 10 of
  a structure of ours that stands at home - within 30 of one of our townhalls - and sends them to the closest of those. A structure of
  ours anywhere else (a Raven's Auto-Turret next to the enemy's mineral line) does not count: it used to, and 14 enemy drones around one
  pulled 15 SCVs across the map to attack the enemy's base. As a safety net, a worker that is attacking more than 45 from every townhall
  is sent back to mining. The army's base defense (`army/defense.py`) does not take an Auto-Turret for a base either.
* **Workers dodge Oracles** (`worker_micro.py`): a worker within 7.5 of an Oracle moves straight away from it (from all of them, the nearer
  counting for more) - to walkable ground within 22 of a townhall, 6 at a time, so it is never inside the Pulsar Beam's range (5 is what
  they keep out of) - instead of running to the townhall like from any other threat, which is where the Oracle follows them to. A worker
  that has fled stays out, not back to mining under the Oracle, until it is more than 10 away or gone. A hallucinated Oracle moves nobody;
  SCVs that are repairing or constructing are left alone.
* **SCVs are not afraid of what cannot hurt them** (`HARMLESS_TO_WORKERS` in `pathing/consts.py`): changelings, Observers (and larva and
  eggs) never send a worker to the townhall (`flee_worker_threats`), hold an SCV back from resuming an unattended building
  (`resume_building_construction`) or turn the scouting SCV back - they walk and float through the mineral line for minutes, and the
  workers just carry on mining. It goes by what the unit is, not by `can_attack_ground`: a disguised changeling may be listed with the
  weapon of what it looks like. The **army** is a separate matter: changelings used to be excluded from targeting entirely
  (`ATTACK_TARGET_IGNORE`), so combat units walked past one sitting in range the same way workers correctly do - now `CHANGELING_TYPES` is
  its own list and only `HARMLESS_TO_WORKERS` keeps it; our own units treat a changeling as a normal (if low-priority) target and kill it
  in one hit, removing the free vision it gives the enemy into our army. Eggs and larva are still never worth attacking either way.
* **Reactions to the scouting** (`reactions.py`): a table of rules, "we have seen X -> change Y", applied on top of the advisor's usual
  per-race numbers every step (so nothing sticks once its trigger is gone) and logged once each as `[react] ...`. A Dark Shrine (or Dark
  Templar): the Starport makes a Raven before a Banshee, is built at once, a missile turret goes into every mineral line. A Roach Warren:
  Siege Tanks, and **money is held back for the tank** - cheap units bought all the time (Marines, 50 minerals, from several Barracks) never
  let the bank reach 150, so while a Factory stands ready and only the money is missing, production spends only what is left over
  (`priority_reserve` in `production.py`; nothing is held back when the gas or the supply is missing, or enough tanks are out). More rules
  for Lurkers, mines, Banshees, Mutalisks, Brood Lords, Colossi, Banelings, Ultralisks, Hydralisks, Battlecruisers - and against skytoss (a
  Stargate or an air unit seen) no more than 2 Siege Tanks, since they cannot shoot up, **and no turrets either** - the Factory's Cyclones
  are the answer to both, so a turret want an earlier rule raised (a Stargate is also "detected": it wants one for Oracles) is cancelled
  again by this last rule, same as the tank cap. Add a rule by adding a `Reaction(...)` to the table; `tests/offline/test_reactions.py`
  shows how a rule is tested.
* **A scouted opponent still on one base well past normal expansion timing holds back our OWN further expansion**
  (`army_composition_advisor.enemy_likely_one_base`, checked live every step - not a `reactions.py` rule, since this is about our
  macro pace, not army composition - and read by `macro.py`'s `holding_for_enemy_all_in`): whatever the extra time bought them (an
  all-in, cheese, or heavy tech investment), matching it with our own normal greedy pace - grabbing a 3rd, 4th base on schedule - is
  the wrong response. Past 5:00 with still at most one enemy townhall ever confirmed (`enemy_structures` already keeps a remembered
  structure at its last-known spot once out of vision again - buildings do not move, unlike army units, which is why
  `EnemyTracker`/`enemy_tracker.py` has to track those itself instead - so this needs no tracking of its own), our own expansion
  beyond the base we already have stops - only that: our own natural is still taken normally, and a mineral bank over 2000 is still
  spent on a new base regardless, same overflow valve `holding_for_units` already uses just above it.
* **Vehicle and ship upgrades** (`handle_upgrades`, `next_mech_upgrade` in `custom_utils.py`): bought once enough mech is out to justify them,
  by the supply of what each upgrade makes stronger - vehicle weapons by the vehicles (Hellions, Tanks, Cyclones, Thors), ship weapons by the
  ships (Vikings, Banshees, Liberators, Battlecruisers), the armor by both and the mines - and each level wants more than the one before:
  9 supply (three Tanks or Cyclones), 15, 24; a bank that piles up (800 minerals and 300 gas) buys any level at the first threshold. A level
  is only asked for once the one before it (of its line) is done. The Armory (`macro()`) is built at two bases as soon as 9 supply of mech
  is out - not, as it used to be, only after an infantry upgrade had started, which needs an Engineering Bay and three bases - and a second
  one when the mech is 24 supply and the bank is piling up, to research weapons and armor at the same time.
* **Infantry weapon/armor upgrades** (the Engineering Bay, `handle_upgrades` in `custom_utils.py`) wait for the 3rd base
  (`INFANTRY_UPGRADE_MIN_BASES`): unlike stim or cloak (a one-off buy), these come back every level and, with nothing else gating them,
  compete with actual unit production for money on every single step from the moment an Engineering Bay exists - a real game was seen
  where that alone stalled production to nothing. The Engineering Bay itself is unaffected: it still goes up as soon as the scouting
  calls for a turret or a detector.
* **Production buildings**: what the number of bases calls for, never more than 6 Barracks, 2 Factories and 2 Starports, and while the bank
  keeps piling up late in the game (1000+ minerals, 100+ supply used; the gas buildings also need 350+ gas) one more at a time up to
  those limits (`production_targets` in `macro.py`).
* **Add-ons** (`addons.py`): every Barracks, Factory and Starport gets a Reactor or a Tech Lab (half of the Barracks a Reactor, a Tech Lab
  on `factory_techlab_ratio` of the Factories, the Starports a Tech Lab first - counted on the buildings themselves), and a building that
  cannot get one is dealt with instead of staying bare. New buildings are placed where the add-on fits (`find_production_spot` in
  `macro.py`: the game is asked whether a depot-sized 2x2 fits at the add-on's spot, as python-sc2's `find_placement(addon_place=True)`
  does; where nothing has room, where the building fits). A bare building with no room (terrain, another building) **lifts** - against any
  race, not only Terran, and not during a worker or Zergling rush; the wall Barracks only once the army is bigger than the enemy army we
  know of - and lands where it and its add-on fit (the grids first, then the game's own answer; the columns of buildings stay 7 apart,
  5.5 when nothing else is found; a spot that did not work is not tried again). An add-on order the game did not take is noticed after
  3 s, asked again twice, and the building then moves; no unit is queued on a building in the step it got such an order (used to be a
  Cyclone right behind the Tech Lab). A ready building that is still bare after a minute is logged as `[addons] ...` with the reason.
  All of this waits for the scripted opening to be done, as before.
* **Against Protoss the army is mech-led** (`army_advisor.mech_focus`): Marines are picked up by almost everything a Protoss has, so the
  scripted opening (Barracks, Refinery, Orbital, Command Center, Factory) is followed by a Starport as soon as the Factory stands and
  ONE Barracks for the first two bases (2 at three bases, 3 at four; a second Factory at three bases; an Armory once the Starport is up
  AND the first bio upgrade (+1 armor or +1 attack) is done - the Cyclone's own upgrades need no Armory at all (they are researched at
  the Factory Tech Lab), so there is no reason to rush one early just because the army is mech-led).
  Every Factory gets a Tech Lab. The
  Factory makes Cyclones first (cap 12), a Siege Tank after each three of them (`factory_order` in `production.py`, cap 4 - 2 against
  skytoss) and Tanks alone once the Cyclones are at their cap; money is held back for the next one (as for the tanks above), so the bio
  is still made, but out of what is left over. Once a Cyclone is made or ordered, an idle Factory Tech Lab researches the Cyclone
  upgrade(s) it offers (`research_cyclone_upgrade`: it is asked what it can research, because which upgrade exists depends on the
  game version).

### The army (`bot/army/`)

`manager.py` runs once per step, after Ares' managers, and gives every combat unit one of these roles:

| role | what it is |
| --- | --- |
| `ATTACKING` | the main army: **hold** (pre-positioned at the rally point, tanks dug in on a slot line facing the enemy's approach path), **attack**, or **defend** |
| `BASE_DEFENDER` | a detachment split off to answer one enemy group near a base; sized with the combat simulator as the smallest group that wins (`defense.py`); the whole army answers when no detachment can |
| `CONTROL_GROUP_ONE` | a small diversion squad sent at a different enemy base to split their defense (only with enough bio) |
| `HARASSING_BANSHEE` / `HARASSING_REAPER` | harassers with their own targeting (`units/banshees.py`, `units/reapers.py`) |
| `HARASSING` | Cyclones on a raid against Protoss (`units/cyclone_raid.py`) |
| `SCOUTING` | a hidden-base sweep, protected from the rest of the army manager (`scouting.py`) |

* **Base defense holds the base's own ramp against a ground threat, rather than marching down to meet it** (`defense.py`'s
  `_hold_target`/`Positioning.hold_at_ramp`): a detachment (or, escalated, the whole army) used to be ordered straight at a threat's own
  position, whatever the terrain in between - a ground rush spotted below a base's ramp had our defenders walk down PAST the choke to
  meet it, giving up the one advantage (a narrow, single-file approach) holding there is for. Now, when the nearest base to the threat
  has its own ramp and the threat is on lower ground than it, the defenders' target is clamped to the ramp's mouth instead - they hold
  there and let it come to them. Only for a threat with a ground component: one that is purely flying (it ignores the ramp completely)
  is still met exactly where it is.
* **Workers are not sent to mine at a base under threat** (`worker_micro.base_is_threatened`, used by `speedmining.py`'s `micro_worker`
  and `dispatch_workers`): an idle worker used to be sent to whichever ready base was nearest, and an oversaturated base's extra workers
  to whichever undersaturated one had room, neither checking whether a visible hostile ground unit (not a worker, not one of
  `HARMLESS_TO_WORKERS`) was standing right next to the destination. Both now skip a threatened base - an idle worker goes to the
  nearest SAFE one instead (mining somewhere beats mining nowhere if every base happens to be threatened at once), and rebalancing
  simply does not unload onto one under threat until it clears.
* **Push or hold** is decided by the combat simulator (`fight.py`) run on our whole army against everything we know of theirs
  (`enemy_tracker.py`, which never forgets what it saw), plus the old "attack at full supply" rule. Thresholds are in `consts.py`. Once a
  push is on and the army is fighting, it is judged on the fight it is in (next bullet), not on the whole matchup; a push called off that
  way waits out the retreat before the whole-army verdict may start it again.
* **A zergling rush holds the army back from pushing out before 4 minutes** (`manager.py`'s `ZERGLING_RUSH_STAY_DEFENSIVE_UNTIL`, gating
  `_update_push_state`): the whole point of a rush like this is to lure the defender out of position and pick it off away from home -
  so while `army_advisor.zergling_rushed` is set and the game clock is still under 4:00, no new push starts, however good the simulator
  says it looks. This only blocks *starting an attack*; coming home to fight a threat at one of our bases (`Mode.DEFEND`) is untouched -
  it is checked first and does not go through this gate at all.
* **Fights** (`local_fight.py`). The simulator ignores where units stand - the same marines beat the same roaches whether they are 2 or
  110 cells apart - so the units it is handed ARE the fight. A unit is in a fight when it could get a weapon on the other side within
  4 seconds (in range now, or able to walk there; a sieged tank has to be in range already). Units still on their way and farther off, on
  either side, are left out until they arrive; two skirmishes are two fights; enemy units that dropped out of sight in the last 12
  seconds still count where they were last seen. Every unit is told the verdict of ITS OWN fight. Bio and cyclones push in ("kite in")
  only once the fight is under way (each side can already shoot the other - walking up to sieged tanks or spines is not kiting in), on
  a "very very high" verdict that also holds when they walk into a side that stands its ground, and only after it has held for 2
  seconds. Only until 1 (edge to edge) is left between the unit and its target (`stutter_forward` in `units/common.py`, instead of Ares'
  `StutterUnitForward`, which walks onto the target): the target is often what our own Siege Tanks are shelling, and a gap of 1 keeps a
  Marine just outside the splash (up to 1.25 around the shell). Never against melee-only enemies, and never against banelings, which bio, cyclones and reapers always step back from whatever
  the simulator says (no push-in, no "futile to run"). Marines and marauders also step back from melee-only enemies (Zealots, Zerglings,
  ...) that come within their weapon range + 1 while their weapon is on cooldown - shoot when ready, step back when not, without waiting
  for the danger grid (a disk of 4 around a melee unit, which flags the cell when the Zealot is already on top of the Marine) - except from
  ones much faster than they are, and they never push in with a melee unit within 10 (`MELEE_*` and `KITE_IN_MELEE_RADIUS` in `consts.py`).
* **The simulator is set up for the situation** (`Stance` in `fight.py`; its settings are undocumented, each was probed). Holding a
  position (`HOLD`, base defense) the enemy walks into us and the side with the longer reach gets the first volley; walking into a held
  position (`ATTACK`, kiting in) they get it; a meeting, or a fight that is under way, is everything in contact from the start. Units that
  cannot walk (sieged tanks, static defense) break the simulator's approach model - in it 20 marines beat 4 sieged tanks without losing one -
  so such fights fall back to the plain model, and whatever commits units (starting a push, kiting in, sizing a detachment) needs the plain
  model to agree too. Every unit type has its own controller in `units/`; the numbers the previous controllers were tuned with (siege
  range, liberator zones, kiting rules, ...) were kept.
* **Pre-positioning**: the hold point comes from the rally-point logic in `custom_utils.py` (the defend point of our newest base - a new
  Command Center counts from the moment it is **placed**, `register_base` in `bot.py`, not once it is finished - and the production
  buildings' rally points follow it: the main defends at its wall tile; a natural/third close enough to a real ramp of its own
  (`closest_ramp_point`) defends there too, instead of a blind "N cells towards the enemy" guess that has no idea whether that spot is
  even on the same plateau as the base), the fight direction from the enemy's
  ground path to it, and before a push the tanks creep up to a stand-off point in front of static defense or sieged tanks (`staging`).
  Bio holds a couple of cells ahead of the hold point, towards the enemy - but never a step LOWER than it (`Positioning.bio_position`):
  the hold point is routinely the main's wall tile, right at the ramp's mouth, so the plain forward offset could otherwise land bio a
  step down the ramp itself, in the open with no wall behind it - exactly where a rush arrives first.
* **Marching**: ground units never hop to a point ahead of them that lies behind terrain they cannot stand on (they go for the far target
  and the engine finds the way), floating enemy buildings are not chased while ground ones exist, and an army that stops getting anywhere
  without fighting gives its target up for a while and goes for the next one (`progress.py`).
* **Hidden-base hunting** (`army/scouting.py`, `SCOUTING` role): once no enemy structure at all is known, a handful of units fan out to
  every base location we have not seen yet - triggered by standing at the (Zerg/Protoss) enemy's empty start location for a while, or
  simply by having nothing better to spend supply on. Fast, expendable units (Hellions, Cyclones, bio, Thors) go first; **if none of
  those are left - a late-game tank/support deathball once the earlier assault used up the fast part of the army - it falls back to
  whatever else is spare** (a Battlecruiser, a Liberator, a Banshee, a Raven, a Medivac; never a Siege Tank, and never a Viking, which
  already sweeps the map corners on its own) rather than the sweep silently finding nobody to send and doing nothing, forever, every 90
  seconds - the reported "the enemy's main is gone, the game isn't over, and we don't scout for the rest of it" bug. Nor does it spend
  its own cooldown on an attempt that could not send anyone anywhere (nothing eligible, or nowhere left unscouted for them to go), so the
  next real attempt does not have to wait out a wasted cycle.
* **Massing** (`manager.py`, the `MIN_PUSH_SUPPLY_VS_PROTOSS` ... `REINFORCE_*` constants): Stalkers blink and kite whatever runs ahead of the
  army and skytoss out-trades bio, so against Protoss a push starts later - 60+ army supply, 90% of the ground army together (75% against the
  others) and the simulator (which knows nothing of blink) at "overwhelming", not just "decisive". Against everyone: a push that has got
  strung out stops and waits for its tail (12 s at most; the next wait is 25 s away, twice as far each time the tail failed to come); the
  stragglers of an army that is in a fight rush to it with an attack-move instead of steering round the fire; and new units do not walk
  across the map one by one - they wait at home until there is a wave (a fifth of the army out there, 8 to 20 supply) and go together. While
  the army is stopped on purpose (the staging point, a pause for the tail) the bio does not spread out towards the enemy's sieged tanks.
* **Sieging**: tanks stay sieged while they can shoot anything, buildings included (measured edge to edge - a Hatchery can be 16 away centre
  to centre and still be in range). Liberators are ordered into Defender Mode without waiting for the game to list the morph as usable (an
  order that never takes effect is given up on after a few tries), hold it for a shooting window after it first shows up, and come down as
  soon as nothing is inside the zone they were ordered to cover - whatever stands next to them.
* **Cyclones never target a cloaked, undetected enemy** (an Observer, most often - permanently cloaked, no detector needed to be seen
  yet still reported once its position is in vision: `is_visible` is about vision of the position, not about seeing through cloak). Left
  out of both Lock On candidates and the normal attack logic (`e.can_be_attacked`, i.e. not cloaked or revealed by a detector) - scoped to
  the Cyclone controller only, not the other unit types.
* **A Cyclone with nothing to fight is never assumed to be safe**: below a ramp with the enemy on top - no vision up there, so no target
  at all - it used to just attack-move blindly forward (ATTACK) or, worse, do nothing at all while already at its spot (HOLD): standing
  still and taking free fire, the exact "idle and an easy target" report. `_no_fight` (`units/cyclones.py`) now checks `ctx.is_safe`
  first and backs off, same as every other branch of the controller already did with a target in sight. The raiding Cyclones have their
  own version of the same gap: `covering` (the precise, weapon-range-based check `_info`/`_threatens` do) only trusts a ghost for
  `FIGHT_GHOST_MAX_AGE` (12s), short and tuned for the whole army's fight decisions - `danger.spots()` (`DangerMemory`, up to 45s)
  remembers a defended spot for longer, but was only ever used to avoid walking back INTO one while searching. Now it also counts towards
  `covering` itself, so a Cyclone standing right where it was shot from keeps backing out once the live ghost ages past 12s, instead of
  going quiet (not searching - nothing new to look for; not stepping back - `covering` was empty) at the foot of the same ramp.
* **Cyclones** kite while a Lock On runs: it keeps firing at the unit up to 15 range for as long as the unit stays in view, so the Cyclone
  steps out of enemy fire - never so far that the target leaves that range - and follows a target that is walking away; it does not spend
  a second lock while one is running. **The Cyclone comes first, the lock is a bonus**: in enemy fire it keeps the lock only by a way
  out that is itself safe (inside the lock's range, the target in view - see below - and no more than 3 longer than the plain way out,
  `LOCK_DETOUR`); it never stops short of safe ground just because the target would leave the lock's range there, and never takes a long
  way through the fire to keep the view. Otherwise it goes all the way out and the lock may end. If the lock started (or the target
  closed in) from closer than 6 - the Cyclone's own weapon only
  reaches 5, and the generic combat logic does not know the lock keeps working from farther out - it backs straight off to that distance
  instead of sitting in its own weapon's range for the whole lock, as long as the way back is safe. A lock that ended (the target died or
  left view, got out of range, the cast never took) hands the Cyclone back to the normal logic. **It keeps the target in view while it
  backs out**: the lock ends when the target is out of view, so a way out that leads down a ramp or behind a cliff (from a lower level
  the high ground cannot be seen: `terrain_view` in
  `pathing/order_utils.py`, heights from `game_info.terrain_height`, tolerance 8; a flying target is never hidden) or beyond the Cyclone's
  own sight (11, while the lock goes on to 15) is only taken when another unit of ours watches the target (inside its own sight range, and
  not behind a cliff unless it flies). Otherwise the Cyclone takes the nearest other safe spot that is inside its sight, sees the target
  and is no nearer to it than it is now - tried at several distances from where it stands, up to its own sight range (not a fixed handful
  of cells: a single defender's own danger radius, its weapon range plus Ares' own 4-cell buffer, is routinely 9-12, farther than a short
  fixed search would reach), 12 directions at each. With no such spot (and for a retreating army, which goes home) the plain way out
  stays: the Cyclone comes first, the lock is given up.
* **Cyclones raid Protoss** (`units/cyclone_raid.py`): against Protoss a Cyclone does not wait for the army - as long as the army is not
  pushing and nothing threatens home (the manager gives them the `HARASSING` role, and back to `ATTACKING` when a push starts or the base
  defense may need them) it goes out to hurt the enemy: lock on, step back out of reach (the lock keeps working up to 15), again. It
  **attacks only with a Lock On available** (the ability must be in the game's list for that Cyclone; waiting for the cooldown it stays out
  of reach of everything that can hit it, and out of its own weapon range of everything else, so that it does not shoot on its own). Targets:
  **units first, then Shield Batteries, then Photon Cannons**, workers when there is nothing else, no other building. Only a target it can
  reach safely: nothing else that can hit the Cyclone may cover the spot it casts from or the way there (the target itself may hit back:
  a Cannon reaches 7, a shot or two), so a unit in the middle of a Stalker ball is left alone while a lone one, a Battery or a Cannon is
  not. Reach comes from the enemies' weapons, not from Ares' danger grid (which marks 4 more around everything, workers included). With
  nothing to hit it walks towards what it knows of the enemy (a Cannon or Battery, an army, a Nexus, **or a lone worker - a valid, if
  low-priority, target and not just the ignore list `_rank` uses for it: without this a raider with nothing else around walked to a
  filler point instead and just sat there**, else their natural) and stops outside the reach of what it sees - and, once it is close
  enough to be worth a lock itself, outside the CAST range of it too (the same stand-off `_pick_target` casts from), so it arrives ready
  to cast instead of walking onto it and only backing out afterwards.
* **Hurt units go home to be repaired** (`units/repair_retreat.py`, shared by Banshees and Cyclones - the army's and the raiding ones): below
  40% of its health a unit walks to where the SCVs (`repair.py`) can reach it - a Banshee to open ground next to a townhall, a Cyclone to the
  army's hold point - and waits until it is up to 90%. The wait starts over each time the repair has got it a little further; with nothing
  happening for 25 seconds (no SCVs, no gas) it gives up, goes back to work as it is, and is not sent home again for 60 seconds.
* **Banshees** skip targets they cannot shoot without flying into anti-air (unless they can cloak) and write off a target they have not
  managed to fire at for a few seconds. They never just wait: over a base with nothing to shoot they move on to the next one, and with no
  base worth a visit they rejoin the army for a while; a hurt one waits for its repair on open ground in the lane between a townhall and
  its minerals - where the SCVs are, never over the townhall itself, which they cannot walk through - and goes back to work if nobody
  comes (the wait starts over each time the repair has got it a little further). **Cloaking waits for a real energy reserve**: turning it
  on at the bare 25-energy minimum the game requires leaves nothing to stay cloaked WITH, so it drops again almost at once for nothing -
  `_should_cloak` (`CLOAK_WORTHWHILE_ENERGY`, 50) holds off until there is a real reserve, both for reacting to danger and for treating a
  defended target as reachable - unless the banshee is already hurt enough to be retreating anyway (below 40%), where even a moment of it
  is worth having.
* **Reapers** never shoot buildings: they are never attack-moved (that shoots whatever is in range) and never left standing next to them
  (an idle unit shoots too). With no enemy unit in sight a reaper tours the two ends of the mineral line of each enemy base we know of,
  nearest first - the workers are there - leaving out an end the enemy defends, and goes on to the next stop as soon as it gets close to
  one. Units in reach are still shot first. **A thrown KD8 Charge does not go off at once**: for `GRENADE_HOLD_SECONDS` (2, approximate)
  after Ares' own `ReaperGrenade` behavior throws one, the reaper holds where it is instead of closing in on the very thing it was aimed
  at - it used to attack-move straight at it the moment it was still out of weapon range, walking into its own blast. A target already in
  range is still fought (that needs no closer approach); banelines and its own safety still come first.
* **Reapers and raiding Cyclones remember a defended spot past what Ares itself does** (`units/danger_memory.py`, `DangerMemory`): a
  defender that steps out of sight for a while does not make the ramp it stood on safe to walk back up. Whatever currently threatens a
  ground unit (`ground_defenders`: live units and structures, and Ares' own short-lived memory of them) is kept for REMEMBER_SECONDS (45,
  well past a scout's own retreat-heal-and-return cycle) whether or not it is still known to Ares, and is given up on the moment the exact
  spot is seen again and found empty - "the path is cleared" - not just on a timer. While there is nothing to fight nearby, a Reaper's way
  to its next stop routes around every such spot heavily (`avoiding_grid`: routing around costs far more than any real threat's own grid
  weight, so a genuine detour wins - but a spot with truly no way round still gets a path, just an expensive one, so a unit is never simply
  stuck); a raiding Cyclone's search for something to hit is clipped short of one the same way `_search`'s live threats already are.
* **Bio against sieged tanks** spreads out on the way in (`TANK_SPLIT_*` in `units/bio.py`) until something is in weapon range, so a shell
  hits a few marines instead of a dozen. **Ravens** drop Auto-Turrets in front of themselves, towards the enemy (damage and something to
  shoot at), flying up to do it when the spot is safe - not under themselves.
* **Against Zerg the Ravens are shared out between the parts of the army** (`ArmyManager._share_ravens`, `RAVEN_ESCORT_*` in
  `army/manager.py`): creep tumors and burrowed units are only seen - and shot - where a Raven's detection reaches, and the army is often
  in more than one place. The Raven nearest to the main army stays with it; each other part of at least 3 units (a base-defense
  detachment, the diversion squad), the biggest first, gets the nearest of the Ravens that are left (within 60), which stands in the middle
  of it (the main army's Ravens stand 4 ahead of it) until the part is gone - then it goes back to the main army. A single Raven stays with
  the main army, and against Terran and Protoss nothing is shared. Against Zerg a second Raven is made once the army is 30 supply
  (`SECOND_RAVEN_ARMY_SUPPLY`): earlier the gas is better spent elsewhere.
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

