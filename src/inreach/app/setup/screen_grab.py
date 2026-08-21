"""Screen capture, image-anchor template matching, and mouse/keyboard
input primitives.

Every function takes its screenshot/OpenCV/input-library dependency as a
keyword argument with a real default, same pattern as
``processes.py``/``steam.py``, so tests can inject fakes without ever
taking a real screenshot or moving the mouse.

Buttons are found by template matching an anchor PNG (see
``gametype_bootstrap.py``'s ``anchors/save-game-type`` images) against
the live screen, not OCR - simpler and, per live testing, more reliable
for locating a specific known button. Matching tries several scale
factors (see ``locate_template``) since the game can render at a
different window size than whatever the anchor was captured at.

Mouse/keyboard input goes through ``pydirectinput`` rather than
``pyautogui``: clicks worked fine via either, but arrow-key navigation
never registered with MCC via plain ``pyautogui`` (confirmed live -
matches this project's very first exploration, which found MCC's menu
navigation unreliable via synthetic keyboard events in general).
``pydirectinput`` sends input via ``SendInput`` with hardware scan codes
rather than ``pyautogui``'s ``keybd_event``-based calls, which is the
standard fix for DirectInput-style games that poll physical key state
directly and don't reliably see less realistic synthetic input. Its API
is otherwise a drop-in match for ``pyautogui``'s (same ``click``/
``press``/``keyDown``/``keyUp``/``write`` signatures).
"""

import pathlib
import time

import cv2
import numpy as np
import pydirectinput
from PIL import ImageGrab

Box = tuple[int, int, int, int]  # left, top, right, bottom - absolute screen pixels

DEFAULT_CONFIDENCE = 0.8
# Tried in this order for every match attempt; not tunable per-call since
# no caller so far has needed a different range.
DEFAULT_SCALE_FACTORS: tuple[float, ...] = (0.8, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.2)


def capture_image(bbox: Box | None = None, grab=ImageGrab.grab) -> np.ndarray:
    """Screenshot ``bbox`` (or the whole screen) as a BGR array (OpenCV's
    native channel order)."""
    image = grab(bbox=bbox) if bbox is not None else grab()
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def load_template(path: pathlib.Path, imread=cv2.imread) -> np.ndarray:
    """Load an anchor PNG from disk as a BGR array."""
    image = imread(str(path))
    if image is None:
        raise FileNotFoundError(f"Could not load anchor image: {path}")
    return image


def locate_template(
    screen: np.ndarray,
    template: np.ndarray,
    confidence: float = DEFAULT_CONFIDENCE,
    scale_factors: tuple[float, ...] = DEFAULT_SCALE_FACTORS,
) -> Box | None:
    """Find ``template`` within ``screen`` (both BGR arrays), trying each
    of ``scale_factors`` to tolerate the game rendering ``template`` at a
    different size than it was captured at.

    Returns the best-scoring match's ``(left, top, right, bottom)`` in
    ``screen``-local pixel coordinates, or ``None`` if nothing scored at
    least ``confidence``. Note: ``TM_CCOEFF_NORMED`` (the matching method
    used) degenerates for a near-flat/textureless template - confirmed
    live before relying on this, matching only works reliably for
    templates with real texture/content (text, gradients, borders), which
    every actual button anchor has.
    """
    screen_gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
    template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

    best_score = -1.0
    best_box: Box | None = None
    for scale in scale_factors:
        width = max(1, round(template_gray.shape[1] * scale))
        height = max(1, round(template_gray.shape[0] * scale))
        if width > screen_gray.shape[1] or height > screen_gray.shape[0]:
            continue
        resized = cv2.resize(template_gray, (width, height), interpolation=cv2.INTER_AREA)
        result = cv2.matchTemplate(screen_gray, resized, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val > best_score:
            best_score = max_val
            best_box = (max_loc[0], max_loc[1], max_loc[0] + width, max_loc[1] + height)

    if best_score < confidence:
        return None
    return best_box


def wait_for_anchor(
    bbox: Box,
    template: np.ndarray,
    timeout: float,
    poll_interval: float = 0.2,
    confidence: float = DEFAULT_CONFIDENCE,
    capture=capture_image,
    locate=locate_template,
    sleep=time.sleep,
) -> Box | None:
    """Poll ``bbox`` (absolute screen coordinates) until ``template`` (an
    already-loaded image - see ``load_template``) is found, or ``timeout``
    elapses.

    Returns the match's box, translated into absolute screen coordinates
    (``bbox``'s own origin plus the local match position), or ``None`` on
    timeout.
    """
    left, top, _, _ = bbox
    # Real wall-clock time, not a naive elapsed += poll_interval count -
    # capturing a full-window screenshot and multi-scale-matching it
    # against DEFAULT_SCALE_FACTORS both take real, non-negligible time,
    # so a fixed per-iteration increment badly under-counts how long this
    # has actually been running (confirmed live: a nominal 5s timeout
    # measured at ~23s wall-clock before giving up).
    start = time.monotonic()
    while time.monotonic() - start <= timeout:
        screen = capture(bbox)
        match = locate(screen, template, confidence)
        if match is not None:
            match_left, match_top, match_right, match_bottom = match
            return (left + match_left, top + match_top, left + match_right, top + match_bottom)
        sleep(poll_interval)
    return None


def center_of(box: Box) -> tuple[int, int]:
    left, top, right, bottom = box
    return (left + right) // 2, (top + bottom) // 2


def click(x: int, y: int, click_fn=pydirectinput.click) -> None:
    click_fn(x, y)


def press_key(key: str, press_fn=pydirectinput.press) -> None:
    press_fn(key)


DEFAULT_KEY_HOLD_SECONDS = 0.2


def press_key_held(
    key: str,
    hold_seconds: float = DEFAULT_KEY_HOLD_SECONDS,
    key_down=pydirectinput.keyDown,
    key_up=pydirectinput.keyUp,
    sleep=time.sleep,
) -> None:
    """Hold ``key`` down for ``hold_seconds`` before releasing, rather
    than an instantaneous tap (``press_key``).

    Some games poll physical key state directly for continuous-
    navigation keys (arrow keys) rather than reacting to a keydown/keyup
    event pair, and a synthetic tap can be too brief for that polling to
    ever sample it as "down" - confirmed live: plain ``press_key("down")``
    wasn't registering during menu navigation, even though clicks were
    working fine. Holding it for a short, real duration is the standard
    mitigation for this.
    """
    key_down(key)
    sleep(hold_seconds)
    key_up(key)


def write_text(text: str, write_fn=pydirectinput.write) -> None:
    write_fn(text)
