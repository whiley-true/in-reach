"""OCR-based text-block detection - used specifically to confirm Halo:
Reach/MCC's Main Menu has loaded (see ``gametype_bootstrap._click_
through_intro``), where template matching isn't an option: there's no
fixed on-screen button/graphic to anchor "we've reached the main menu"
on, only its list of nav items as text.

OpenCV finds candidate text-block regions first (Canny edges +
morphological dilation), so Tesseract only ever runs on small, tightly-
cropped crops instead of the whole window - both far more reliable and
far cheaper than OCR-ing an entire busy, art-heavy menu screen at once.
Each crop is averaged from a few closely-spaced sub-screenshots first, to
cancel out animated background art behind the (static) menu text. All of
this - including the tuned detection constants below - carries over
unchanged from live testing done in ``scripts/dev.py`` (see
``agent/PROMPT_HISTORY.md``), ported here now that the main-menu-
detection problem it solves has come up in the real, production flow.
"""

import time

import cv2
import numpy as np
import pytesseract

from inreach.app.setup import screen_grab, window_tracking

SUBFRAME_COUNT = 3
SUBFRAME_INTERVAL_SECONDS = 0.15

# Text-block detection tuning - a busy/animated menu background can throw
# a lot of small edge fragments (mostly single characters/noise from
# blurred artwork, not real text); these were raised specifically to cut
# that down during live testing.
DILATE_KERNEL_SIZE = (25, 3)
MIN_BLOCK_WIDTH = 35
MIN_BLOCK_HEIGHT = 12
MIN_BLOCK_AREA = 600
MAX_BLOCKS_PER_POLL = 60
CANNY_LOWER_THRESHOLD = 90
CANNY_UPPER_THRESHOLD = 200

# Tesseract reads a tightly-cropped block (text touching the crop's
# edges) as empty even when the exact same text with a margin around it
# reads perfectly - confirmed live before relying on this. Padding is
# replicated from each crop's own edge pixels rather than a fixed color,
# since the background varies block to block.
BLOCK_PADDING_PX = 10

# Every top-level menu's identifying text sits in the window's left
# column - checking just this region is both faster (smaller image,
# fewer candidate blocks) and less noisy (excludes most of the busy
# background art) than scanning the whole window.
LEFT_REGION_WIDTH_FRACTION = 1 / 3

MAIN_MENU_ITEMS: tuple[str, ...] = (
    "CAMPAIGNS",
    "MULTIPLAYER",
    "CREATIVE",
    "FIREFIGHT",
    "OPTIONS & CAREER",
    "EXTRAS",
    "QUIT TO DESKTOP",
)


def capture_window(
    hwnd: int,
    width_fraction: float = 1.0,
    get_window_rect=window_tracking.get_window_rect,
    capture=screen_grab.capture_image,
) -> np.ndarray | None:
    """Screenshot the left ``width_fraction`` of ``hwnd``'s current window
    rect (the full window if 1.0) as a BGR array, or ``None`` if ``hwnd``
    isn't a valid, sized window right now (e.g. it was closed/replaced).
    """
    x, y, width, height = get_window_rect(hwnd)
    if width <= 0 or height <= 0:
        return None
    capture_width = max(1, round(width * width_fraction))
    image = capture((x, y, x + capture_width, y + height))
    if image is None or image.size == 0:
        return None
    return image


def find_text_blocks(image: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Find likely text-block regions via edge detection + morphological
    dilation, so OCR only ever runs on small crops instead of the whole
    image. Returns ``(x, y, width, height)`` boxes in ``image``-local
    pixel coordinates, largest first.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, CANNY_LOWER_THRESHOLD, CANNY_UPPER_THRESHOLD)
    # A wide, short kernel merges letters/words on the same line into one
    # blob while keeping separate lines apart.
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, DILATE_KERNEL_SIZE)
    dilated = cv2.dilate(edges, kernel, iterations=1)
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w < MIN_BLOCK_WIDTH or h < MIN_BLOCK_HEIGHT or w * h < MIN_BLOCK_AREA:
            continue
        boxes.append((x, y, w, h))

    boxes.sort(key=lambda box: box[2] * box[3], reverse=True)
    return boxes[:MAX_BLOCKS_PER_POLL]


def average_frames(frames: list[np.ndarray]) -> np.ndarray:
    """Pixel-wise average of same-sized frames.

    Menu text is static frame to frame, so averaging reinforces it
    unchanged; a moving/animated background behind it lands on different
    pixels each frame, so averaging smears it toward a flat blend. Net
    effect: better text-to-background contrast for OCR.
    """
    stacked = np.stack(frames).astype(np.float32)
    return np.mean(stacked, axis=0).astype(np.uint8)


def read_text_blocks(hwnd: int, width_fraction: float = 1.0, sleep=time.sleep) -> list[str] | None:
    """Capture ``hwnd`` (or its left ``width_fraction``), find candidate
    text-block regions, and OCR each one from an average of a few
    closely-spaced sub-screenshots.

    Returns the recognized, non-empty text of each block found, or
    ``None`` if ``hwnd`` went invalid partway through (closed, or
    replaced by a different window) or its size changed between sub-
    screenshots, since the frames can no longer be stacked/averaged
    together.
    """
    frames = [capture_window(hwnd, width_fraction)]
    for _ in range(SUBFRAME_COUNT - 1):
        sleep(SUBFRAME_INTERVAL_SECONDS)
        frames.append(capture_window(hwnd, width_fraction))

    if any(frame is None for frame in frames):
        return None
    if len({frame.shape for frame in frames}) > 1:
        return None

    boxes = find_text_blocks(frames[0])

    texts = []
    for x, y, w, h in boxes:
        crops = [frame[y : y + h, x : x + w] for frame in frames]
        averaged = average_frames(crops)
        padded = cv2.copyMakeBorder(
            averaged, BLOCK_PADDING_PX, BLOCK_PADDING_PX, BLOCK_PADDING_PX, BLOCK_PADDING_PX, cv2.BORDER_REPLICATE
        )
        text = pytesseract.image_to_string(padded).strip()
        if text:
            texts.append(text)
    return texts


def is_main_menu_visible(hwnd: int) -> bool:
    """Is Halo: Reach/MCC's Main Menu showing right now?

    Checks the window's left column (see ``LEFT_REGION_WIDTH_FRACTION``)
    for every one of ``MAIN_MENU_ITEMS``.
    """
    texts = read_text_blocks(hwnd, LEFT_REGION_WIDTH_FRACTION)
    if texts is None:
        return False
    combined = " ".join(texts).lower()
    return all(item.lower() in combined for item in MAIN_MENU_ITEMS)
