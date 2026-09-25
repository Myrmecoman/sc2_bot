"""Fake Ares mediator / bot for offline tests. Only implements what the army code calls; anything else raises
AttributeError on purpose so a typo or an un-modelled dependency shows up as a failing test."""
from collections import defaultdict
from types import SimpleNamespace

import numpy as np

from ares.consts import UnitRole, UnitTreeQueryType
from ares.managers.combat_sim_manager import CombatSimManager
from sc2.bot_ai import BotAI
from sc2.position import Point2
from sc2.units import Units

from gamefix import World


class FakeMediator:
    def __init__(self, ai, map_size=(200, 200)):
        self.ai = ai
        self.sim_manager = CombatSimManager(ai, {}, None)
        self.roles = defaultdict(set)            # role -> tags
        self.map_size = map_size
        self.ground = np.ones(map_size, dtype=np.float32)
        self.air = np.ones(map_size, dtype=np.float32)
        self.calls = defaultdict(int)

    # ---- combat sim
    def can_win_fight(self, **kwargs):
        self.calls["can_win_fight"] += 1
        return self.sim_manager.can_win_fight(**kwargs)

    # ---- roles
    def assign_role(self, tag, role, remove_from_squad=True):
        for r in self.roles.values():
            r.discard(tag)
        self.roles[role].add(tag)

    def batch_assign_role(self, tags, role):
        for t in tags:
            self.assign_role(t, role)

    def clear_role(self, tag):
        for r in self.roles.values():
            r.discard(tag)

    def get_units_from_role(self, role, unit_type=None, restrict_to=None):
        tags = self.roles[role]
        units = [u for u in self.ai.units if u.tag in tags]
        if unit_type is not None:
            types = {unit_type} if not isinstance(unit_type, (set, frozenset, list, tuple)) else set(unit_type)
            units = [u for u in units if u.type_id in types]
        return Units(units, self.ai)

    def get_units_from_roles(self, roles, unit_type=None):
        out = []
        for r in roles:
            out.extend(self.get_units_from_role(r, unit_type))
        return Units(out, self.ai)

    @property
    def get_unit_role_dict(self):
        return {r.name: set(t) for r, t in self.roles.items()}

    def switch_roles(self, from_role, to_role):
        self.batch_assign_role(list(self.roles[from_role]), to_role)

    # ---- squads (single greedy clustering; enough for logic tests)
    def get_squads(self, role, squad_radius=6.0, unit_type=None):
        units = list(self.get_units_from_role(role, unit_type))
        clusters = []
        for u in units:
            for c in clusters:
                cx = sum(m.position.x for m in c) / len(c)
                cy = sum(m.position.y for m in c) / len(c)
                if Point2((cx, cy)).distance_to(u.position) < squad_radius:
                    c.append(u)
                    break
            else:
                clusters.append([u])
        from ares.managers.squad_manager import UnitSquad
        squads = []
        biggest = max(clusters, key=len) if clusters else None
        for c in clusters:
            center = Point2((sum(m.position.x for m in c) / len(c), sum(m.position.y for m in c) / len(c)))
            squads.append(UnitSquad(main_squad=c is biggest, squad_id=str(id(c)), squad_position=center,
                                    squad_units=c, tags={m.tag for m in c}))
        return squads

    def remove_tag_from_squads(self, tag):
        pass

    # ---- KD-tree style queries (brute force)
    def _pool(self, query_tree):
        ai = self.ai
        if query_tree == UnitTreeQueryType.AllEnemy:
            return list(ai.all_enemy_units)
        if query_tree == UnitTreeQueryType.EnemyGround:
            return [u for u in ai.all_enemy_units if not u.is_flying]
        if query_tree == UnitTreeQueryType.EnemyFlying:
            return [u for u in ai.all_enemy_units if u.is_flying]
        if query_tree == UnitTreeQueryType.AllOwn:
            return list(ai.all_own_units)
        raise ValueError(query_tree)

    def get_units_in_range(self, start_points, distances, query_tree, return_as_dict=False):
        self.calls["get_units_in_range"] += 1
        pool = self._pool(query_tree)
        dists = distances if isinstance(distances, (list, tuple)) else [distances] * len(start_points)
        out = []
        for sp, d in zip(start_points, dists):
            pos = sp.position if hasattr(sp, "position") else Point2(sp)
            out.append(Units([u for u in pool if u.position.distance_to(pos) <= d], self.ai))
        if return_as_dict:
            return {(sp.tag if hasattr(sp, "tag") else tuple(sp)): res for sp, res in zip(start_points, out)}
        return out

    # ---- grids / pathing
    @property
    def get_ground_grid(self):
        return self.ground

    @property
    def get_cached_ground_grid(self):
        return self.ground

    @property
    def get_air_grid(self):
        return self.air

    @property
    def get_climber_grid(self):
        return self.ground

    @property
    def get_air_avoidance_grid(self):
        return self.air

    @property
    def get_ground_avoidance_grid(self):
        return self.ground

    @property
    def get_ground_to_air_grid(self):
        return self.air

    def is_position_safe(self, grid, position, weight_safety_limit=1.0):
        x, y = int(position[0]), int(position[1])
        return bool(grid[x, y] <= weight_safety_limit)

    def find_closest_safe_spot(self, from_pos, grid, radius=11):
        best, best_d = None, 1e9
        fx, fy = int(from_pos[0]), int(from_pos[1])
        for x in range(max(0, fx - radius), min(grid.shape[0], fx + radius + 1)):
            for y in range(max(0, fy - radius), min(grid.shape[1], fy + radius + 1)):
                if grid[x, y] <= 1.0:
                    d = (x - fx) ** 2 + (y - fy) ** 2
                    if d < best_d:
                        best, best_d = (x, y), d
        # like Ares: a grid CELL, as numpy ints (Point2.__bool__ and friends must cope with those)
        return Point2((np.int64(best[0]), np.int64(best[1]))) if best is not None else Point2(from_pos)

    def find_path_next_point(self, start, target, grid, sensitivity=5, smoothing=False, sense_danger=True,
                             danger_distance=20.0, danger_threshold=5.0):
        self.calls["find_path_next_point"] += 1
        return Point2(target)

    def find_raw_path(self, start, target, grid, sensitivity=5):
        """Like Ares: the cells of a straight path from just after `start` to `target`, as Points of numpy ints."""
        sx, sy, tx, ty = float(start[0]), float(start[1]), float(target[0]), float(target[1])
        steps = max(1, int(max(abs(tx - sx), abs(ty - sy)) // max(1, sensitivity)))
        return [Point2((np.int32(round(sx + (tx - sx) * i / steps)), np.int32(round(sy + (ty - sy) * i / steps))))
                for i in range(1, steps + 1)]

    def find_low_priority_path(self, start, target, grid):
        return [Point2(target)]

    # ---- terrain
    @property
    def get_enemy_expansions(self):
        return [(p, float(i)) for i, p in enumerate(self.ai.enemy_expansions)]

    @property
    def get_own_expansions(self):
        return [(p, float(i)) for i, p in enumerate(self.ai.own_expansions)]

    @property
    def get_own_nat(self):
        return self.ai.own_expansions[1]

    @property
    def get_enemy_nat(self):
        return self.ai.enemy_expansions[1]

    @property
    def get_enemy_third(self):
        return self.ai.enemy_expansions[2]

    @property
    def get_map_choke_points(self):
        return set()

    def get_is_detected(self, unit, by_enemy=True):
        return False


class FakeAI(BotAI):
    """A never-started BotAI with just enough state for the army code."""

    def _initialize_variables(self):
        # the vendored sc2 now calls this from BotAI.__init__; it assigns to attributes (units, structures, ...) that are
        # read-only properties on this fake - and the fake never needed the rest
        self.cache = {}

    def __init__(self, world: World):
        game_data = world.bot.game_data
        super().__init__()
        self.world = world
        world.bot = self
        self.state = SimpleNamespace(game_loop=100, upgrades=set(), effects=set(), dead_units=set())
        self.game_data = game_data
        self._distances_override_functions(0)
        self.actions = []
        self.unit_tags_received_action = set()
        self.unit_command_uses_self_do = False

    def setup(self, world: World, own, enemies, start=(20, 20), enemy_start=(180, 180), time=100.0):
        self.game_data = world.bot.game_data
        self._distances_override_functions(0)
        self._fake_time = time
        self._own = list(own)
        self._enemies = list(enemies)
        self.units_list = self._own
        self.start = Point2(start)
        self.enemy_start = Point2(enemy_start)
        self.actions_log = []
        self.behaviors = []
        self.same_actions = []
        self.ability_cache = {}
        self.enemy_expansions = [Point2(enemy_start), Point2((150, 150)), Point2((120, 140))]
        self.own_expansions = [Point2(start), Point2((50, 50)), Point2((80, 60))]
        return self

    # BotAI attributes the army code reads (properties on the real class; here plain data)
    @property
    def time(self):
        return self._fake_time

    @property
    def start_location(self):
        return self.start

    @property
    def enemy_start_locations(self):
        return [self.enemy_start]

    @property
    def units(self):
        return Units([u for u in self._own if not u.is_structure], self)

    @property
    def structures(self):
        return Units([u for u in self._own if u.is_structure], self)

    @property
    def townhalls(self):
        from sc2.ids.unit_typeid import UnitTypeId as U
        return Units([u for u in self._own if u.type_id in {U.COMMANDCENTER, U.PLANETARYFORTRESS, U.ORBITALCOMMAND}], self)

    @property
    def all_own_units(self):
        return Units(list(self._own), self)

    @property
    def enemy_units(self):
        return Units([u for u in self._enemies if not u.is_structure], self)

    @property
    def enemy_structures(self):
        return Units([u for u in self._enemies if u.is_structure], self)

    @property
    def all_enemy_units(self):
        return Units(list(self._enemies), self)

    def register_behavior(self, behavior):
        self.behaviors.append(behavior)

    def give_same_action(self, order, tags, target=None):
        self.same_actions.append((order, set(tags), target))


# ---------------------------------------------------------------------------------------------------------------
# a fuller scene builder used by the scenario tests
# ---------------------------------------------------------------------------------------------------------------
import asyncio
from sc2.data import Race
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as _U


class Scene:
    """A FakeAI + FakeMediator + ArmyManager wired together. Own units are created via `own(...)`, enemies via `enemy(...)`."""

    def __init__(self, enemy_race=Race.Zerg, hold_point=(60.0, 60.0), time=200.0, real_managers=False):
        self.world = World()
        self.ai = FakeAI(self.world)
        ai = self.ai
        ai.setup(self.world, [], [], time=time)
        ai.game_info = SimpleNamespace(map_center=Point2((100.0, 100.0)))
        ai.map_corners = [Point2((190, 190)), Point2((190, 10)), Point2((10, 10)), Point2((10, 190))]
        ai.expansion_locations_list = [Point2((20, 20)), Point2((50, 50)), Point2((80, 60)), Point2((120, 140)),
                                       Point2((150, 150)), Point2((180, 180))]
        ai.enemy_race = enemy_race
        ai.enemy_base_scouted = True
        ai.client = SimpleNamespace(game_step=2)
        ai.config = {}
        ai.mediator = RealishMediator(ai) if real_managers else FakeMediator(ai)
        ai.manager_hub = SimpleNamespace(combat_sim_manager=ai.mediator.sim_manager)
        ai.army_advisor = SimpleNamespace(is_wall_closed=lambda: True)
        ai.supply_army = 60
        ai.supply_cap = 120
        ai.supply_left = 30
        ai.visible = set()                    # positions reported visible by is_visible
        ai.ability_grants = {}                # tag -> set(AbilityId) returned by get_available_abilities
        self.hold_point = Point2(hold_point)
        import bot.army.positioning as positioning_module
        positioning_module.get_rally_point = lambda bot: self.hold_point
        from bot.ares_compat import install_compat
        install_compat()
        from bot.army.manager import ArmyManager
        self.manager = ArmyManager(ai)
        self.manager.positioning.front_vector = lambda hp: Point2((1.0, 0.0))     # enemy comes from +x in tests

    # -- units
    def own(self, type_id, pos, role=None, **kw):
        u = self.world.unit(type_id, pos, alliance=1, **kw)
        self.ai._own.append(u)
        if role is not None:
            self.ai.mediator.assign_role(u.tag, role)
        return u

    def enemy(self, type_id, pos, **kw):
        u = self.world.unit(type_id, pos, alliance=4, **kw)
        self.ai._enemies.append(u)
        return u

    def own_many(self, type_id, n, origin, spacing=0.6, **kw):
        return [self.own(type_id, (origin[0] + (i % 8) * spacing, origin[1] + (i // 8) * spacing), **kw) for i in range(n)]

    def enemy_many(self, type_id, n, origin, spacing=0.6, **kw):
        return [self.enemy(type_id, (origin[0] + (i % 8) * spacing, origin[1] + (i // 8) * spacing), **kw) for i in range(n)]

    # -- running
    def step(self, dt=0.5):
        ai = self.ai
        ai._fake_time += dt
        ai.state.game_loop += int(dt * 22.4)
        ai.actions.clear()
        ai.same_actions.clear()
        # every unit in a real frame is created fresh with the current game loop; unit objects that are meant to be
        # remembered ghosts are flagged `_ghost` and keep their old loop
        for u in self.world.all_units:
            if not getattr(u, "_ghost", False):
                u.game_loop = ai.state.game_loop
        if hasattr(ai.mediator, 'refresh'):
            ai.mediator.refresh()
        asyncio.get_event_loop_policy().get_event_loop().run_until_complete(self.manager.update(0)) if False else asyncio.run(self.manager.update(0))
        return list(ai.actions)

    def commands_for(self, unit):
        return [c for c in self.ai.actions if c.unit.tag == unit.tag]


def _visible_enemy_units(self):
    return Units([u for u in self._enemies if not u.is_structure and not u.is_memory], self)


FakeAI.visible_enemy_units = property(_visible_enemy_units)


async def _get_available_abilities(self, units, ignore_resource_requirements=False):
    return [list(self.ability_grants.get(u.tag, ())) for u in units]


FakeAI.get_available_abilities = _get_available_abilities


def _already_pending_upgrade(self, upgrade):
    return 1 if upgrade in self.state.upgrades else 0


FakeAI.already_pending_upgrade = _already_pending_upgrade
FakeAI.is_visible = lambda self, pos: Point2(pos) in self.visible or any(Point2(pos).distance_to(v) < 1 for v in self.visible)
FakeAI.in_map_bounds = lambda self, pos: True
FakeAI.in_pathing_grid = lambda self, pos: True
FakeAI.in_placement_grid = lambda self, pos: True


async def _can_place_single(self, building, pos):
    return True


FakeAI.can_place_single = _can_place_single
FakeAI.expansion_locations_list = None      # replaced per scene


# ---------------------------------------------------------------------------------------------------------------
# A mediator that uses the REAL Ares role / squad / unit-cache / unit-memory managers (the parts of Ares whose exact
# semantics my code depends on), and keeps the fake grid / pathing / terrain parts (they need the map C extension).
# ---------------------------------------------------------------------------------------------------------------
class RealishMediator(FakeMediator):
    def __init__(self, ai, map_size=(200, 200)):
        super().__init__(ai, map_size)
        from ares.managers.manager_mediator import ManagerMediator
        from ares.managers.unit_role_manager import UnitRoleManager
        from ares.managers.unit_cache_manager import UnitCacheManager
        from ares.managers.unit_memory_manager import UnitMemoryManager
        from ares.managers.squad_manager import SquadManager
        self.real = ManagerMediator()
        ai.unit_tag_dict = {}
        ai.start_location_ = ai.start
        self.cache = UnitCacheManager(ai, {"Debug": False}, self.real)
        self.role_mgr = UnitRoleManager(ai, {"Debug": False}, self.real)
        self.memory = UnitMemoryManager(ai, {"Debug": False}, self.real)
        self.squad_mgr = SquadManager(ai, {"Debug": False}, self.real)
        self.real.add_managers([self.cache, self.role_mgr, self.memory, self.squad_mgr])
        self.combat_sim = self.sim_manager

    def refresh(self):
        """What AresBot._prepare_units + the manager updates do each frame, minus the parts needing a running game."""
        ai = self.ai
        ai.unit_tag_dict = {u.tag: u for u in ai.all_units_list()}
        self.cache.clear_store_dicts()
        for u in ai.units:
            self.cache.store_own_unit(u, u.type_id)
        self.role_mgr.get_assigned_units()
        self.memory.all_own = ai.all_own_units
        self.memory.all_enemies = ai.all_enemy_units
        self.memory.enemy_ground, self.memory.enemy_fliers = ai.split_ground_fliers(self.memory.all_enemies)
        self.memory.generate_kd_trees()

    # --- roles / squads / KD trees delegate to the real managers -------------------------------------------------
    def assign_role(self, tag, role, remove_from_squad=True):
        self.role_mgr.assign_role(tag, role, remove_from_squad)

    def batch_assign_role(self, tags, role):
        self.role_mgr.batch_assign_role(tags, role)

    def clear_role(self, tag):
        self.role_mgr.clear_role(tag)

    def get_units_from_role(self, role, unit_type=None, restrict_to=None):
        return self.role_mgr.get_units_from_role(role, unit_type, restrict_to)

    @property
    def get_unit_role_dict(self):
        return self.role_mgr.unit_role_dict

    def get_squads(self, role, squad_radius=6.0, unit_type=None):
        return self.squad_mgr._get_squads(role=role, squad_radius=squad_radius, unit_type=unit_type)

    def remove_tag_from_squads(self, tag):
        self.squad_mgr.remove_tag(tag)

    def get_units_in_range(self, start_points, distances, query_tree, return_as_dict=False):
        self.calls["get_units_in_range"] += 1
        return self.memory.units_in_range(start_points, distances, query_tree, return_as_dict)

    @property
    def roles(self):    # tests read `mediator.roles[role]` -> set of tags
        from ares.consts import UnitRole
        return _RoleView(self.role_mgr)

    @roles.setter
    def roles(self, value):
        pass


class _RoleView(dict):
    def __init__(self, mgr):
        self.mgr = mgr

    def __getitem__(self, role):
        return self.mgr.unit_role_dict[role.name]


def _all_units_list(self):
    return list(self._own) + list(self._enemies)


FakeAI.all_units_list = _all_units_list


def _split_ground_fliers(self, units, return_as_lists=False):
    ground, fly = [], []
    for unit in units:
        (fly if unit.is_flying else ground).append(unit)
    if return_as_lists:
        return ground, fly
    return Units(ground, self), Units(fly, self)


FakeAI.split_ground_fliers = _split_ground_fliers
