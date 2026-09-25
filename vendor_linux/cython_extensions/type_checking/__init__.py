"""
Safe wrapper module for cython-extensions-sc2.
Provides type-safe wrappers for all Cython functions.
"""

from cython_extensions.type_checking.config import (
    disable_safe_mode,
    enable_safe_mode,
    get_safe_mode_status,
    is_safe_mode_enabled,
    safe_mode_context,
)
from cython_extensions.type_checking.wrappers import *

__all__ = [
    # Configuration
    "enable_safe_mode",
    "disable_safe_mode",
    "is_safe_mode_enabled",
    "get_safe_mode_status",
    "safe_mode_context",
    # All wrapped functions are imported via * from wrappers
]
