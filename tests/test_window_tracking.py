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


def test_find_window_returns_none_when_no_title_matches():
    assert window_tracking.find_window(lambda title: False) is None


def test_find_window_returns_hwnd_of_first_visible_match(monkeypatch):
    titles = {1: "Skip", 2: "Match Me", 3: "Match Me Too"}
    visibles = {1: False, 2: True, 3: True}

    def fake_enum_windows(callback, extra):
        for hwnd in (1, 2, 3):
            callback(hwnd, extra)

    monkeypatch.setattr(window_tracking.win32gui, "EnumWindows", fake_enum_windows)
    monkeypatch.setattr(window_tracking.win32gui, "IsWindowVisible", lambda hwnd: visibles[hwnd])
    monkeypatch.setattr(window_tracking.win32gui, "GetWindowText", lambda hwnd: titles[hwnd])

    result = window_tracking.find_window(lambda t: "Match" in t)

    assert result == 2


def test_get_window_rect_returns_a_four_tuple_for_a_bogus_handle():
    # GetWindowRect raises for an invalid handle - this checks the
    # wrapper swallows that and still returns a well-shaped result.
    assert window_tracking.get_window_rect(0) == (0, 0, 0, 0)


def test_get_window_title_returns_empty_string_for_a_bogus_handle():
    assert window_tracking.get_window_title(0) == ""


def test_get_foreground_window_returns_an_int():
    assert isinstance(window_tracking.get_foreground_window(), int)


def test_bring_to_foreground_does_not_raise_for_a_bogus_handle():
    # SetForegroundWindow/SetWindowPos both raise pywintypes.error for an
    # invalid handle - this checks the wrapper swallows that instead of
    # propagating it.
    window_tracking.bring_to_foreground(0)


def test_bring_to_foreground_restores_when_minimized_and_pulses_topmost(monkeypatch):
    calls = []
    monkeypatch.setattr(window_tracking.win32gui, "IsIconic", lambda hwnd: True)
    monkeypatch.setattr(
        window_tracking.win32gui, "ShowWindow", lambda hwnd, flag: calls.append(("show", hwnd, flag))
    )
    monkeypatch.setattr(window_tracking.win32api, "keybd_event", lambda *args: calls.append(("key", args)))
    monkeypatch.setattr(window_tracking.win32gui, "SetForegroundWindow", lambda hwnd: calls.append(("fg", hwnd)))
    monkeypatch.setattr(window_tracking.win32gui, "SetWindowPos", lambda *args: calls.append(("pos", args)))

    window_tracking.bring_to_foreground(42)

    assert ("show", 42, window_tracking.win32con.SW_RESTORE) in calls
    assert ("fg", 42) in calls
    key_calls = [entry[1] for entry in calls if entry[0] == "key"]
    assert key_calls == [
        (window_tracking.win32con.VK_MENU, 0, 0, 0),
        (window_tracking.win32con.VK_MENU, 0, window_tracking.win32con.KEYEVENTF_KEYUP, 0),
    ]
    pos_calls = [entry[1] for entry in calls if entry[0] == "pos"]
    assert len(pos_calls) == 2
    assert pos_calls[0][1] == window_tracking.win32con.HWND_TOPMOST
    assert pos_calls[1][1] == window_tracking.win32con.HWND_NOTOPMOST


def test_bring_to_foreground_skips_restore_when_not_minimized(monkeypatch):
    show_calls = []
    monkeypatch.setattr(window_tracking.win32gui, "IsIconic", lambda hwnd: False)
    monkeypatch.setattr(
        window_tracking.win32gui, "ShowWindow", lambda hwnd, flag: show_calls.append((hwnd, flag))
    )
    monkeypatch.setattr(window_tracking.win32api, "keybd_event", lambda *args: None)
    monkeypatch.setattr(window_tracking.win32gui, "SetForegroundWindow", lambda hwnd: None)
    monkeypatch.setattr(window_tracking.win32gui, "SetWindowPos", lambda *args: None)

    window_tracking.bring_to_foreground(42)

    assert show_calls == []


def test_bring_to_foreground_cycle_minimize_forces_minimize_then_restore(monkeypatch):
    show_calls = []
    monkeypatch.setattr(window_tracking.win32gui, "IsIconic", lambda hwnd: False)
    monkeypatch.setattr(window_tracking.win32gui, "ShowWindow", lambda hwnd, flag: show_calls.append(flag))
    monkeypatch.setattr(window_tracking.win32api, "keybd_event", lambda *args: None)
    monkeypatch.setattr(window_tracking.win32gui, "SetForegroundWindow", lambda hwnd: None)
    monkeypatch.setattr(window_tracking.win32gui, "SetWindowPos", lambda *args: None)

    window_tracking.bring_to_foreground(42, cycle_minimize=True)

    assert show_calls == [window_tracking.win32con.SW_MINIMIZE, window_tracking.win32con.SW_RESTORE]


def test_bring_to_foreground_cycle_minimize_skips_redundant_minimize_when_already_iconic(monkeypatch):
    show_calls = []
    monkeypatch.setattr(window_tracking.win32gui, "IsIconic", lambda hwnd: True)
    monkeypatch.setattr(window_tracking.win32gui, "ShowWindow", lambda hwnd, flag: show_calls.append(flag))
    monkeypatch.setattr(window_tracking.win32api, "keybd_event", lambda *args: None)
    monkeypatch.setattr(window_tracking.win32gui, "SetForegroundWindow", lambda hwnd: None)
    monkeypatch.setattr(window_tracking.win32gui, "SetWindowPos", lambda *args: None)

    window_tracking.bring_to_foreground(42, cycle_minimize=True)

    assert show_calls == [window_tracking.win32con.SW_RESTORE]


def test_get_monitor_size_returns_width_and_height():
    width, height = window_tracking.get_monitor_size(0)
    assert isinstance(width, int) and isinstance(height, int)


def test_wait_for_stable_size_returns_true_once_size_repeats(monkeypatch):
    sizes = [(200, 100), (800, 450), (800, 450), (1920, 1080), (1920, 1080)]
    sizes_iter = iter(sizes)
    sleeps = []

    result = window_tracking.wait_for_stable_size(
        1,
        timeout=10.0,
        poll_interval=0.5,
        min_confirmations=2,
        get_window_rect=lambda hwnd: (0, 0, *next(sizes_iter)),
        sleep=sleeps.append,
    )

    assert result is True
    # Stops as soon as (800, 450) repeats - never needs to see (1920, 1080).
    assert sleeps == [0.5, 0.5]


def test_wait_for_stable_size_ignores_a_transient_size_below_the_monitor_fraction(monkeypatch):
    # The 800x450 decoy window found during earlier live testing holding
    # steady across two polls shouldn't count as "settled" once a minimum
    # fraction of the monitor is required.
    sizes = [(800, 450), (800, 450), (1920, 1080), (1920, 1080)]
    sizes_iter = iter(sizes)

    result = window_tracking.wait_for_stable_size(
        1,
        timeout=10.0,
        poll_interval=0.0,
        min_confirmations=2,
        min_fraction_of_monitor=0.5,
        get_window_rect=lambda hwnd: (0, 0, *next(sizes_iter)),
        get_monitor_size=lambda hwnd: (1920, 1080),
        sleep=lambda s: None,
    )

    assert result is True
    assert next(sizes_iter, None) is None  # consumed exactly the 4 sizes above


def test_wait_for_stable_size_returns_false_on_timeout():
    # A size that keeps changing every single poll never reaches
    # min_confirmations consecutive equal readings, so this should never
    # settle no matter how long timeout allows polling.
    call_count = [0]

    def ever_changing_rect(hwnd):
        call_count[0] += 1
        return (0, 0, 800 + call_count[0], 450)

    result = window_tracking.wait_for_stable_size(
        1,
        timeout=1.0,
        poll_interval=0.3,
        get_window_rect=ever_changing_rect,
        sleep=lambda s: None,
    )

    assert result is False


def test_minimize_other_windows_skips_target_invisible_minimized_and_untitled(monkeypatch):
    windows = {
        1: {"visible": True, "iconic": False, "title": "Keep Me"},
        2: {"visible": True, "iconic": False, "title": "Other App"},
        3: {"visible": False, "iconic": False, "title": "Hidden"},
        4: {"visible": True, "iconic": True, "title": "Already Minimized"},
        5: {"visible": True, "iconic": False, "title": ""},
    }

    def fake_enum_windows(callback, extra):
        for hwnd in windows:
            callback(hwnd, extra)

    monkeypatch.setattr(window_tracking.win32gui, "EnumWindows", fake_enum_windows)
    monkeypatch.setattr(window_tracking.win32gui, "IsWindowVisible", lambda hwnd: windows[hwnd]["visible"])
    monkeypatch.setattr(window_tracking.win32gui, "IsIconic", lambda hwnd: windows[hwnd]["iconic"])
    monkeypatch.setattr(window_tracking.win32gui, "GetWindowText", lambda hwnd: windows[hwnd]["title"])
    minimized = []
    monkeypatch.setattr(window_tracking.win32gui, "ShowWindow", lambda hwnd, flag: minimized.append((hwnd, flag)))

    window_tracking.minimize_other_windows(keep_hwnds=1)

    assert minimized == [(2, window_tracking.win32con.SW_MINIMIZE)]


def test_minimize_other_windows_accepts_multiple_hwnds_to_keep(monkeypatch):
    windows = {
        1: {"visible": True, "iconic": False, "title": "Keep Me"},
        2: {"visible": True, "iconic": False, "title": "Also Keep Me"},
        3: {"visible": True, "iconic": False, "title": "Minimize Me"},
    }

    def fake_enum_windows(callback, extra):
        for hwnd in windows:
            callback(hwnd, extra)

    monkeypatch.setattr(window_tracking.win32gui, "EnumWindows", fake_enum_windows)
    monkeypatch.setattr(window_tracking.win32gui, "IsWindowVisible", lambda hwnd: windows[hwnd]["visible"])
    monkeypatch.setattr(window_tracking.win32gui, "IsIconic", lambda hwnd: windows[hwnd]["iconic"])
    monkeypatch.setattr(window_tracking.win32gui, "GetWindowText", lambda hwnd: windows[hwnd]["title"])
    minimized = []
    monkeypatch.setattr(window_tracking.win32gui, "ShowWindow", lambda hwnd, flag: minimized.append(hwnd))

    window_tracking.minimize_other_windows(keep_hwnds={1, 2})

    assert minimized == [3]


def test_focus_exclusively_brings_to_foreground_then_minimizes_others(monkeypatch):
    calls = []
    monkeypatch.setattr(window_tracking, "bring_to_foreground", lambda hwnd: calls.append(("fg", hwnd)))
    monkeypatch.setattr(window_tracking, "minimize_other_windows", lambda keep_hwnds: calls.append(("min", keep_hwnds)))

    window_tracking.focus_exclusively(7)

    assert calls == [("fg", 7), ("min", {7})]


def test_focus_exclusively_forwards_also_keep_to_minimize_other_windows(monkeypatch):
    calls = []
    monkeypatch.setattr(window_tracking, "bring_to_foreground", lambda hwnd: None)
    monkeypatch.setattr(window_tracking, "minimize_other_windows", lambda keep_hwnds: calls.append(keep_hwnds))

    window_tracking.focus_exclusively(7, also_keep=(8, 9))

    assert calls == [{7, 8, 9}]


def test_capture_window_state_returns_none_when_no_match():
    assert window_tracking.capture_window_state(lambda title: False, []) is None


def test_capture_window_state_finds_real_window_and_reports_well_shaped_result():
    # Exercises the real win32api.MonitorFromWindow/GetMonitorInfo path
    # against whatever window currently has focus - only checking the
    # returned dict's shape, not any particular window's title.
    hwnd = window_tracking.get_foreground_window()
    title = window_tracking.get_window_title(hwnd)

    result = window_tracking.capture_window_state(lambda t: t == title, [])

    assert result is not None
    assert set(result) == {"device", "x", "y", "width", "height", "fullscreen"}
    assert isinstance(result["fullscreen"], bool)
