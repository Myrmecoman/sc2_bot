__version__ = "0.18.0"

# bootstrap is the only module which
# can be loaded with default Python-machinery
# because the resulting extension is called `bootstrap`:
from . import bootstrap

# injecting our finders into sys.meta_path
# after that all other submodules can be loaded
bootstrap.bootstrap_cython_submodules()

# Import configuration functions from the safe module
from cython_extensions.type_checking import (
    disable_safe_mode,
    enable_safe_mode,
    get_safe_mode_status,
    is_safe_mode_enabled,
    safe_mode_context,
)

# Import all functions from the safe wrappers module
# These handle the conditional validation internally
from cython_extensions.type_checking.wrappers import *
