"""Configuration utilities for safe mode in cython-extensions-sc2."""

import os
import threading

try:
    from propcache.api import cached_property
except ImportError:
    from functools import cached_property


class SafeModeConfig:
    """Thread-safe configuration for safe mode."""

    def __init__(self):
        self._lock = threading.Lock()
        self._enabled = self._read_initial_state()

    def _read_initial_state(self) -> bool:
        """Read initial state from environment variable."""
        env_value = os.environ.get("CYTHON_EXTENSIONS_SAFE_MODE", "false")
        return env_value.lower() in ("true", "1", "yes", "on")

    @cached_property
    def enabled(self) -> bool:
        """Check if safe mode is enabled."""
        with self._lock:
            return self._enabled

    def enable(self, enabled: bool = True):
        """Enable or disable safe mode."""
        with self._lock:
            self._enabled = enabled

    def disable(self):
        """Disable safe mode."""
        self.enable(False)


# Global configuration instance
_config = SafeModeConfig()


def enable_safe_mode(enabled: bool = True):
    """
    Enable or disable safe mode for type checking globally.

    Args:
        enabled: Whether to enable safe mode

    """
    _config.enable(enabled)


def disable_safe_mode():
    """Disable safe mode for type checking globally."""
    _config.disable()

def is_safe_mode_enabled() -> bool:
    """Check if safe mode is currently enabled."""
    return _config.enabled


def get_safe_mode_status() -> str:
    """Get a human-readable status of safe mode."""
    return "ENABLED" if _config.enabled else "DISABLED"


def safe_mode_context(enabled: bool = True):
    """
    Context manager for temporarily enabling/disabling safe mode.

    Args:
        enabled: Whether to enable safe mode in this context

    """

    class SafeModeContext:
        def __init__(self, enable: bool):
            self.enable = enable
            self.previous_state = None

        def __enter__(self):
            self.previous_state = is_safe_mode_enabled()
            enable_safe_mode(self.enable)
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            enable_safe_mode(self.previous_state)

    return SafeModeContext(enabled)
