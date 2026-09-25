# vendor_linux

Compiled packages the AI Arena ladder image does not have and cannot be asked to install through `requirements.txt` (the ladder
does not read it). `run.py` puts this folder at the END of `sys.path`, on Linux only, so a pip-installed copy is always used in
preference and nothing changes on a Windows dev machine.

## cython_extensions/

`cython-extensions-sc2` 0.18.0 (GPL-3.0, <https://github.com/AresSC2/cython-extensions-sc2>): the compiled helpers Ares imports at
start-up (`ares/main.py`: `from cython_extensions import cy_towards, ...`). It is the `cython_extensions/` folder of this PyPI wheel,
unmodified (every file was checked against the wheel's `RECORD`):

    cython_extensions_sc2-0.18.0-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl
    sha256 9a0d3d8b20c790af274a679099b49d2601cc0c1abe268cf9948853fe2ee59783

CPython 3.12, Linux x86_64, needs glibc >= 2.14 (the ladder image, `aiarena/aiarena-docker-base`, is `python:3.12-slim-bookworm`,
glibc 2.36) and NumPy >= 1.25 (that image's `uv.lock` has 2.4). The 22 MB of the `.so` is mostly debug information; it was left as
built so that it stays identical to PyPI's.

To update it, or to cover another Python version:

    python -m pip download --no-deps --only-binary=:all: --platform manylinux_2_28_x86_64 --python-version 3.12 cython-extensions-sc2==X.Y.Z -d tmp

then unzip the wheel and replace the folder (for a second Python version, only add that wheel's `bootstrap.cpython-31x-...so` next to
the existing one). Ares 3.13.x is built against the 0.18 series.
