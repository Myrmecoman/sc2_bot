"""Static API cross-check of everything bot/ calls on Ares: mediator members, manager-method kwargs, behavior fields."""
import _bootstrap  # noqa: F401  (repo root on sys.path - keep this first)
import ast, dataclasses, inspect, pathlib, sys
from ares.managers.manager_mediator import ManagerMediator
from ares.managers.path_manager import PathManager
from ares.managers.unit_memory_manager import UnitMemoryManager
from ares.managers.unit_role_manager import UnitRoleManager
from ares.managers.squad_manager import SquadManager
from ares.managers.combat_sim_manager import CombatSimManager
import ares.behaviors.combat.individual as ind
import ares.behaviors.combat.group as grp

root = _bootstrap.ROOT / "bot"
TARGET = {
    "get_units_in_range": UnitMemoryManager.units_in_range,
    "find_path_next_point": PathManager.find_path_next_point,
    "find_closest_safe_spot": PathManager.find_closest_safe_spot,
    "find_raw_path": PathManager.raw_pathfind,
    "is_position_safe": PathManager.is_position_safe,
    "assign_role": UnitRoleManager.assign_role,
    "batch_assign_role": UnitRoleManager.batch_assign_role,
    "get_units_from_role": UnitRoleManager.get_units_from_role,
    "get_units_from_roles": UnitRoleManager.get_units_from_roles,
    "get_squads": SquadManager._get_squads,
    "get_is_detected": UnitMemoryManager.get_is_detected,
    "can_win_fight": CombatSimManager.can_win_fight,
    "switch_roles": UnitRoleManager.switch_roles,
}
problems = 0
seen_members = set()
for p in sorted(root.rglob("*.py")):
    tree = ast.parse(p.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        # mediator.<member>
        if isinstance(node, ast.Attribute) and (
            (isinstance(node.value, ast.Attribute) and node.value.attr == "mediator") or
            (isinstance(node.value, ast.Name) and node.value.id == "mediator")):
            seen_members.add(node.attr)
            if not hasattr(ManagerMediator, node.attr):
                print(f"MISSING mediator member {node.attr} at {p.name}:{node.lineno}"); problems += 1
        # calls with kwargs to mediator methods
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in TARGET:
            target = TARGET[node.func.attr]
            params = set(inspect.signature(target).parameters) - {"self"}
            for kw in node.keywords:
                if kw.arg is not None and kw.arg not in params:
                    print(f"BAD KWARG {node.func.attr}({kw.arg}=...) at {p.name}:{node.lineno}; valid: {sorted(params)}"); problems += 1
            required = {n for n, prm in inspect.signature(target).parameters.items() if prm.default is inspect._empty and n != "self"}
            given = {kw.arg for kw in node.keywords if kw.arg}
            if node.args: given |= set(list(params)[:len(node.args)])
            missing = required - given
            if missing:
                print(f"MISSING REQUIRED {node.func.attr}: {sorted(missing)} at {p.name}:{node.lineno}"); problems += 1
        # Ares behavior constructors
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            cls = getattr(ind, node.func.id, None) or getattr(grp, node.func.id, None)
            if cls is not None and dataclasses.is_dataclass(cls):
                fields = {f.name for f in dataclasses.fields(cls)}
                req = {f.name for f in dataclasses.fields(cls) if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING}
                given = {kw.arg for kw in node.keywords if kw.arg}
                if node.args:
                    given |= {f.name for f in dataclasses.fields(cls)[:len(node.args)]}
                bad = given - fields
                miss = req - given
                if bad or miss:
                    print(f"BEHAVIOR {node.func.id}: bad={sorted(bad)} missing={sorted(miss)} at {p.name}:{node.lineno}"); problems += 1
print("mediator members used:", sorted(seen_members))
print("problems:", problems)
sys.exit(1 if problems else 0)
