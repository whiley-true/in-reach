"""Window discovery and foreground/z-order control, plus screen-priority
guessing and window position/fullscreen capture.

Built on ``pywin32`` (``win32gui``/``win32con``/``win32api``) rather than
raw ``ctypes`` calls to the Win32 API directly - it's the standard,
well-maintained Python wrapper for this, and gives us two things a plain
``SetForegroundWindow`` call doesn't: a reliable way past Windows' own
foreground-lock restriction (see ``bring_to_foreground``), and z-order
control (``SetWindowPos``/``ShowWindow``) to push the target window above
everything else, or push everything else out of the way entirely (see
``minimize_other_windows``/``focus_exclusively``).

``poll_and_record_window`` has no permanent consumer yet (there's no
background polling loop), but is called once from the MCC EAC-disabled
launch step during setup so we start building up ``window.history``.
"""

import datetime
import json
import logging
import pathlib
from typing import Callable

import pywintypes
import win32api
import win32con
import win32gui

from inreach.app.setup import screens

logger = logging.getLogger(__name__)

WINDOW_HISTORY_FILE_NAME = "window.history"


class _StopEnumeration(Exception):
    """Raised from an ``EnumWindows`` callback to stop early.

    ``win32gui.EnumWindows`` doesn't reliably honor a falsy return from
    the callback as "stop" across pywin32 versions - raising and catching
    is the robust way to break out once a match is found.
    """


def get_window_title(hwnd: int) -> str:
    """Return ``hwnd``'s window title, or ``""`` if it has none/is invalid."""
    return win32gui.GetWindowText(hwnd)


def find_window(title_matcher: Callable[[str], bool]) -> int | None:
    """Return the hwnd of the first visible top-level window whose title
    satisfies ``title_matcher``, or ``None`` if there isn't one."""
    found_hwnd = None

    def _enum_callback(hwnd, _extra):
        nonlocal found_hwnd
        if win32gui.IsWindowVisible(hwnd) and title_matcher(get_window_title(hwnd)):
            found_hwnd = hwnd
            raise _StopEnumeration
        return True

    try:
        win32gui.EnumWindows(_enum_callback, None)
    except _StopEnumeration:
        pass
    return found_hwnd


def get_window_rect(hwnd: int) -> tuple[int, int, int, int]:
    """Return ``(x, y, width, height)`` for ``hwnd``, or all zeros if it
    can't be queried (e.g. an invalid/closed handle)."""
    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    except pywintypes.error:
        return (0, 0, 0, 0)
    return left, top, right - left, bottom - top


def get_foreground_window() -> int:
    """Return the hwnd of whichever top-level window currently has focus."""
    return win32gui.GetForegroundWindow()


def bring_to_foreground(hwnd: int) -> None:
    """Restore (if minimized) and reliably focus ``hwnd``.

    A plain ``SetForegroundWindow`` call is often silently refused by
    Windows' foreground-lock restriction (``LockSetForegroundWindow``)
    when the calling process didn't just generate real input - which a
    background automation script never does. Synthesizing a harmless Alt
    keypress right before the call satisfies that check; it's the
    standard, documented workaround. Also pulses ``hwnd`` to the very top
    of the z-order via ``HWND_TOPMOST``/``HWND_NOTOPMOST`` so it visually
    ends up above every other window immediately - not pinned there
    forever, just raised once - rather than relying on focus alone, which
    doesn't guarantee visibility if something else is still drawn on top.
    """
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

    win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
    win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
    try:
        win32gui.SetForegroundWindow(hwnd)
    except pywintypes.error:
        logger.warning("SetForegroundWindow failed for hwnd=%s", hwnd)

    swp_flags = win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
    try:
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, swp_flags)
        win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0, swp_flags)
    except pywintypes.error:
        logger.warning("SetWindowPos failed for hwnd=%s", hwnd)


def minimize_other_windows(keep_hwnd: int) -> None:
    """Minimize every other visible, titled top-level window.

    Leaves ``keep_hwnd`` as the only thing left in view - the "move
    everything else back" half of getting a window unambiguously in
    front, for when a Steam overlay/notification or some other app window
    keeps reappearing over it.
    """

    def _enum_callback(hwnd, _extra):
        if hwnd == keep_hwnd or not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
            return True
        if not get_window_title(hwnd):
            return True
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
        except pywintypes.error:
            pass
        return True

    win32gui.EnumWindows(_enum_callback, None)


def focus_exclusively(hwnd: int) -> None:
    """Bring ``hwnd`` to the foreground and minimize every other window.

    The combined operation this module was built for: make ``hwnd``
    unambiguously the thing on screen and receiving input, rather than
    just "focused" (which other windows can still visually cover or steal
    back from).
    """
    bring_to_foreground(hwnd)
    minimize_other_windows(hwnd)


def capture_window_state(title_matcher: Callable[[str], bool], screens_list: list[dict]) -> dict | None:
    """Find a top-level window matching ``title_matcher`` and describe it.

    Returns a dict with the matched screen's device name, the window's
    position/size, and whether it looks fullscreen (its rect covers the
    whole monitor), or ``None`` if no matching window is found.
    """
    found_hwnd = find_window(title_matcher)
    if found_hwnd is None:
        return None

    x, y, width, height = get_window_rect(found_hwnd)

    hmonitor = win32api.MonitorFromWindow(found_hwnd, win32con.MONITOR_DEFAULTTONEAREST)
    monitor_info = win32api.GetMonitorInfo(hmonitor)
    device = monitor_info["Device"]
    monitor_left, monitor_top, monitor_right, monitor_bottom = monitor_info["Monitor"]
    fullscreen = (
        x <= monitor_left and y <= monitor_top and (x + width) >= monitor_right and (y + height) >= monitor_bottom
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
