"""A crude physics + combat simulation layered on the dynamic harness: turns the bot's commands into unit movement, attacks,
damage and deaths so multi-step behaviour (kiting, holding, defending, sieging, retreating) can be observed.

Deliberately simple - it is meant to expose oscillation, thrashing and obviously wrong decisions, not to be balanced."""
import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from s2clientprotocol import raw_pb2

from sc2.ids.ability_id import AbilityId as A
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

import gamefix

LOOPS_PER_SECOND = 22.4
SIEGE_TRANSFORM_SECONDS = 2.7
STIM_SECONDS = 11.0
MELEE_REACH = 0.4


@dataclass
class SimUnit:
    tag: int
    type_id: U
    alliance: int
    x: float
    y: float
    hp: float
    shield: float = 0.0
    cooldown: float = 0.0           # loops until the weapon is ready
    order: Optional[dict] = None    # {"kind": "move"|"attack_move"|"attack_unit"|"hold", ...}
    transform_until: float = 0.0
    morph_to: Optional[U] = None
    stim_until: float = 0.0
    energy: float = 50.0
    flying: bool = False
    is_structure: bool = False

    @property
    def stats(self):
        return gamefix.STATS.get(self.type_id)

    def weapons(self):
        s = self.stats
        return s[4] if s else []

    def speed(self):
        s = self.stats
        base = s[3] if s else 0.0
        return base * (1.5 if self.stim_until > 0 else 1.0)

    def radius(self):
        return gamefix.RADIUS.get(self.type_id, 0.375)


def dist(a: SimUnit, b: SimUnit) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


class Physics:
    """Owns the authoritative unit state; regenerates the game's raw unit protos from it every frame."""

    def __init__(self, game, seed=1):
        self.game = game
        self.units: Dict[int, SimUnit] = {}
        self.rng = random.Random(seed)
        self.loop = game.game_loop
        self.dead_this_frame: List[int] = []
        self.kills = {1: 0, 4: 0}       # units killed BY alliance
        self.losses = {1: 0, 4: 0}
        self.order_flips = 0            # how many times a unit's order kind/target changed (oscillation metric)
        self._last_order_sig: Dict[int, tuple] = {}
        self.static_protos = []
        self.splash_deaths = {1: 0, 4: 0}   # units killed by baneling splash, by the alliance that LOST them
        self.baneling_explosions = 0        # banelings that reached something and blew up (the others were shot down)

    # ---- populating -------------------------------------------------------------------------------------------
    def adopt_existing(self):
        """Take over the protos already in game.units_raw (neutral units stay static protos)."""
        keep = []
        for p in self.game.units_raw:
            if p.alliance == 3 or p.unit_type in (U.COMMANDCENTER.value, U.SUPPLYDEPOT.value, U.BARRACKS.value, U.HATCHERY.value, U.SPINECRAWLER.value):
                keep.append(p)
                if p.alliance in (1, 4):
                    self.units[p.tag] = self._from_proto(p)
                continue
            self.units[p.tag] = self._from_proto(p)
        # neutral resources and worker protos stay static forever; everything the physics owns is regenerated each frame
        self.static_protos = [p for p in keep if p.alliance == 3] + [p for p in keep if p.alliance != 3 and p.tag not in self.units]
        self.game.units_raw = list(self.static_protos)

    def _from_proto(self, p) -> SimUnit:
        t = U(p.unit_type)
        s = gamefix.STATS.get(t)
        return SimUnit(tag=p.tag, type_id=t, alliance=p.alliance, x=p.pos.x, y=p.pos.y, hp=p.health, shield=p.shield,
                       flying=p.is_flying, is_structure=bool(s and gamefix.STRUCT in s[5]), energy=p.energy or 50.0)

    def add(self, type_id, pos, alliance, **kw) -> SimUnit:
        p = self.game.unit_proto(type_id, pos, alliance, **kw)
        u = self._from_proto(p)
        self.units[u.tag] = u
        return u

    # ---- applying the bot's commands ---------------------------------------------------------------------------
    def apply(self, actions):
        for a in actions:
            u = self.units.get(a.unit.tag)
            if u is None or u.alliance != 1:
                continue
            ab = a.ability
            target = a.target
            if ab in (A.MOVE_MOVE, A.MOVE, A.SMART) and isinstance(target, (Point2, tuple)):
                self._set_order(u, {"kind": "move", "pos": Point2(target)}, a.queue)
            elif ab in (A.ATTACK, A.ATTACK_ATTACK, A.SCAN_MOVE):
                if isinstance(target, (Point2, tuple)):
                    self._set_order(u, {"kind": "attack_move", "pos": Point2(target)}, a.queue)
                elif hasattr(target, "tag"):
                    self._set_order(u, {"kind": "attack_unit", "tag": target.tag}, a.queue)
            elif ab == A.SIEGEMODE_SIEGEMODE and u.type_id == U.SIEGETANK and u.morph_to is None:
                u.morph_to, u.transform_until = U.SIEGETANKSIEGED, self.loop + SIEGE_TRANSFORM_SECONDS * LOOPS_PER_SECOND
            elif ab == A.UNSIEGE_UNSIEGE and u.type_id == U.SIEGETANKSIEGED and u.morph_to is None:
                u.morph_to, u.transform_until = U.SIEGETANK, self.loop + SIEGE_TRANSFORM_SECONDS * LOOPS_PER_SECOND
            elif ab in (A.EFFECT_STIM_MARINE, A.EFFECT_STIM_MARAUDER) and u.stim_until <= 0 and u.hp > 10:
                u.hp -= 10
                u.stim_until = self.loop + STIM_SECONDS * LOOPS_PER_SECOND
            elif ab == A.MEDIVACHEAL_HEAL and hasattr(target, "tag"):
                self._set_order(u, {"kind": "heal", "tag": target.tag}, a.queue)

    def _set_order(self, u: SimUnit, order: dict, queue: bool):
        sig = (order["kind"], order.get("tag"), tuple(round(v) for v in order["pos"]) if "pos" in order else None)
        if not queue:
            if self._last_order_sig.get(u.tag) != sig:
                self.order_flips += 1
            self._last_order_sig[u.tag] = sig
            u.order = order
            u.queue = []
        else:
            if not hasattr(u, "queue"):
                u.queue = []
            u.queue.append(order)

    # ---- one game step ----------------------------------------------------------------------------------------
    def step(self, loops=2):
        self.dead_this_frame = []
        for _ in range(loops):
            self.loop += 1
            self._enemy_ai()
            for u in list(self.units.values()):
                self._tick(u)
            for u in list(self.units.values()):
                if u.hp <= 0:
                    self._kill(u)
        self._regenerate()

    def _kill(self, u: SimUnit):
        self.units.pop(u.tag, None)
        self.dead_this_frame.append(u.tag)
        self.losses[u.alliance] = self.losses.get(u.alliance, 0) + 1

    def _enemy_ai(self):
        """Enemy units a-move at our closest unit/structure and attack whatever is nearest in reach."""
        ours = [u for u in self.units.values() if u.alliance == 1]
        for e in self.units.values():
            if e.alliance != 4 or e.is_structure or e.morph_to:
                continue
            if not ours:
                continue
            nearest = min(ours, key=lambda o: dist(e, o))
            e.order = {"kind": "attack_move", "pos": Point2((nearest.x, nearest.y))}

    def _tick(self, u: SimUnit):
        if u.is_structure:
            self._fire(u, 0.0)       # structures with weapons still shoot
            return
        if u.cooldown > 0:
            u.cooldown -= 1
        if u.morph_to and self.loop >= u.transform_until:
            u.type_id, u.morph_to = u.morph_to, None
        if u.stim_until and self.loop >= u.stim_until:
            u.stim_until = 0
        if u.morph_to:
            return
        # regeneration for nothing; medivac healing
        order = u.order
        if order is None and getattr(u, "queue", None):
            u.order = order = u.queue.pop(0)
        if u.type_id in (U.MEDIVAC,):
            self._medivac(u, order)
            return
        if not u.weapons():
            self._move_towards_order(u, order)
            return
        target = self._choose_target(u, order)
        if target is not None and self._in_range(u, target):
            if u.type_id == U.SIEGETANKSIEGED or True:
                self._fire(u, 0.0, target)
            return       # standing still while attacking
        if target is not None and order and order["kind"] in ("attack_unit", "attack_move") and u.type_id != U.SIEGETANKSIEGED:
            self._step_to(u, target.x, target.y)
            return
        self._move_towards_order(u, order)

    def _medivac(self, u: SimUnit, order):
        if order and order["kind"] == "heal":
            t = self.units.get(order["tag"])
            if t and dist(u, t) < 4.0 and t.hp < (t.stats[0] if t.stats else 100):
                t.hp = min(t.stats[0], t.hp + 12.6 / LOOPS_PER_SECOND)
            elif t:
                self._step_to(u, t.x, t.y)
            return
        self._move_towards_order(u, order)

    def _move_towards_order(self, u: SimUnit, order):
        if not order or u.type_id == U.SIEGETANKSIEGED:
            return
        if order["kind"] in ("move", "attack_move"):
            p = order["pos"]
            if math.hypot(u.x - p.x, u.y - p.y) < 0.6:
                u.order = None
                return
            self._step_to(u, p.x, p.y)
        elif order["kind"] == "attack_unit":
            t = self.units.get(order["tag"])
            if t is None:
                u.order = None
            else:
                self._step_to(u, t.x, t.y)

    def _step_to(self, u: SimUnit, x, y):
        d = math.hypot(x - u.x, y - u.y)
        if d < 1e-6:
            return
        step = u.speed() / LOOPS_PER_SECOND
        f = min(1.0, step / d)
        u.x += (x - u.x) * f
        u.y += (y - u.y) * f

    def _hits(self, u: SimUnit, t: SimUnit):
        """The weapon of u that can hit t, or None."""
        for kind, dmg, attacks, rng, cd, bonus in u.weapons():
            if (t.flying and kind in (gamefix.AIR, gamefix.ANY)) or (not t.flying and kind in (gamefix.GROUND, gamefix.ANY)):
                return kind, dmg, attacks, rng, cd, bonus
        return None

    def _in_range(self, u: SimUnit, t: SimUnit) -> bool:
        w = self._hits(u, t)
        if w is None:
            return False
        return dist(u, t) <= w[3] + u.radius() + t.radius() + (MELEE_REACH if w[3] < 1 else 0.0)

    def _choose_target(self, u: SimUnit, order) -> Optional[SimUnit]:
        if order and order["kind"] == "attack_unit":
            t = self.units.get(order["tag"])
            if t and t.alliance != u.alliance and self._hits(u, t):
                return t
            u.order = None
        best, best_d = None, 1e9
        for t in self.units.values():
            if t.alliance == u.alliance or t.alliance == 3 or not self._hits(u, t):
                continue
            d = dist(u, t)
            if d < best_d:
                best, best_d = t, d
        if best is None:
            return None
        # units only auto-acquire within ~ (range + 4) unless on an attack-move
        w = self._hits(u, best)
        acquire = w[3] + 4.0
        if order and order["kind"] == "attack_move":
            acquire = 12.0
        elif order and order["kind"] == "move":
            return None                    # a move command ignores enemies
        return best if best_d <= acquire + u.radius() + best.radius() else None

    def _fire(self, u: SimUnit, _unused, target: Optional[SimUnit] = None):
        if u.cooldown > 0:
            return
        if target is None:
            best, best_d = None, 1e9
            for t in self.units.values():
                if t.alliance == u.alliance or t.alliance == 3 or not self._hits(u, t):
                    continue
                d = dist(u, t)
                if d < best_d:
                    best, best_d = t, d
            if best is None or not self._in_range(u, best):
                return
            target = best
        if u.type_id == U.BANELING:
            self._baneling_explode(u, target)
            return
        w = self._hits(u, target)
        kind, dmg, attacks, rng, cd, bonus = w
        attrs = target.stats[5] if target.stats else []
        armor = target.stats[2] if target.stats else 0
        total = 0.0
        for _ in range(int(attacks)):
            d = dmg + sum(b for attr, b in bonus if attr in attrs)
            total += max(0.5, d - armor)
        if target.shield > 0:
            absorbed = min(target.shield, total)
            target.shield -= absorbed
            total -= absorbed
        target.hp -= total
        speed_up = 1.5 if u.stim_until > 0 else 1.0
        u.cooldown = cd * LOOPS_PER_SECOND / speed_up
        if target.hp <= 0:
            self.kills[u.alliance] = self.kills.get(u.alliance, 0) + 1

    BANELING_SPLASH_RADIUS = 2.2

    def _baneling_explode(self, u: SimUnit, target: SimUnit):
        """A baneling dies on contact and hurts every enemy ground unit around the one it hit (light units take extra)."""
        _, dmg, _, _, _, bonus = u.weapons()[0]
        self.baneling_explosions += 1
        for t in list(self.units.values()):
            if t.alliance == u.alliance or t.alliance == 3 or t.flying or t.is_structure:
                continue
            if math.hypot(t.x - target.x, t.y - target.y) > self.BANELING_SPLASH_RADIUS:
                continue
            attrs = t.stats[5] if t.stats else []
            armor = t.stats[2] if t.stats else 0
            total = max(0.5, dmg + sum(b for attr, b in bonus if attr in attrs) - armor)
            was_alive = t.hp > 0
            t.hp -= total
            if was_alive and t.hp <= 0 and t.tag != u.tag:
                self.kills[u.alliance] = self.kills.get(u.alliance, 0) + 1
                self.splash_deaths[t.alliance] = self.splash_deaths.get(t.alliance, 0) + 1
        u.hp = 0

    # ---- writing the state back into the game's raw protos ----------------------------------------------------------
    def _regenerate(self):
        game = self.game
        game.game_loop = self.loop
        regenerated = []
        for u in self.units.values():
            p = game.unit_proto(u.type_id, (u.x, u.y), u.alliance, hp=max(1.0, u.hp), tag=u.tag, energy=u.energy)
            p.shield = max(0.0, u.shield)
            p.weapon_cooldown = max(0.0, u.cooldown)
            p.is_flying = u.flying
            if u.stim_until > 0:
                p.buff_ids.append(BuffId.STIMPACK.value)
            if u.order:
                o = p.orders.add()
                kind = u.order["kind"]
                o.ability_id = (A.MOVE_MOVE if kind == "move" else A.ATTACK_ATTACK if kind in ("attack_move", "attack_unit") else A.MEDIVACHEAL_HEAL).value
                if "pos" in u.order:
                    o.target_world_space_pos.x, o.target_world_space_pos.y = u.order["pos"].x, u.order["pos"].y
                elif "tag" in u.order:
                    o.target_unit_tag = u.order["tag"]
            if u.morph_to:
                o = p.orders.add()
                o.ability_id = (A.SIEGEMODE_SIEGEMODE if u.morph_to == U.SIEGETANKSIEGED else A.UNSIEGE_UNSIEGE).value
            regenerated.append(p)
        # static protos (minerals, geysers) stay; structures the physics owns are regenerated above, so drop duplicates
        game.units_raw = list(self.static_protos) + regenerated
        game.dead = list(self.dead_this_frame)


class TerrainPhysics(Physics):
    """Physics whose ground units move the way the engine moves them: along the real shortest path to wherever they were
    ordered, or - when that place cannot be stood on - to the closest spot that can be reached, and stop there. That is
    what makes a unit sent to a spot behind a cliff press itself against the cliff, which the plain straight-line
    Physics cannot show. Paths come from the same Ares pathfinder the bot uses (`bot.mediator.find_raw_path`)."""

    def __init__(self, game, bot, seed=1):
        super().__init__(game, seed)
        self.bot = bot
        self._route: Dict[int, tuple] = {}

    def _step_to(self, u, x, y):
        if u.flying:
            return super()._step_to(u, x, y)
        goal = (round(x), round(y))
        route = self._route.get(u.tag)
        if route is None or route[0] != goal:
            route = (goal, self._waypoints(u, x, y))
            self._route[u.tag] = route
        waypoints = route[1]
        while waypoints and math.hypot(waypoints[0][0] - u.x, waypoints[0][1] - u.y) < 0.5:
            waypoints.pop(0)
        if waypoints:
            super()._step_to(u, waypoints[0][0], waypoints[0][1])

    def _waypoints(self, u, x, y):
        mediator = self.bot.mediator
        grid = mediator.get_cached_ground_grid

        def path_to(px, py):
            return mediator.find_raw_path(start=Point2((u.x, u.y)), target=Point2((px, py)), grid=grid, sensitivity=1)

        walk = self.game.pathing                                     # [y, x]: 1 = can be stood on
        gx, gy = int(x), int(y)
        path = None
        if 0 <= gy < walk.shape[0] and 0 <= gx < walk.shape[1] and walk[gy, gx]:
            path = path_to(x, y)
        else:
            y0, y1, x0, x1 = max(0, gy - 12), min(walk.shape[0], gy + 13), max(0, gx - 12), min(walk.shape[1], gx + 13)
            cells = sorted(((cy + y0, cx + x0) for cy, cx in zip(*walk[y0:y1, x0:x1].nonzero())),
                           key=lambda c: (c[1] + 0.5 - x) ** 2 + (c[0] + 0.5 - y) ** 2)
            for cy, cx in cells[:12]:
                path = path_to(cx + 0.5, cy + 0.5)
                if path:
                    break
        return [(float(p[0]) + 0.5, float(p[1]) + 0.5) for p in path] if path else []
