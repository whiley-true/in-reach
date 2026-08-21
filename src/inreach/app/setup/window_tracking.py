"""Screen-priority guessing and window position/fullscreen capture.

``poll_and_record_window`` has no permanent consumer yet (there's no
background polling loop), but is called once from the MCC EAC-disabled
launch step during setup so we start building up ``window.history``.
"""

import ctypes
import datetime
import json
import logging
import pathlib
from typing import Callable

from inreach.app.setup import screens

logger = logging.getLogger(__name__)

WINDOW_HISTORY_FILE_NAME = "window.history"


def capture_window_state(title_matcher: Callable[[str], bool], screens_list: list[dict]) -> dict | None:
    """Find a top-level window matching ``title_matcher`` and describe it.

    Returns a dict with the matched screen's device name, the window's
    position/size, and whether it looks fullscreen (its rect covers the
    whole monitor), or ``None`` if no matching window is found.
    """
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    found_hwnd = None

    def _enum_callback(hwnd, lparam):
        nonlocal found_hwnd
        if not user32.IsWindowVisible(hwnd):
            return 1
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return 1
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        if title_matcher(buffer.value):
            found_hwnd = hwnd
            return 0
        return 1

    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumWindows(enum_proc(_enum_callback), 0)

    if found_hwnd is None:
        return None

    rect = wintypes.RECT()
    user32.GetWindowRect(found_hwnd, ctypes.byref(rect))
    x, y = rect.left, rect.top
    width, height = rect.right - rect.left, rect.bottom - rect.top

    MONITOR_DEFAULTTONEAREST = 2

    class _MonitorInfoExW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
            ("szDevice", wintypes.WCHAR * 32),
        ]

    hmonitor = user32.MonitorFromWindow(found_hwnd, MONITOR_DEFAULTTONEAREST)
    info = _MonitorInfoExW()
    info.cbSize = ctypes.sizeof(_MonitorInfoExW)
    device = None
    fullscreen = False
    if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
        device = info.szDevice
        monitor_rect = info.rcMonitor
        fullscreen = (
            x <= monitor_rect.left
            and y <= monitor_rect.top
            and (x + width) >= monitor_rect.right
            and (y + height) >= monitor_rect.bottom
        )

    return {
        "device": device,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "fullscreen": fullscreen,
    }


def poll_and_record_window(
    project_dir: pathlib.Path,
    title_matcher: Callable[[str], bool],
    get_screens=None,
    capture=capture_window_state,
) -> pathlib.Path:
    """Capture current screens + a matching window's state, updating
    ``screens.json`` if the monitor layout changed and appending a record
    to ``window.history``.
    """
    if get_screens is None:
        get_screens = screens.get_screen_info

    current_screens = screens.assign_priorities(get_screens())

    config_dir = project_dir / screens.CONFIG_DIR_NAME
    screens_path = config_dir / screens.SCREENS_FILE_NAME
    previous_screens = None
    if screens_path.exists():
        try:
            previous_screens = json.loads(screens_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous_screens = None

    if previous_screens != current_screens:
        screens.save_screen_config(project_dir, screens=current_screens)

    window_state = capture(title_matcher, current_screens)

    history_path = config_dir / WINDOW_HISTORY_FILE_NAME
    config_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "window": window_state,
    }
    with history_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    logger.info("Recorded window state to %s", history_path)
    return history_path
