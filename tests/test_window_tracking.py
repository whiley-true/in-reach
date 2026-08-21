import json

from inreach.app.setup import screens, window_tracking

SCREENS = [
    {"device": "\\\\.\\DISPLAY1", "x": 0, "y": 0, "width": 2560, "height": 1440, "primary": True},
    {"device": "\\\\.\\DISPLAY2", "x": -1920, "y": 0, "width": 1920, "height": 1080, "primary": False},
]


def _fake_capture(title_matcher, screens_list):
    return {"device": screens_list[0]["device"], "x": 0, "y": 0, "width": 100, "height": 100, "fullscreen": False}


def test_poll_and_record_window_writes_screens_and_history(tmp_path):
    history_path = window_tracking.poll_and_record_window(
        tmp_path, lambda title: True, get_screens=lambda: SCREENS, capture=_fake_capture
    )

    assert history_path == tmp_path / "config" / "window.history"
    lines = history_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["window"]["device"] == "\\\\.\\DISPLAY1"
    assert "timestamp" in entry

    screens_data = json.loads((tmp_path / "config" / "screens.json").read_text(encoding="utf-8"))
    assert screens_data[0]["priority"] == 1
    assert screens_data[1]["priority"] == 2


def test_poll_and_record_window_skips_rewrite_when_unchanged(tmp_path, monkeypatch):
    window_tracking.poll_and_record_window(
        tmp_path, lambda title: True, get_screens=lambda: SCREENS, capture=_fake_capture
    )

    calls = []
    monkeypatch.setattr(
        window_tracking.screens, "save_screen_config", lambda project_dir, screens=None: calls.append(project_dir)
    )

    window_tracking.poll_and_record_window(
        tmp_path, lambda title: True, get_screens=lambda: SCREENS, capture=_fake_capture
    )

    assert calls == []

    history_lines = (tmp_path / "config" / "window.history").read_text(encoding="utf-8").splitlines()
    assert len(history_lines) == 2


def test_poll_and_record_window_rewrites_when_screens_changed(tmp_path, monkeypatch):
    window_tracking.poll_and_record_window(
        tmp_path, lambda title: True, get_screens=lambda: SCREENS, capture=_fake_capture
    )

    calls = []
    monkeypatch.setattr(
        window_tracking.screens, "save_screen_config", lambda project_dir, screens=None: calls.append(project_dir)
    )

    changed_screens = SCREENS + [
        {"device": "\\\\.\\DISPLAY3", "x": -1080, "y": 0, "width": 1080, "height": 1920, "primary": False}
    ]
    window_tracking.poll_and_record_window(
        tmp_path, lambda title: True, get_screens=lambda: changed_screens, capture=_fake_capture
    )

    assert calls == [tmp_path]


def test_poll_and_record_window_handles_no_matching_window(tmp_path):
    history_path = window_tracking.poll_and_record_window(
        tmp_path, lambda title: True, get_screens=lambda: SCREENS, capture=lambda matcher, screens_list: None
    )

    entry = json.loads(history_path.read_text(encoding="utf-8").splitlines()[0])
    assert entry["window"] is None


def test_screens_assign_priorities_primary_gets_one():
    result = screens.assign_priorities(SCREENS)

    assert result[0]["priority"] == 1
    assert result[1]["priority"] == 2


def test_screens_guess_target_screen_returns_primary():
    prioritized = screens.assign_priorities(SCREENS)

    assert screens.guess_target_screen(prioritized)["device"] == "\\\\.\\DISPLAY1"
