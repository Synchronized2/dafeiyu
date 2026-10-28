"""Select per-monitor DPI before Qt creates a native window.

Qt owns WM_DPICHANGED and uses logical coordinates; callers must not multiply
mouse positions or widget sizes by the monitor's device pixel ratio again.
"""
from __future__ import annotations

import sys


def enable_per_monitor_dpi() -> None:
    if sys.platform != "win32":
        return
    import ctypes
    try:
        api = ctypes.windll.user32.SetProcessDpiAwarenessContext
        api.argtypes = [ctypes.c_void_p]
        api.restype = ctypes.c_bool
        # An existing manifest/Qt DPI context may already have set this mode.
        if api(ctypes.c_void_p(-4)):  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            return
    except (AttributeError, OSError):
        pass
    try:
        # Windows 8.1 fallback. E_ACCESSDENIED simply means it was already set.
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        pass
