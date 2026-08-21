import cv2
import numpy as np
import pytest

from inreach.app.setup import screen_grab


def _textured_button(width=100, height=25, text="OK", noise_low=0, noise_high=50):
    """A synthetic BGR button image with real texture (random noisy
    background + drawn text), not a flat color - TM_CCOEFF_NORMED (the
    matching method locate_template uses) degenerates for a near-flat/
    textureless template, confirmed live before relying on this, so a
    flat synthetic button would give a meaningless test.
    """
    image = np.random.randint(noise_low, noise_high, (height, width, 3), dtype=np.uint8)
    cv2.rectangle(image, (2, 2), (width - 2, height - 2), (180, 180, 180), -1)
    cv2.putText(image, text, (8, height - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (20, 20, 20), 2, cv2.LINE_AA)
    return image


def _screen_with_button(button, x=60, y=40, screen_w=300, screen_h=200):
    screen = np.random.randint(0, 40, (screen_h, screen_w, 3), dtype=np.uint8)
    h, w = button.shape[:2]
    screen[y : y + h, x : x + w] = button
    return screen, (x, y, x + w, y + h)


def test_locate_template_finds_an_exact_match():
    button = _textured_button()
    screen, box = _screen_with_button(button)

    found = screen_grab.locate_template(screen, button)

    assert found == box


def test_locate_template_tolerates_a_larger_scale():
    button = _textured_button()
    screen, box = _screen_with_button(button)
    # Simulate the anchor having been captured at a smaller window size
    # than the game is currently rendering at.
    scaled_up = cv2.resize(button, (round(button.shape[1] * 1.15), round(button.shape[0] * 1.15)))

    found = screen_grab.locate_template(screen, scaled_up)

    assert found is not None
    assert abs(found[0] - box[0]) <= 3
    assert abs(found[1] - box[1]) <= 3


def test_locate_template_returns_none_when_nothing_matches():
    button = _textured_button(text="OK")
    screen, _ = _screen_with_button(button)
    unrelated = _textured_button(text="SAVE AS", width=140, height=25)

    found = screen_grab.locate_template(screen, unrelated)

    assert found is None


def test_load_template_raises_for_a_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        screen_grab.load_template(tmp_path / "does-not-exist.png")


def test_load_template_returns_real_image_data(tmp_path):
    button = _textured_button()
    path = tmp_path / "button.png"
    cv2.imwrite(str(path), button)

    loaded = screen_grab.load_template(path)

    assert loaded.shape == button.shape


def test_capture_image_crops_to_bbox_via_injected_grab():
    calls = []

    def fake_grab(bbox=None):
        calls.append(bbox)
        from PIL import Image

        return Image.new("RGB", (10, 10))

    result = screen_grab.capture_image((1, 2, 3, 4), grab=fake_grab)

    assert calls == [(1, 2, 3, 4)]
    assert result.shape == (10, 10, 3)


def test_wait_for_anchor_returns_absolute_coordinates_of_match():
    def fake_capture(bbox):
        return "screen"

    def fake_locate(screen, template, confidence):
        return (10, 20, 30, 40)  # local match, relative to bbox's origin

    result = screen_grab.wait_for_anchor(
        (100, 200, 500, 600), template="tpl", timeout=1.0, capture=fake_capture, locate=fake_locate, sleep=lambda s: None
    )

    assert result == (110, 220, 130, 240)


def test_wait_for_anchor_returns_none_on_timeout():
    sleeps = []

    result = screen_grab.wait_for_anchor(
        (0, 0, 100, 100),
        template="tpl",
        timeout=0.3,
        poll_interval=0.1,
        capture=lambda bbox: "screen",
        locate=lambda screen, template, confidence: None,
        sleep=sleeps.append,
    )

    assert result is None
    assert len(sleeps) >= 2


def test_center_of_returns_the_midpoint():
    assert screen_grab.center_of((10, 20, 30, 60)) == (20, 40)


def test_click_forwards_to_the_injected_click_fn():
    calls = []
    screen_grab.click(5, 6, click_fn=lambda x, y: calls.append((x, y)))
    assert calls == [(5, 6)]


def test_press_key_forwards_to_the_injected_press_fn():
    calls = []
    screen_grab.press_key("enter", press_fn=calls.append)
    assert calls == ["enter"]


def test_write_text_forwards_to_the_injected_write_fn():
    calls = []
    screen_grab.write_text("temporary", write_fn=calls.append)
    assert calls == ["temporary"]


def test_press_key_held_holds_the_key_for_the_requested_duration():
    calls = []

    screen_grab.press_key_held(
        "down",
        hold_seconds=0.25,
        key_down=lambda key: calls.append(("down", key)),
        key_up=lambda key: calls.append(("up", key)),
        sleep=lambda s: calls.append(("sleep", s)),
    )

    assert calls == [("down", "down"), ("sleep", 0.25), ("up", "down")]


def test_press_key_held_uses_the_default_hold_duration():
    calls = []

    screen_grab.press_key_held(
        "down",
        key_down=lambda key: None,
        key_up=lambda key: None,
        sleep=calls.append,
    )

    assert calls == [screen_grab.DEFAULT_KEY_HOLD_SECONDS]
