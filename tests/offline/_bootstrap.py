"""Put the repository root on sys.path so `import bot...`, `import ares...` and the vendored `sc2` resolve when a script in
this folder is run directly (`python tests/offline/<script>.py`). Imported first by every entry-point script."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
