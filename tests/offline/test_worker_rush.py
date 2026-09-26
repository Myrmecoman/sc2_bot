"""The worker-rush defense (bot/worker_rush_defense.py) pulls workers only against a rush AT HOME.

It used to count every enemy worker within 10 of ANY structure of ours, wherever that structure stood, and to send the pulled workers to
the first enemy worker in the list. One structure next to the enemy's mineral line (a Raven's Auto-Turret, dropped there while the army
attacked) made 14 drones "a worker rush": 15 of our workers were sent across the map to attack the enemy's base.

The whole bot on the real Ares hub:

  far structure   a structure of ours next to 14 enemy drones at THEIR base: nobody is pulled (control: with the home radius switched off
                  every worker is)
  real rush       4 enemy drones at our base, and the far group above listed first: 5 workers are pulled (their number + 1), and sent to
                  the drones at home - not to the first drone in the list
  leash           a worker attacking 100 cells from home is sent back to mine (control: with the leash off it is not); one attacking near
                  home is left to it"""
import _bootstrap  # noqa: F401  (repo root on sys.path - keep this first)
import asyncio, math
from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

import bot.worker_rush_defense as wrd
from dynamic import BASES, run_frame, start_game
from test_dynamic import build_game
import gamefix_more  # noqa: F401
from bot.bot import SmoothBrainBot

RESULTS = []
ATTACK = (AbilityId.ATTACK, AbilityId.ATTACK_ATTACK)


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail and not cond else ""))


def start():
    errors = []
    logger.remove()
    logger.add(lambda m: errors.append(str(m)) if m.record["level"].no >= 40 else None, colorize=False)
    game = build_game()
    bot = SmoothBrainBot()
    loop = asyncio.new_event_loop()
    client, proto_gi = loop.run_until_complete(start_game(game, bot))
    return {"game": game, "bot": bot, "client": client, "proto_gi": proto_gi, "loop": loop, "errors": errors, "i": 0}


def frames(env, n):
    """run n frames; returns every action sent"""
    sent = []
    for _ in range(n):
        before = len(env["client"].sent_actions)
        env["loop"].run_until_complete(run_frame(env["game"], env["bot"], env["proto_gi"], env["i"]))
        env["i"] += 1
        assert not env["errors"], env["errors"][:1]
        sent.extend(env["client"].sent_actions[before:])
    return sent


def workers_of(game):
    return [u for u in game.units_raw if u.unit_type == U.SCV.value]


def attack_orders(acts, worker_tags):
    return [a for a in acts if a.unit.tag in worker_tags and a.ability in ATTACK]


def enemy_group_at_their_base(game, structure=U.BUNKER):
    ex, ey = BASES["enemy_main"]
    game.add(structure, (ex - 6, ey - 6), 1)                                    # ours, parked next to the enemy's mineral line
    for k in range(14):
        game.add(U.DRONE, (ex - 6 + (k % 5) * 1.5 - 3, ey - 6 + (k // 5) * 1.5 - 2), 4)


def far_structure():
    env = start()
    tags = {w.tag for w in workers_of(env["game"])}
    enemy_group_at_their_base(env["game"])
    acts = frames(env, 5)
    check("far structure: 14 enemy drones around a structure of ours at THEIR base are not a rush on us: no worker is sent to attack",
          not attack_orders(acts, tags) and not env["bot"].worker_rushed, f"{len(attack_orders(acts, tags))} attack orders, worker_rushed={env['bot'].worker_rushed}")

    saved = wrd.WORKER_RUSH_HOME_RADIUS
    wrd.WORKER_RUSH_HOME_RADIUS = math.inf                                      # = every structure counts, as it did
    try:
        env = start()
        tags = {w.tag for w in workers_of(env["game"])}
        enemy_group_at_their_base(env["game"])
        acts = frames(env, 5)
        pulled = {a.unit.tag for a in attack_orders(acts, tags)}
        check("far structure (control, every structure counts): the same layout pulls the workers - all of them here", len(pulled) == len(tags) and env["bot"].worker_rushed, f"{len(pulled)}/{len(tags)}")
    finally:
        wrd.WORKER_RUSH_HOME_RADIUS = saved


def real_rush():
    env = start()
    game = env["game"]
    tags = {w.tag for w in workers_of(game)}
    enemy_group_at_their_base(game)                                             # (listed first: what `enemies.first` used to be)
    cx, cy = BASES["our_main"]
    for k in range(4):
        game.add(U.DRONE, (cx + 6 + k, cy + 6), 4)                              # at our base: within 10 of the townhall and the depot
    acts = frames(env, 5)
    orders = attack_orders(acts, tags)
    pulled = {a.unit.tag for a in orders}
    check("real rush: 4 drones at our base pull 5 workers (their number + 1) - the 14 at their own base do not count", len(pulled) == 5 and env["bot"].worker_rushed, f"{len(pulled)} pulled, worker_rushed={env['bot'].worker_rushed}")
    home = Point2((cx, cy))
    check("real rush: ...and they are sent to the drones at home, not to the first drone in the list (at the enemy's base)",
          orders and all(isinstance(a.target, Point2) and a.target.distance_to(home) < 15 for a in orders), str([a.target for a in orders][:2]))


def leash():
    cx, cy = BASES["our_main"]

    def run(leash_on):
        saved = wrd.WORKER_ATTACK_LEASH
        if not leash_on:
            wrd.WORKER_ATTACK_LEASH = math.inf
        try:
            env = start()
            frames(env, 1)                                                      # (the split of the workers over the minerals from on_start goes out with the first frame)
            far, near = workers_of(env["game"])[:2]
            for w, (x, y) in ((far, (100.0, 100.0)), (near, (cx + 12.0, cy + 12.0))):
                w.pos.x, w.pos.y = x, y
                order = w.orders.add()
                order.ability_id = AbilityId.ATTACK_ATTACK.value
                order.target_world_space_pos.x, order.target_world_space_pos.y = x + 1.0, y + 1.0
            acts = frames(env, 2)
            gathers = lambda w: [a for a in acts if a.unit.tag == w.tag and a.ability == AbilityId.HARVEST_GATHER]
            return bool(gathers(far)), bool(gathers(near))
        finally:
            wrd.WORKER_ATTACK_LEASH = saved

    recalled_far, recalled_near = run(True)
    check("leash: a worker attacking 100 cells from home is sent back to mine", recalled_far)
    check("leash: ...one attacking near home is left to it", not recalled_near)
    recalled_far, _ = run(False)
    check("leash (control, leash off): the far attacker is left to it", not recalled_far)


def main():
    far_structure()
    real_rush()
    leash()
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
