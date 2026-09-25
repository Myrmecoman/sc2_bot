#!/usr/bin/env python3
"""
Builds the zip to upload to the AI Arena ladder (https://aiarena.net):  python arena-submission.py  ->  dist/SmoothBrainBot.zip

    python arena-submission.py                  build dist/<bot name>.zip (after tests/offline/ladder_check.py passes)
    python arena-submission.py --list           show every file that would go into the zip, build nothing
    python arena-submission.py -o some.zip      write it somewhere else
    python arena-submission.py --skip-check     do not run tests/offline/ladder_check.py first
"""
import argparse
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# what goes into the zip: these files and, recursively, these folders. Everything else in the repo stays out.
FILES = ["run.py", "__init__.py", "ladderbots.json", "LICENSE"]
DIRECTORIES = ["bot", "ares", "sc2", "map_analyzer", "sc2_helper", "vendor_linux"]
CACHE_DIRECTORIES = {"__pycache__"}
CACHE_SUFFIXES = {".pyc", ".pyo"}
NATIVE_SUFFIXES = {".so", ".pyd", ".dylib", ".dll"}      # compiled files: kept only when they are Linux (ELF) binaries
ELF_MAGIC = b"\x7fELF"
SIZE_LIMIT = 50 * 1000 * 1000                            # AI Arena: a bot zip is at most 50 MB (decimal, to be on the safe side)


def is_wanted(relative: Path) -> bool:
    if any(part in CACHE_DIRECTORIES for part in relative.parts) or relative.suffix in CACHE_SUFFIXES:
        return False
    if relative.suffix in NATIVE_SUFFIXES:
        with open(ROOT / relative, "rb") as f:
            return f.read(4) == ELF_MAGIC
    return True


def collect(output: Path):
    """(files that go into the zip, compiled files left out because they are not Linux binaries), both as paths relative to ROOT"""
    missing = [name for name in FILES + DIRECTORIES if not (ROOT / name).exists()]
    if missing:
        sys.exit("arena-submission: missing from the repository: " + ", ".join(missing))
    files, left_out = [Path(name) for name in FILES], []
    for name in DIRECTORIES:
        for path in (ROOT / name).rglob("*"):
            if not path.is_file() or path == output:
                continue
            relative = path.relative_to(ROOT)
            if is_wanted(relative):
                files.append(relative)
            elif relative.suffix in NATIVE_SUFFIXES:
                left_out.append(relative)
    files.sort(key=lambda p: p.as_posix())
    left_out.sort(key=lambda p: p.as_posix())
    return files, left_out


def ladder_checks() -> bool:
    check = ROOT / "tests" / "offline" / "ladder_check.py"
    if not check.exists():
        print("note: tests/offline/ladder_check.py is not there, skipping the ladder checks")
        return True
    result = subprocess.run([sys.executable, str(check)], cwd=str(ROOT), capture_output=True, text=True)
    lines = [line for line in (result.stdout + result.stderr).splitlines() if line.strip()]
    if result.returncode != 0:
        print("\n".join(lines))
        print("\nThe ladder checks failed, no zip was built (--skip-check builds it anyway).")
        return False
    print("ladder checks:", lines[-1])
    return True


def build(files, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for relative in files:
            z.write(ROOT / relative, relative.as_posix())      # forward slashes: the ladder unzips on Linux


def verify(output: Path):
    """what the ladder needs from the zip, read back from the file that was just written; returns the list of problems found"""
    with zipfile.ZipFile(output) as z:
        names = z.namelist()
        problems = []
        if z.testzip() is not None:
            problems.append("the archive is corrupt")
        for required in ("run.py", "__init__.py", "ladderbots.json", "vendor_linux/cython_extensions/__init__.py"):
            if required not in names:
                problems.append(f"{required} is not in the zip")
        if not any(n.startswith("vendor_linux/cython_extensions/bootstrap.") and n.endswith(".so") for n in names):
            problems.append("no Linux build of cython_extensions in the zip")
        if any("\\" in n or n.startswith("/") for n in names):
            problems.append("entry names must be relative and use forward slashes")
        if any(n.endswith((".pyd", ".pyc")) or "__pycache__" in n or n.startswith(("tests/", "training_bots/", ".git/")) for n in names):
            problems.append("something that should have stayed out got in")
    return problems


def megabytes(size: int) -> str:
    return f"{size / 1e6:6.1f} MB"


def summary(output: Path, left_out) -> None:
    with zipfile.ZipFile(output) as z:
        groups = {}
        for info in z.infolist():
            top = info.filename.split("/")[0] + "/" if "/" in info.filename else "(root files)"
            count, size, zipped = groups.get(top, (0, 0, 0))
            groups[top] = (count + 1, size + info.file_size, zipped + info.compress_size)
    print(f"\n  {'':16s}{'files':>6s}{'size':>11s}{'zipped':>11s}")
    for top, (count, size, zipped) in sorted(groups.items()):
        print(f"  {top:16s}{count:6d}{megabytes(size):>11s}{megabytes(zipped):>11s}")
    if left_out:
        print(f"  left out: {len(left_out)} compiled files that are not Linux binaries (Windows .pyd, macOS .so)")


def git_state():
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT), capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--"] + FILES + DIRECTORIES, cwd=str(ROOT), capture_output=True, text=True,
                               check=True).stdout.strip().splitlines()
    except (OSError, subprocess.CalledProcessError):
        return None
    return f"commit {head}" + (f" + {len(dirty)} uncommitted change(s) in the zipped files" if dirty else " (nothing uncommitted in the zipped files)")


def main() -> int:
    try:
        name, info = next(iter(json.loads((ROOT / "ladderbots.json").read_text(encoding="utf-8"))["Bots"].items()))
    except (OSError, ValueError, KeyError, StopIteration) as e:
        sys.exit(f"arena-submission: cannot read the bot from ladderbots.json: {e!r}")
    parser = argparse.ArgumentParser(prog="arena-submission.py", description="Build the zip to upload to the AI Arena ladder.")
    parser.add_argument("-o", "--output", type=Path, default=ROOT / "dist" / f"{name}.zip",
                        help="where to write the zip (default: dist/<bot name from ladderbots.json>.zip)")
    parser.add_argument("--list", action="store_true", help="only list the files that would go into the zip")
    parser.add_argument("--skip-check", action="store_true", help="do not run tests/offline/ladder_check.py first")
    args = parser.parse_args()
    output = args.output.resolve()

    files, left_out = collect(output)
    if args.list:
        total = 0
        for relative in files:
            size = (ROOT / relative).stat().st_size
            total += size
            print(f"{size:>10,d}  {relative.as_posix()}")
        print(f"\n{len(files)} files, {total / 1e6:.1f} MB before compression; {len(left_out)} non-Linux compiled files would be left out")
        return 0

    if not args.skip_check and not ladder_checks():
        return 1
    build(files, output)
    problems = verify(output)
    if problems:
        output.unlink()                                   # a wrong zip must not be left around to be uploaded
        print("arena-submission: the zip is wrong, so it was removed: " + "; ".join(problems))
        return 1
    size = output.stat().st_size
    print(f"\nbuilt {output}")
    print(f"{len(files)} files, {size / 1e6:.1f} MB zipped (the ladder takes at most {SIZE_LIMIT // 1000000} MB), from {git_state() or 'the working tree'}")
    summary(output, left_out)
    if size > SIZE_LIMIT:
        output.unlink()
        print(f"\nTOO BIG: {size / 1e6:.1f} MB is over the ladder's {SIZE_LIMIT // 1000000} MB limit, so the zip was removed.")
        return 1
    print(f"\nUpload it on aiarena.net as a {info.get('Type', 'Python')} bot, race {info.get('Race', '?')}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
