"""Will the zip load on the AI Arena ladder? Nothing here can start the ladder's Linux image (no StarCraft II, no Linux needed), so it
checks the two things that have gone wrong there, from files alone:

* the compiled pieces Ares imports at start-up exist for the ladder's interpreter (CPython 3.12, Linux x86_64) and can be loaded by
  its C library: right ELF kind, the module's init function is exported, and no symbol needs a glibc newer than the image's
  (python:3.12-slim-bookworm = glibc 2.36). A binary built on a newer distribution fails on the ladder with "version `GLIBC_2.xx'
  not found" - after an upload.
* run.py finds cython_extensions there: the ladder has no pip copy, so on Linux the vendored one in vendor_linux/ is what gets
  imported; a pip-installed copy still wins; and nothing changes on Windows.
* arena-submission.py, which zips the bot for the ladder, puts all of that (and only Linux binaries) into the zip.
"""
import _bootstrap  # noqa: F401  (repo root on sys.path - keep this first)
import json, re, struct, subprocess, sys, tempfile, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LADDER_GLIBC = (2, 36)                    # python:3.12-slim-bookworm
COMPILED = [                              # (what it is, file, name of the module it provides)
    ("combat simulator", "sc2_helper/sc2_helper.cpython-312-x86_64-linux-gnu.so", "sc2_helper"),
    ("map analysis", "map_analyzer/cext/mapanalyzerext.cpython-312-x86_64-linux-gnu.so", "mapanalyzerext"),
    ("cython-extensions-sc2", "vendor_linux/cython_extensions/bootstrap.cpython-312-x86_64-linux-gnu.so", "bootstrap"),
]
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail and not cond else ""))


def elf_info(path: Path):
    """(machine, type, highest glibc version needed, exported PyInit_ names) of a 64-bit little-endian ELF file"""
    data = path.read_bytes()
    if data[:4] != b"\x7fELF" or data[4] != 2 or data[5] != 1:
        return None
    e_type, machine = struct.unpack_from("<HH", data, 16)
    e_shoff, = struct.unpack_from("<Q", data, 40)
    e_shentsize, e_shnum = struct.unpack_from("<HH", data, 58)
    sections = [struct.unpack_from("<IIQQQQIIQQ", data, e_shoff + i * e_shentsize) for i in range(e_shnum)]
    # (name, type, flags, addr, offset, size, link, info, align, entsize)

    def strings(index):
        _, _, _, _, offset, size, *_ = sections[index]
        return data[offset:offset + size]

    def cstr(table, at):
        return table[at:table.index(b"\0", at)].decode()

    glibc, inits = (0, 0), set()
    for _, kind, _, _, offset, size, link, info, _, _ in sections:
        table = strings(link) if kind in (0x6ffffffe, 11) else b""
        if kind == 0x6ffffffe:                                   # SHT_GNU_verneed: which symbol versions it needs from libc
            at = offset
            for _ in range(info):
                _, count, _, aux, nxt = struct.unpack_from("<HHIII", data, at)
                a = at + aux
                for _ in range(count):
                    _, _, _, name, a_next = struct.unpack_from("<IHHII", data, a)
                    m = re.fullmatch(r"GLIBC_(\d+)\.(\d+)(?:\.\d+)?", cstr(table, name))
                    if m:
                        glibc = max(glibc, (int(m.group(1)), int(m.group(2))))
                    a += a_next
                at += nxt
        if kind == 11:                                           # SHT_DYNSYM: what it exports
            for i in range(size // 24):
                name, _, _, shndx, _, _ = struct.unpack_from("<IBBHQQ", data, offset + i * 24)
                if shndx != 0 and cstr(table, name).startswith("PyInit_"):
                    inits.add(cstr(table, name))
    return machine, e_type, glibc, inits


def run_block(mode):
    """The sys.path block at the top of run.py, run in a fresh interpreter as on the ladder ("ladder": Linux, nothing installed - `-S`
    leaves site-packages out), on Linux with a pip-installed copy, and on Windows. Returns where cython_extensions resolves to."""
    source = (ROOT / "run.py").read_text(encoding="utf-8")
    block = re.search(r"(if sys\.platform\.startswith\(\"linux\"\):\n(?:    .*\n)+)", source)
    code = ("import importlib.util, sys\n"
            f"__file__ = {str(ROOT / 'run.py')!r}\nimport os\n"
            + ("sys.platform = 'linux'\n" if mode != "windows" else "")
            + "before = list(sys.path)\n" + (block.group(1) if block else "") +
            "spec = importlib.util.find_spec('cython_extensions')\n"
            "print('|'.join([str(sys.path == before), sys.path[-1] if sys.path != before else '-', str(spec.origin if spec else None)]))\n")
    args = [sys.executable] + (["-S"] if mode == "ladder" else []) + ["-c", code]
    out = subprocess.run(args, capture_output=True, text=True, cwd=str(ROOT))
    unchanged, added, origin = out.stdout.strip().split("|") if out.returncode == 0 else ("?", "?", out.stderr[-300:])
    return unchanged == "True", added, origin


def build_zip():
    """runs arena-submission.py into a temporary file; returns (error text or None, {name in the zip: its first four bytes})"""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "bot.zip"
        out = subprocess.run([sys.executable, str(ROOT / "arena-submission.py"), "-o", str(target), "--skip-check"],
                             capture_output=True, text=True, cwd=str(ROOT))
        if out.returncode != 0:
            return (out.stdout + out.stderr)[-400:], {}
        with zipfile.ZipFile(target) as z:
            return None, {name: z.read(name)[:4] for name in z.namelist()}


def main():
    for label, relative, module in COMPILED:
        path = ROOT / relative
        info = elf_info(path) if path.exists() else None
        check(f"{label}: the Linux x86_64 build for Python 3.12 is in the repo ({relative})", info is not None)
        if info is None:
            continue
        machine, e_type, glibc, inits = info
        check(f"{label}: is an x86-64 shared object that exports PyInit_{module}", machine == 62 and e_type == 3 and f"PyInit_{module}" in inits,
              f"machine {machine}, type {e_type}, exports {sorted(inits)[:3]}")
        check(f"{label}: needs glibc {glibc[0]}.{glibc[1]}, the ladder image has {LADDER_GLIBC[0]}.{LADDER_GLIBC[1]}", glibc <= LADDER_GLIBC)

    ladders = json.loads((ROOT / "ladderbots.json").read_text(encoding="utf-8"))["Bots"]
    check("ladderbots.json starts run.py from the root of the zip", all(b["FileName"] == "run.py" and b["RootPath"] == "./" for b in ladders.values()))

    vendored = str(ROOT / "vendor_linux" / "cython_extensions" / "__init__.py")
    _, added, origin = run_block("ladder")
    check("ladder (Linux, no pip package): run.py makes cython_extensions resolve to vendor_linux/", origin == vendored, f"{origin}")
    unchanged, _, pip_origin = run_block("windows")          # where this interpreter finds cython_extensions when run.py's block does nothing
    if pip_origin == "None":
        print("SKIP Linux with a pip-installed copy: this interpreter has none (nothing to prefer)")
    else:
        _, _, origin = run_block("linux_with_pip")
        check("Linux with a pip-installed copy: the pip copy wins", origin == pip_origin and origin != vendored, f"{origin} instead of {pip_origin}")
    check("Windows: run.py leaves sys.path alone", unchanged)

    error, zipped = build_zip()
    check("arena-submission.py builds the zip", error is None, error or "")
    if error is None:
        wanted = ["run.py", "__init__.py", "ladderbots.json", "ares/config.yml", "ares/protoss_building_placements.yml"] + [c[1] for c in COMPILED]
        missing = [n for n in wanted if n not in zipped]
        check("the zip has run.py at its root and every file the ladder loads", not missing, str(missing))
        foreign = [n for n, head in zipped.items() if n.endswith((".so", ".pyd", ".dylib", ".dll")) and head != b"ELF"]
        check("the zip holds no Windows or macOS binaries", not foreign, str(foreign[:3]))
        stray = [n for n in zipped if n.startswith(("tests/", "training_bots/", ".git/")) or "__pycache__" in n or n.endswith(".pyc")]
        check("tests, training bots, .git and caches stay out of the zip", not stray, str(stray[:3]))

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
