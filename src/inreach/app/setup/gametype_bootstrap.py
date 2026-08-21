"""Drives the live Halo: Reach/MCC UI to save a throwaway custom gametype.

Reach only creates the per-account personal-variants folder once a
custom gametype has been saved through its own UI - see
``personal_variants.resolve_personal_variants``, which calls this. This
module is the one-shot flow that gets a fresh install to that point.

Reuses an already-running MCC instance if there is one (``mcc_launch.
run_eac_launch_step`` launches MCC and calls this - via ``personal_
variants.resolve_personal_variants`` - while it's still open, precisely
so this doesn't need a second relaunch), otherwise launches a fresh one.
Either way, waits for its window to settle at a real (not transient
launcher/mini-title) size, clicks through the intro/sign-in until OCR
confirms Main Menu has actually loaded (see ``text_detection.py`` -
there's no fixed button/graphic to anchor "we've reached the main menu"
on, only its list of nav items as text), then keys/clicks its way to the
Custom Game Lobby and saves a "temporary" gametype via the File Options
-> Save As flow. Those buttons are found by image template matching
against ``anchors/save-game-type/*.png`` (see ``screen_grab.py``) rather
than OCR, since they're fixed, known graphics OCR isn't needed for. MCC
is only closed once a gametype file has actually appeared under the
caller-supplied ``personal_variants_loc_1`` (or that wait times out) - a
real filesystem signal rather than trusting the UI flow alone. Every
other dependency is injectable with a real default (same style as
``mcc_launch.py``), so the whole flow is fake-able in tests without ever
taking a screenshot, moving the mouse, or touching a real process.
"""

import logging
import pathlib
import time

from inreach.app import ui
from inreach.app.setup import processes, screen_grab, steam, text_detection, window_tracking

logger = logging.getLogger(__name__)

MCC_PROCESS_NAME = "MCC-Win64-Shipping.exe"

ANCHORS_DIR = pathlib.Path(__file__).resolve().parent.parent / "anchors" / "save-game-type"
FILE_OPTIONS_ANCHOR = ANCHORS_DIR / "1_file_options.png"
SAVE_AS_ANCHOR = ANCHORS_DIR / "2_save_as.png"
NAME_OK_ANCHOR = ANCHORS_DIR / "3_ok.png"
# Visually the same OK button as NAME_OK_ANCHOR - just captured on the
# description menu instead of the name menu.
DESCRIPTION_OK_ANCHOR = ANCHORS_DIR / "4_ok.png"

GAME_TYPE_NAME = "temporary"

LAUNCH_TIMEOUT_SECONDS = 60.0

# MCC's window typically passes through several sizes on the way up (a
# small standalone launcher, then a brief "mini title" frame) before
# settling at its real size, and can swap to a different hwnd along the
# way - WINDOW_SETTLE_TIMEOUT_SECONDS is the overall budget for that,
# WINDOW_SIZE_CHECK_SECONDS how long each individual settle-check attempt
# gets, and WINDOW_SIZE_MIN_MONITOR_FRACTION how large a fraction of its
# monitor's width/height the settled size has to be (comfortably above
# the ~40% a known small decoy window measured at).
WINDOW_SETTLE_TIMEOUT_SECONDS = 30.0
WINDOW_SIZE_CHECK_SECONDS = 3.0
WINDOW_SIZE_MIN_MONITOR_FRACTION = 0.5

# Wait, then click the window center every few seconds to skip through
# the intro cutscene and sign-in screen, checking after each click
# whether Main Menu has actually loaded (text_detection.
# is_main_menu_visible - clicking blindly with no way to detect Main
# Menu meant this never stopped clicking even once there, confirmed
# live). CLICK_LOOP_TIMEOUT_SECONDS is the overall budget before giving
# up.
INITIAL_WAIT_SECONDS = 3.0
CLICK_INTERVAL_SECONDS = 3.0
CLICK_LOOP_TIMEOUT_SECONDS = 120.0

# Main Menu -> Multiplayer -> Custom Multiplayer -> Halo: Reach -> (lobby)
# Game Type tile, all via keyboard rather than mouse clicks/text search:
# Down (Campaigns -> Multiplayer), Enter (select), Down, Down (Social
# Games -> Competitive Games -> Custom Multiplayer), Enter (select),
# Enter (Custom Multiplayer's default-highlighted item, Halo: Reach),
# Right (the lobby's Map tile, default-highlighted, -> Game Type tile).
KEY_SEQUENCE: tuple[str, ...] = ("down", "enter", "down", "down", "enter", "enter", "right")
KEY_DELAY_SECONDS = 1

ANCHOR_POLL_INTERVAL_SECONDS = 0.2
ANCHOR_TIMEOUT_SECONDS = 5.0
POST_SAVE_AS_WAIT_SECONDS = 1.0

# The per-user personal-variants folder (and its gametype file) doesn't
# exist until Reach actually finishes writing the save - a far more
# reliable "did the save actually complete" signal than any further
# on-screen anchor, so MCC is only closed once a file has appeared in the
# local HaloReach\GameType folder under PERSONAL_VARIANTS_LOC_1 (its exact
# per-user subfolder isn't known in advance, hence the glob). Owned here
# rather than in personal_variants.py (which imports this module and
# reuses this same constant) since it's this module's own save-completion
# check that needs it.
GAMETYPE_SUBPATH = pathlib.Path("HaloReach") / "GameType"
GAMETYPE_FILE_POLL_INTERVAL_SECONDS = 1.0
GAMETYPE_FILE_POLL_TIMEOUT_SECONDS = 30.0

# How long to wait after reclaiming focus (cycle_minimize=True triggers
# an OS-level minimize/restore animation and focus handoff, neither of
# which is instantaneous) before actually sending input - sending
# immediately risks it arriving before the window was really ready to
# receive it.
FOREGROUND_SETTLE_SECONDS = 0.5


def _is_mcc_title(title: str) -> bool:
    return "Halo" in title and "Master Chief" in title


def _find_settled_window(
    find_window,
    get_window_rect,
    wait_for_stable_size,
    sleep,
) -> int | None:
    """Find MCC's window and wait for it to settle at its real size,
    re-checking for a different hwnd (the transient-window-swap case)
    each settle attempt. Returns the settled hwnd, or ``None`` if MCC's
    window never appeared or never settled within budget.
    """
    hwnd = None
    elapsed = 0.0
    while elapsed <= LAUNCH_TIMEOUT_SECONDS:
        hwnd = find_window(_is_mcc_title)
        if hwnd is not None:
            break
        sleep(1.0)
        elapsed += 1.0
    if hwnd is None:
        logger.info("MCC's window never appeared within %ss.", LAUNCH_TIMEOUT_SECONDS)
        return None
    logger.info("MCC window found: hwnd=%s - waiting for it to settle at its full size...", hwnd)

    settle_elapsed = 0.0
    while settle_elapsed <= WINDOW_SETTLE_TIMEOUT_SECONDS:
        candidate = find_window(_is_mcc_title)
        if candidate is not None and candidate != hwnd:
            logger.info("MCC's window changed: hwnd=%s -> hwnd=%s", hwnd, candidate)
            hwnd = candidate
        if wait_for_stable_size(
            hwnd,
            timeout=WINDOW_SIZE_CHECK_SECONDS,
            min_fraction_of_monitor=WINDOW_SIZE_MIN_MONITOR_FRACTION,
        ):
            return hwnd
        settle_elapsed += WINDOW_SIZE_CHECK_SECONDS
    logger.info("MCC's window (hwnd=%s) never settled within %ss.", hwnd, WINDOW_SETTLE_TIMEOUT_SECONDS)
    return None


def _click_through_intro(hwnd, get_window_rect, click, sleep, is_main_menu_visible) -> bool:
    """Click the window center every ``CLICK_INTERVAL_SECONDS`` to skip
    through the intro cutscene and sign-in screen, checking after each
    click whether Main Menu has loaded. Stops as soon as it has, rather
    than continuing to click on an already-loaded main menu for the rest
    of the budget. Returns whether Main Menu was confirmed within
    ``CLICK_LOOP_TIMEOUT_SECONDS``.
    """
    sleep(INITIAL_WAIT_SECONDS)
    x, y, width, height = get_window_rect(hwnd)
    center = (x + width // 2, y + height // 2)

    elapsed = 0.0
    while elapsed < CLICK_LOOP_TIMEOUT_SECONDS:
        click(*center)
        if is_main_menu_visible(hwnd):
            logger.info("Main menu detected after %ss of clicking.", elapsed)
            return True
        sleep(CLICK_INTERVAL_SECONDS)
        elapsed += CLICK_INTERVAL_SECONDS

    click(*center)
    found = is_main_menu_visible(hwnd)
    if not found:
        logger.info("Main menu never detected after %ss of clicking.", CLICK_LOOP_TIMEOUT_SECONDS)
    return found


def _ensure_focus(hwnd, get_foreground_window, bring_to_foreground, sleep) -> None:
    """Make sure ``hwnd`` actually has focus before sending it input.

    Logs the outcome either way - the first place to look if input still
    isn't registering. Only reclaims (the disruptive minimize/restore
    cycle) when ``hwnd`` genuinely isn't the foreground window; input was
    working fine for the mouse clicks that got this far (the click loop
    stopping on its own confirms Main Menu was reached), so this is aimed
    at focus having drifted since then, not a blanket "always reclaim"
    hammer.
    """
    current_foreground = get_foreground_window()
    if current_foreground != hwnd:
        logger.info("MCC (hwnd=%s) isn't foreground (hwnd=%s is) - reclaiming.", hwnd, current_foreground)
        bring_to_foreground(hwnd, cycle_minimize=True)
        sleep(FOREGROUND_SETTLE_SECONDS)
    else:
        logger.debug("MCC (hwnd=%s) is already foreground.", hwnd)


def _press_key_ensuring_focus(hwnd, key, get_foreground_window, bring_to_foreground, press_key, sleep) -> None:
    _ensure_focus(hwnd, get_foreground_window, bring_to_foreground, sleep)
    logger.info("Pressing %r", key)
    press_key(key)


def _send_key_sequence(hwnd, get_foreground_window, bring_to_foreground, press_key, sleep) -> None:
    logger.info("Sending key sequence: %s", KEY_SEQUENCE)
    for key in KEY_SEQUENCE:
        _press_key_ensuring_focus(hwnd, key, get_foreground_window, bring_to_foreground, press_key, sleep)
        sleep(KEY_DELAY_SECONDS)


def _has_gametype_file(personal_variants_loc_1: pathlib.Path) -> bool:
    """Whether a file has appeared in ``<loc_1>/<any subfolder>/HaloReach/
    GameType`` - the exact structure Reach creates when it saves a
    gametype - rather than just anywhere under ``personal_variants_loc_1``.
    """
    for gametype_dir in personal_variants_loc_1.glob(f"*/{GAMETYPE_SUBPATH.as_posix()}"):
        if gametype_dir.is_dir() and any(p.is_file() for p in gametype_dir.iterdir()):
            return True
    return False


def _wait_for_gametype_file(personal_variants_loc_1: pathlib.Path, sleep) -> bool:
    start = time.monotonic()
    while True:
        if _has_gametype_file(personal_variants_loc_1):
            return True
        if time.monotonic() - start >= GAMETYPE_FILE_POLL_TIMEOUT_SECONDS:
            return False
        sleep(GAMETYPE_FILE_POLL_INTERVAL_SECONDS)


def _wait_for_button(bbox, anchor_path, load_template, wait_for_anchor):
    logger.info("Waiting for %s (up to %ss)...", anchor_path.name, ANCHOR_TIMEOUT_SECONDS)
    template = load_template(anchor_path)
    box = wait_for_anchor(bbox, template, timeout=ANCHOR_TIMEOUT_SECONDS, poll_interval=ANCHOR_POLL_INTERVAL_SECONDS)
    logger.info("%s: %s", anchor_path.name, f"found at {box}" if box is not None else "not found")
    return box


def _save_temporary_gametype(
    hwnd,
    get_window_rect,
    get_foreground_window,
    bring_to_foreground,
    wait_for_anchor,
    load_template,
    click,
    write_text,
    press_key,
    sleep,
) -> bool:
    x, y, width, height = get_window_rect(hwnd)
    bbox = (x, y, x + width, y + height)

    box = _wait_for_button(bbox, FILE_OPTIONS_ANCHOR, load_template, wait_for_anchor)
    if box is None:
        ui.error("Could not find the File Options button.")
        return False
    _ensure_focus(hwnd, get_foreground_window, bring_to_foreground, sleep)
    click(*screen_grab.center_of(box))

    box = _wait_for_button(bbox, SAVE_AS_ANCHOR, load_template, wait_for_anchor)
    if box is None:
        ui.error("Could not find the Save As button.")
        return False
    _ensure_focus(hwnd, get_foreground_window, bring_to_foreground, sleep)
    click(*screen_grab.center_of(box))

    sleep(POST_SAVE_AS_WAIT_SECONDS)
    _ensure_focus(hwnd, get_foreground_window, bring_to_foreground, sleep)
    logger.info("Typing game type name: %r", GAME_TYPE_NAME)
    write_text(GAME_TYPE_NAME)
    _press_key_ensuring_focus(hwnd, "enter", get_foreground_window, bring_to_foreground, press_key, sleep)

    # NAME_OK_ANCHOR appearing means the Game Type Description prompt has
    # popped up - not something to click, just the checkpoint that the
    # name was accepted and this next field is ready.
    if _wait_for_button(bbox, NAME_OK_ANCHOR, load_template, wait_for_anchor) is None:
        ui.error("The game type name prompt did not confirm.")
        return False

    # No description is typed - DESCRIPTION_OK_ANCHOR is waited for as the
    # checkpoint that the description dialog is actually ready (replacing
    # a blind fixed sleep), but not clicked - confirmed with Enter instead,
    # leaving the field blank.
    if _wait_for_button(bbox, DESCRIPTION_OK_ANCHOR, load_template, wait_for_anchor) is None:
        ui.error("The game type description prompt did not confirm.")
        return False

    _press_key_ensuring_focus(hwnd, "enter", get_foreground_window, bring_to_foreground, press_key, sleep)
    return True


def create_temporary_gametype(
    personal_variants_loc_1: pathlib.Path,
    find_window=window_tracking.find_window,
    get_window_rect=window_tracking.get_window_rect,
    get_foreground_window=window_tracking.get_foreground_window,
    bring_to_foreground=window_tracking.bring_to_foreground,
    wait_for_stable_size=window_tracking.wait_for_stable_size,
    is_process_running=processes.is_process_running,
    close_process=processes.close_process,
    launch=steam.launch_mcc_eac_disabled,
    wait_for_process=processes.wait_for_process,
    click=screen_grab.click,
    press_key=screen_grab.press_key_held,
    write_text=screen_grab.write_text,
    wait_for_anchor=screen_grab.wait_for_anchor,
    load_template=screen_grab.load_template,
    is_main_menu_visible=text_detection.is_main_menu_visible,
    sleep=time.sleep,
) -> bool:
    """Save a "temporary" custom gametype in Halo: Reach's custom game
    lobby, reusing an already-running MCC instance if there is one.

    Returns whether the save completed; on any failure it reports via
    ``ui.error`` and returns ``False`` rather than raising. Once the UI
    flow itself reports success, MCC is only closed after a gametype file
    has actually appeared somewhere under ``personal_variants_loc_1`` (see
    ``_wait_for_gametype_file``) or that wait times out - a real
    filesystem signal is a far more reliable "did the save actually
    complete" check than trusting the UI flow alone. Logs its progress at
    each stage (``logger``, name ``inreach.app.setup.gametype_bootstrap`` -
    always written to the log file; also to the console if the project's
    ``.env`` has ``OUTPUT_TO_STREAM=true``) since this drives a live game
    UI with no other visibility into what's actually happening.
    """
    if is_process_running(MCC_PROCESS_NAME):
        logger.info("%s is already running - using it instead of relaunching.", MCC_PROCESS_NAME)
    else:
        logger.info("Launching %s...", MCC_PROCESS_NAME)
        launch()

        if not wait_for_process(MCC_PROCESS_NAME, timeout=LAUNCH_TIMEOUT_SECONDS):
            ui.error("Halo: MCC did not start within the expected time.")
            return False

    hwnd = _find_settled_window(find_window, get_window_rect, wait_for_stable_size, sleep)
    if hwnd is None:
        ui.error("Halo: MCC's window never appeared/settled at its full size.")
        return False
    logger.info("MCC window settled: hwnd=%s rect=%s", hwnd, get_window_rect(hwnd))

    bring_to_foreground(hwnd, cycle_minimize=True)

    if not _click_through_intro(hwnd, get_window_rect, click, sleep, is_main_menu_visible):
        ui.error("Halo: MCC never reached the main menu.")
        close_process(MCC_PROCESS_NAME)
        return False
    logger.info("Reached the main menu.")

    _send_key_sequence(hwnd, get_foreground_window, bring_to_foreground, press_key, sleep)

    success = _save_temporary_gametype(
        hwnd,
        get_window_rect,
        get_foreground_window,
        bring_to_foreground,
        wait_for_anchor,
        load_template,
        click,
        write_text,
        press_key,
        sleep,
    )

    if success:
        logger.info("Waiting for a gametype file to appear under %s...", personal_variants_loc_1)
        if not _wait_for_gametype_file(personal_variants_loc_1, sleep):
            ui.error("No gametype file appeared after saving.")
            success = False

    close_process(MCC_PROCESS_NAME)

    if success:
        logger.info("Saved temporary gametype %r", GAME_TYPE_NAME)
    return success
