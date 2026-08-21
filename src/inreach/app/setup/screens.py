import ctypes
import json
import logging
import pathlib

logger = logging.getLogger(__name__)

MONITORINFOF_PRIMARY = 1
CONFIG_DIR_NAME = "config"
SCREENS_FILE_NAME = "screens.json"


def get_screen_info() -> list[dict]:
    """Enumerate connected monitors via the Windows API.

    Returns a list of dicts with each monitor's device name, position,
    size, and whether it is the primary display.
    """
    from ctypes import wintypes

    class _MonitorInfoExW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
            ("szDevice", wintypes.WCHAR * 32),
        ]

    screens: list[dict] = []

    def _callback(hmonitor, hdc, lprect, lparam):
        info = _MonitorInfoExW()
        info.cbSize = ctypes.sizeof(_MonitorInfoExW)
        if ctypes.windll.user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            rect = info.rcMonitor
            screens.append(
                {
                    "device": info.szDevice,
                    "x": rect.left,
                    "y": rect.top,
                    "width": rect.right - rect.left,
                    "height": rect.bottom - rect.top,
                    "primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
                }
            )
        return 1

    monitor_enum_proc = ctypes.WINFUNCTYPE(
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.RECT),
        ctypes.c_ssize_t,
    )
    ctypes.windll.user32.EnumDisplayMonitors(None, None, monitor_enum_proc(_callback), 0)
    return screens


def assign_priorities(screens: list[dict]) -> list[dict]:
    """Annotate each screen with a ``priority``: primary is 1, rest 2, 3, ...

    Array order is left untouched (it's raw OS enumeration order); only
    the ``priority`` field is added/overwritten.
    """
    result = []
    next_priority = 2
    for screen in screens:
        annotated = dict(screen)
        if annotated.get("primary"):
            annotated["priority"] = 1
        else:
            annotated["priority"] = next_priority
            next_priority += 1
        result.append(annotated)
    return result


def guess_target_screen(screens: list[dict]) -> dict | None:
    """Guess which screen a newly launched window will appear on.

    Absent any other signal, that's the primary screen (priority 1) -
    Windows' default placement for a new top-level window.
    """
    for screen in screens:
        if screen.get("priority") == 1 or screen.get("primary"):
            return screen
    return screens[0] if screens else None


def save_screen_config(project_dir: pathlib.Path, screens: list[dict] | None = None) -> pathlib.Path:
    screens = get_screen_info() if screens is None else screens
    screens = assign_priorities(screens)

    config_dir = project_dir / CONFIG_DIR_NAME
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / SCREENS_FILE_NAME
    config_path.write_text(json.dumps(screens, indent=2), encoding="utf-8")

    logger.info("Saved screen config to %s", config_path)
    return config_path
