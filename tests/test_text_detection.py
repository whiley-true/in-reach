import cv2
import numpy as np

from inreach.app.setup import text_detection


def _menu_list_image(items, width=400, height=400):
    """A synthetic BGR image with real text/texture (not flat color -
    Canny edge detection needs real contrast/edges to find anything, and
    Tesseract needs real texture, same lesson as screen_grab's tests).
    """
    image = np.random.randint(0, 30, (height, width, 3), dtype=np.uint8)
    y = 30
    for item in items:
        cv2.putText(image, item, (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (230, 230, 230), 2, cv2.LINE_AA)
        y += 40
    return image


def test_find_text_blocks_locates_each_line():
    image = _menu_list_image(["MULTIPLAYER", "CAMPAIGNS"])

    boxes = text_detection.find_text_blocks(image)

    assert len(boxes) >= 2
    for x, y, w, h in boxes:
        assert w >= text_detection.MIN_BLOCK_WIDTH
        assert h >= text_detection.MIN_BLOCK_HEIGHT


def test_find_text_blocks_caps_at_max_blocks_per_poll(monkeypatch):
    monkeypatch.setattr(text_detection, "MAX_BLOCKS_PER_POLL", 1)
    image = _menu_list_image(["MULTIPLAYER", "CAMPAIGNS", "FIREFIGHT"])

    boxes = text_detection.find_text_blocks(image)

    assert len(boxes) == 1


def test_average_frames_of_identical_frames_matches_the_original():
    image = _menu_list_image(["MULTIPLAYER"])

    averaged = text_detection.average_frames([image, image, image])

    assert np.array_equal(averaged, image)


def test_average_frames_keeps_a_static_region_unchanged_under_a_moving_background():
    base = _menu_list_image(["MULTIPLAYER"])
    frame1 = base.copy()
    frame2 = base.copy()
    frame3 = base.copy()
    # A "moving" background element in an unrelated part of the frame.
    cv2.rectangle(frame1, (300, 300), (350, 350), (200, 200, 200), -1)
    cv2.rectangle(frame2, (320, 300), (370, 350), (200, 200, 200), -1)
    cv2.rectangle(frame3, (340, 300), (390, 350), (200, 200, 200), -1)

    averaged = text_detection.average_frames([frame1, frame2, frame3])

    # The static text region (top-left) is untouched by the moving
    # element elsewhere in the frame.
    assert np.array_equal(averaged[0:60, 0:200], base[0:60, 0:200])


def test_capture_window_returns_none_for_a_degenerate_rect():
    result = text_detection.capture_window(1, get_window_rect=lambda hwnd: (0, 0, 0, 0))
    assert result is None


def test_capture_window_crops_to_the_requested_width_fraction():
    calls = []

    def fake_capture(bbox):
        calls.append(bbox)
        return np.zeros((10, 10, 3), dtype=np.uint8)

    text_detection.capture_window(
        1, width_fraction=1 / 3, get_window_rect=lambda hwnd: (100, 50, 900, 600), capture=fake_capture
    )

    assert calls == [(100, 50, 100 + round(900 / 3), 50 + 600)]


def test_read_text_blocks_returns_none_when_capture_fails(monkeypatch):
    monkeypatch.setattr(text_detection, "capture_window", lambda hwnd, width_fraction: None)

    result = text_detection.read_text_blocks(1, sleep=lambda s: None)

    assert result is None


def test_read_text_blocks_returns_none_when_frames_change_shape(monkeypatch):
    # SUBFRAME_COUNT frames get captured regardless (the shape check only
    # happens after all of them are collected), so this needs one fake
    # frame per capture call, not just two distinct shapes.
    frames = iter(
        [np.zeros((100, 200, 3), dtype=np.uint8)] + [np.zeros((90, 180, 3), dtype=np.uint8)] * (text_detection.SUBFRAME_COUNT - 1)
    )
    monkeypatch.setattr(text_detection, "capture_window", lambda hwnd, width_fraction: next(frames))

    result = text_detection.read_text_blocks(1, sleep=lambda s: None)

    assert result is None


def test_read_text_blocks_end_to_end_recognizes_real_text(monkeypatch):
    image = _menu_list_image(["MULTIPLAYER", "CAMPAIGNS"])
    monkeypatch.setattr(text_detection, "capture_window", lambda hwnd, width_fraction: image)

    texts = text_detection.read_text_blocks(1, sleep=lambda s: None)

    assert texts is not None
    combined = " ".join(texts).upper()
    assert "MULTIPLAYER" in combined
    assert "CAMPAIGNS" in combined


def test_is_main_menu_visible_true_when_all_items_present(monkeypatch):
    monkeypatch.setattr(
        text_detection,
        "read_text_blocks",
        lambda hwnd, width_fraction: list(text_detection.MAIN_MENU_ITEMS),
    )

    assert text_detection.is_main_menu_visible(1) is True


def test_is_main_menu_visible_false_when_an_item_is_missing(monkeypatch):
    monkeypatch.setattr(
        text_detection,
        "read_text_blocks",
        lambda hwnd, width_fraction: list(text_detection.MAIN_MENU_ITEMS[:-1]),
    )

    assert text_detection.is_main_menu_visible(1) is False


def test_is_main_menu_visible_false_when_read_text_blocks_returns_none(monkeypatch):
    monkeypatch.setattr(text_detection, "read_text_blocks", lambda hwnd, width_fraction: None)

    assert text_detection.is_main_menu_visible(1) is False


def test_is_main_menu_visible_uses_the_left_region_fraction(monkeypatch):
    fractions = []
    monkeypatch.setattr(
        text_detection,
        "read_text_blocks",
        lambda hwnd, width_fraction: fractions.append(width_fraction) or list(text_detection.MAIN_MENU_ITEMS),
    )

    text_detection.is_main_menu_visible(1)

    assert fractions == [text_detection.LEFT_REGION_WIDTH_FRACTION]
