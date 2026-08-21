from inreach.app.setup import gametype_bootstrap, screen_grab

WINDOW_RECT = (0, 0, 1920, 1080)


def _loc_1_with_file(tmp_path):
    """A PERSONAL_VARIANTS_LOC_1-style folder that already has a file
    sitting in <subfolder>/HaloReach/GameType, so create_temporary_
    gametype's post-save file poll (_wait_for_gametype_file) succeeds on
    its first check without any real sleep."""
    loc_1 = tmp_path / "personal"
    gametype_dir = loc_1 / "some_user_id" / gametype_bootstrap.GAMETYPE_SUBPATH
    gametype_dir.mkdir(parents=True)
    (gametype_dir / "existing.bin").write_bytes(b"x")
    return loc_1


def _base_kwargs(loc_1, **overrides):
    kwargs = dict(
        personal_variants_loc_1=loc_1,
        find_window=lambda matcher: 1,
        get_window_rect=lambda hwnd: WINDOW_RECT,
        get_foreground_window=lambda: 1,
        bring_to_foreground=lambda hwnd, cycle_minimize=False: None,
        wait_for_stable_size=lambda hwnd, timeout, min_fraction_of_monitor=None: True,
        is_process_running=lambda name: False,
        close_process=lambda name: None,
        launch=lambda: None,
        wait_for_process=lambda name, timeout: True,
        click=lambda x, y: None,
        press_key=lambda key: None,
        write_text=lambda text: None,
        wait_for_anchor=lambda bbox, template, timeout, poll_interval=0.2: (10, 10, 90, 40),
        load_template=lambda path: f"template:{path.name}",
        is_main_menu_visible=lambda hwnd: True,
        sleep=lambda s: None,
    )
    kwargs.update(overrides)
    return kwargs


def test_reuses_an_already_running_mcc_instead_of_relaunching(tmp_path, monkeypatch):
    # mcc_launch.run_eac_launch_step already has MCC open (it launches it
    # itself, to verify the EAC-disabled launch works) by the time this
    # runs - relaunching here would be a wasteful second launch.
    launch_calls = []
    close_calls = []
    result = gametype_bootstrap.create_temporary_gametype(
        **_base_kwargs(
            _loc_1_with_file(tmp_path),
            is_process_running=lambda name: True,
            launch=lambda: launch_calls.append(1),
            close_process=lambda name: close_calls.append(name),
        )
    )

    assert result is True
    assert launch_calls == []
    # Still closed at the end, regardless of who started it.
    assert close_calls == [gametype_bootstrap.MCC_PROCESS_NAME]


def test_launches_mcc_when_not_already_running(tmp_path, monkeypatch):
    launch_calls = []
    result = gametype_bootstrap.create_temporary_gametype(
        **_base_kwargs(
            _loc_1_with_file(tmp_path),
            is_process_running=lambda name: False,
            launch=lambda: launch_calls.append(1),
        )
    )

    assert result is True
    assert launch_calls == [1]


def test_returns_false_when_launch_times_out(tmp_path, monkeypatch):
    messages = []
    monkeypatch.setattr(gametype_bootstrap.ui, "error", messages.append)

    result = gametype_bootstrap.create_temporary_gametype(
        **_base_kwargs(_loc_1_with_file(tmp_path), wait_for_process=lambda name, timeout: False)
    )

    assert result is False
    assert any("did not start" in m.lower() for m in messages)


def test_returns_false_when_window_never_appears(tmp_path, monkeypatch):
    monkeypatch.setattr(gametype_bootstrap, "LAUNCH_TIMEOUT_SECONDS", 0.5)
    messages = []
    monkeypatch.setattr(gametype_bootstrap.ui, "error", messages.append)

    result = gametype_bootstrap.create_temporary_gametype(
        **_base_kwargs(_loc_1_with_file(tmp_path), find_window=lambda matcher: None)
    )

    assert result is False
    assert any("never appeared" in m.lower() for m in messages)


def test_returns_false_when_window_never_settles(tmp_path, monkeypatch):
    monkeypatch.setattr(gametype_bootstrap, "WINDOW_SETTLE_TIMEOUT_SECONDS", 0.5)
    monkeypatch.setattr(gametype_bootstrap, "WINDOW_SIZE_CHECK_SECONDS", 0.5)
    messages = []
    monkeypatch.setattr(gametype_bootstrap.ui, "error", messages.append)

    result = gametype_bootstrap.create_temporary_gametype(
        **_base_kwargs(
            _loc_1_with_file(tmp_path),
            wait_for_stable_size=lambda hwnd, timeout, min_fraction_of_monitor=None: False,
        )
    )

    assert result is False
    assert any("never appeared/settled" in m.lower() for m in messages)


def test_adopts_a_different_hwnd_that_appears_while_settling(tmp_path, monkeypatch):
    monkeypatch.setattr(gametype_bootstrap, "WINDOW_SIZE_CHECK_SECONDS", 1.0)
    # find_window is re-checked at the top of every settle-loop attempt,
    # so hwnd=1 has to persist across a couple of calls (the initial find
    # plus one settle attempt) before "changing" to hwnd=2.
    find_calls = [1, 1, 2]
    settle_calls = []

    def fake_find_window(matcher):
        return find_calls.pop(0) if find_calls else 2

    def fake_wait_for_stable_size(hwnd, timeout, min_fraction_of_monitor=None):
        settle_calls.append(hwnd)
        return hwnd == 2

    foreground_calls = []
    result = gametype_bootstrap.create_temporary_gametype(
        **_base_kwargs(
            _loc_1_with_file(tmp_path),
            find_window=fake_find_window,
            wait_for_stable_size=fake_wait_for_stable_size,
            get_foreground_window=lambda: 2,  # matches the adopted hwnd - already focused, no reclaim needed
            bring_to_foreground=lambda hwnd, cycle_minimize=False: foreground_calls.append(hwnd),
        )
    )

    assert result is True
    assert settle_calls == [1, 2]
    # Only the one unconditional bring_to_foreground right after settling
    # - _ensure_focus sees hwnd=2 already matches get_foreground_window
    # and doesn't reclaim again for any of the later key presses/clicks.
    assert foreground_calls == [2]


def test_click_through_intro_waits_then_clicks_window_center_repeatedly(monkeypatch):
    monkeypatch.setattr(gametype_bootstrap, "CLICK_LOOP_TIMEOUT_SECONDS", 6.0)
    monkeypatch.setattr(gametype_bootstrap, "CLICK_INTERVAL_SECONDS", 3.0)
    clicks = []
    sleeps = []

    result = gametype_bootstrap._click_through_intro(
        1, lambda hwnd: WINDOW_RECT, lambda x, y: clicks.append((x, y)), sleeps.append, lambda hwnd: False
    )

    center = (WINDOW_RECT[0] + WINDOW_RECT[2] // 2, WINDOW_RECT[1] + WINDOW_RECT[3] // 2)
    # Main menu never detected, so it uses the full budget: initial wait,
    # then click/wait pairs for the 6s loop (2 iterations of 3s), then
    # one final click.
    assert result is False
    assert clicks == [center, center, center]
    assert sleeps == [
        gametype_bootstrap.INITIAL_WAIT_SECONDS,
        gametype_bootstrap.CLICK_INTERVAL_SECONDS,
        gametype_bootstrap.CLICK_INTERVAL_SECONDS,
    ]


def test_click_through_intro_stops_as_soon_as_main_menu_is_detected(monkeypatch):
    monkeypatch.setattr(gametype_bootstrap, "CLICK_LOOP_TIMEOUT_SECONDS", 120.0)
    monkeypatch.setattr(gametype_bootstrap, "CLICK_INTERVAL_SECONDS", 3.0)
    clicks = []
    sleeps = []
    # Not visible on the first click, visible on the second - previously
    # this had no way to know Main Menu had loaded and would keep
    # clicking for the whole 120s budget regardless.
    visibility = [False, True]

    result = gametype_bootstrap._click_through_intro(
        1,
        lambda hwnd: WINDOW_RECT,
        lambda x, y: clicks.append((x, y)),
        sleeps.append,
        lambda hwnd: visibility.pop(0),
    )

    assert result is True
    center = (WINDOW_RECT[0] + WINDOW_RECT[2] // 2, WINDOW_RECT[1] + WINDOW_RECT[3] // 2)
    assert clicks == [center, center]
    assert sleeps == [gametype_bootstrap.INITIAL_WAIT_SECONDS, gametype_bootstrap.CLICK_INTERVAL_SECONDS]


def test_send_key_sequence_presses_expected_keys_with_delay():
    presses = []
    sleeps = []

    gametype_bootstrap._send_key_sequence(
        1,
        get_foreground_window=lambda: 1,
        bring_to_foreground=lambda hwnd, cycle_minimize=False: None,
        press_key=presses.append,
        sleep=sleeps.append,
    )

    assert presses == list(gametype_bootstrap.KEY_SEQUENCE)
    assert sleeps == [gametype_bootstrap.KEY_DELAY_SECONDS] * len(gametype_bootstrap.KEY_SEQUENCE)


def test_send_key_sequence_reclaims_focus_before_a_press_when_not_foreground():
    foreground_calls = []
    presses = []
    sleeps = []

    gametype_bootstrap._send_key_sequence(
        1,
        get_foreground_window=lambda: 999,  # something else is foreground
        bring_to_foreground=lambda hwnd, cycle_minimize=False: foreground_calls.append((hwnd, cycle_minimize)),
        press_key=presses.append,
        sleep=sleeps.append,
    )

    assert presses == list(gametype_bootstrap.KEY_SEQUENCE)
    # Reclaimed once per key, always with the disruptive cycle - matches
    # the dev.py-validated pattern for input that isn't registering.
    assert foreground_calls == [(1, True)] * len(gametype_bootstrap.KEY_SEQUENCE)
    # One settle-sleep per reclaim, plus one KEY_DELAY_SECONDS sleep per
    # key (they happen to share the same value, so this checks the total
    # count rather than filtering by it).
    assert len(sleeps) == 2 * len(gametype_bootstrap.KEY_SEQUENCE)


def test_save_flow_waits_for_description_ok_anchor_before_pressing_enter():
    events = []

    window_rect = (0, 0, 1920, 1080)
    window = gametype_bootstrap._save_temporary_gametype(
        hwnd=1,
        get_window_rect=lambda hwnd: window_rect,
        get_foreground_window=lambda: 1,
        bring_to_foreground=lambda hwnd, cycle_minimize=False: None,
        wait_for_anchor=lambda bbox, template, timeout, poll_interval=0.2: (10, 10, 90, 40),
        load_template=lambda path: f"template:{path.name}",
        click=lambda x, y: events.append(("click", x, y)),
        write_text=lambda text: events.append(("write", text)),
        press_key=lambda key: events.append(("key", key)),
        sleep=lambda s: events.append(("sleep", s)),
    )

    assert window is True
    # Only the name is ever typed - once NAME_OK_ANCHOR confirms the
    # description dialog is up, DESCRIPTION_OK_ANCHOR (visually the same
    # OK button, just captured on that menu instead) is waited for as the
    # checkpoint that it's actually ready, replacing a blind fixed sleep -
    # then confirmed blank with Enter, never clicked.
    assert [event for event in events if event[0] == "write"] == [("write", gametype_bootstrap.GAME_TYPE_NAME)]
    assert [event for event in events if event[0] == "key"] == [("key", "enter"), ("key", "enter")]
    # The final action is the second Enter, confirming the blank
    # description, not a click.
    assert events[-1] == ("key", "enter")


def test_full_flow_succeeds_and_saves_expected_name_and_description(tmp_path, monkeypatch):
    monkeypatch.setattr(gametype_bootstrap, "CLICK_LOOP_TIMEOUT_SECONDS", 0.0)
    calls = []

    result = gametype_bootstrap.create_temporary_gametype(
        **_base_kwargs(
            _loc_1_with_file(tmp_path),
            click=lambda x, y: calls.append(("click", x, y)),
            press_key=lambda key: calls.append(("key", key)),
            write_text=lambda text: calls.append(("write", text)),
            close_process=lambda name: calls.append(("close", name)),
            load_template=lambda path: calls.append(("load", path.name)) or f"template:{path.name}",
        )
    )

    assert result is True
    loaded = [item[1] for item in calls if item[0] == "load"]
    # File Options, Save As, the name-prompt OK checkpoint, and the
    # description-prompt OK checkpoint - the last two are only ever
    # waited on, never clicked.
    assert loaded == ["1_file_options.png", "2_save_as.png", "3_ok.png", "4_ok.png"]
    written = [item[1] for item in calls if item[0] == "write"]
    # Only the name is typed - nothing is typed into the description field.
    assert written == [gametype_bootstrap.GAME_TYPE_NAME]
    keys = [item[1] for item in calls if item[0] == "key"]
    # Two "enter"s: after the name, and after the (blank) description.
    assert keys == [*gametype_bootstrap.KEY_SEQUENCE, "enter", "enter"]
    clicks = [item for item in calls if item[0] == "click"]
    # One window-center click from the (immediately-exhausted, per the
    # 0.0s timeout) intro click loop's final click, then File Options and
    # Save As - both at the fake wait_for_anchor's fixed (10, 10, 90, 40)
    # box, so its center. Nothing is ever clicked for the description
    # prompt - it's confirmed with Enter.
    window_center = (WINDOW_RECT[0] + WINDOW_RECT[2] // 2, WINDOW_RECT[1] + WINDOW_RECT[3] // 2)
    anchor_center = screen_grab.center_of((10, 10, 90, 40))
    assert clicks == [("click", *window_center)] + [("click", *anchor_center)] * 2
    assert ("close", gametype_bootstrap.MCC_PROCESS_NAME) in calls


def test_closes_mcc_only_after_a_gametype_file_appears(tmp_path, monkeypatch):
    # MCC shouldn't be closed the instant the UI flow reports success -
    # only once a real file has actually shown up under
    # personal_variants_loc_1, confirming the save genuinely completed.
    monkeypatch.setattr(gametype_bootstrap, "CLICK_LOOP_TIMEOUT_SECONDS", 0.0)
    monkeypatch.setattr(gametype_bootstrap, "GAMETYPE_FILE_POLL_INTERVAL_SECONDS", 0.0)
    loc_1 = tmp_path / "personal"
    loc_1.mkdir()
    events = []

    def fake_sleep(seconds):
        events.append(("sleep", seconds))
        if seconds == gametype_bootstrap.GAMETYPE_FILE_POLL_INTERVAL_SECONDS:
            # The file only appears after the first poll tick - close
            # shouldn't have happened yet at this point.
            assert ("close", gametype_bootstrap.MCC_PROCESS_NAME) not in events
            gametype_dir = loc_1 / "some_user_id" / gametype_bootstrap.GAMETYPE_SUBPATH
            gametype_dir.mkdir(parents=True)
            (gametype_dir / "saved.bin").write_bytes(b"x")

    result = gametype_bootstrap.create_temporary_gametype(
        **_base_kwargs(
            loc_1,
            close_process=lambda name: events.append(("close", name)),
            sleep=fake_sleep,
        )
    )

    assert result is True
    assert ("close", gametype_bootstrap.MCC_PROCESS_NAME) in events
    # The close only happens after the file-appearance sleep/check, not
    # before.
    close_index = events.index(("close", gametype_bootstrap.MCC_PROCESS_NAME))
    sleep_index = events.index(("sleep", gametype_bootstrap.GAMETYPE_FILE_POLL_INTERVAL_SECONDS))
    assert sleep_index < close_index


def test_ignores_a_file_outside_the_haloreach_gametype_folder(tmp_path, monkeypatch):
    # A stray file directly under personal_variants_loc_1 (not nested in
    # <subfolder>/HaloReach/GameType) shouldn't satisfy the poll - only a
    # file in the actual gametype folder structure Reach creates counts.
    monkeypatch.setattr(gametype_bootstrap, "CLICK_LOOP_TIMEOUT_SECONDS", 0.0)
    monkeypatch.setattr(gametype_bootstrap, "GAMETYPE_FILE_POLL_TIMEOUT_SECONDS", 0.0)
    monkeypatch.setattr(gametype_bootstrap, "GAMETYPE_FILE_POLL_INTERVAL_SECONDS", 0.0)
    messages = []
    monkeypatch.setattr(gametype_bootstrap.ui, "error", messages.append)
    loc_1 = tmp_path / "personal"
    loc_1.mkdir()
    (loc_1 / "unrelated.bin").write_bytes(b"x")

    result = gametype_bootstrap.create_temporary_gametype(**_base_kwargs(loc_1))

    assert result is False
    assert any("no gametype file" in m.lower() for m in messages)


def test_returns_false_when_no_gametype_file_ever_appears(tmp_path, monkeypatch):
    monkeypatch.setattr(gametype_bootstrap, "CLICK_LOOP_TIMEOUT_SECONDS", 0.0)
    monkeypatch.setattr(gametype_bootstrap, "GAMETYPE_FILE_POLL_TIMEOUT_SECONDS", 0.0)
    monkeypatch.setattr(gametype_bootstrap, "GAMETYPE_FILE_POLL_INTERVAL_SECONDS", 0.0)
    messages = []
    monkeypatch.setattr(gametype_bootstrap.ui, "error", messages.append)
    loc_1 = tmp_path / "personal"
    loc_1.mkdir()
    close_calls = []

    result = gametype_bootstrap.create_temporary_gametype(
        **_base_kwargs(loc_1, close_process=lambda name: close_calls.append(name))
    )

    assert result is False
    assert any("no gametype file" in m.lower() for m in messages)
    # MCC is still closed even though no file ever appeared.
    assert close_calls == [gametype_bootstrap.MCC_PROCESS_NAME]


def test_returns_false_when_main_menu_never_reached(tmp_path, monkeypatch):
    monkeypatch.setattr(gametype_bootstrap, "CLICK_LOOP_TIMEOUT_SECONDS", 0.0)
    messages = []
    monkeypatch.setattr(gametype_bootstrap.ui, "error", messages.append)
    close_calls = []
    key_calls = []

    result = gametype_bootstrap.create_temporary_gametype(
        **_base_kwargs(
            _loc_1_with_file(tmp_path),
            is_main_menu_visible=lambda hwnd: False,
            close_process=lambda name: close_calls.append(name),
            press_key=lambda key: key_calls.append(key),
        )
    )

    assert result is False
    assert any("main menu" in m.lower() for m in messages)
    # MCC is still closed, and the key sequence/save flow never ran since
    # we never actually reached the main menu to navigate from.
    assert close_calls == [gametype_bootstrap.MCC_PROCESS_NAME]
    assert key_calls == []


def test_returns_false_when_file_options_anchor_not_found(tmp_path, monkeypatch):
    messages = []
    monkeypatch.setattr(gametype_bootstrap.ui, "error", messages.append)
    close_calls = []

    result = gametype_bootstrap.create_temporary_gametype(
        **_base_kwargs(
            _loc_1_with_file(tmp_path),
            wait_for_anchor=lambda bbox, template, timeout, poll_interval=0.2: None,
            close_process=lambda name: close_calls.append(name),
        )
    )

    assert result is False
    assert any("file options" in m.lower() for m in messages)
    # MCC is still closed even though the save failed.
    assert close_calls == [gametype_bootstrap.MCC_PROCESS_NAME]


def test_returns_false_when_save_as_anchor_not_found(tmp_path, monkeypatch):
    messages = []
    monkeypatch.setattr(gametype_bootstrap.ui, "error", messages.append)

    def fake_wait_for_anchor(bbox, template, timeout, poll_interval=0.2):
        return None if "save_as" in str(template) else (10, 10, 90, 40)

    result = gametype_bootstrap.create_temporary_gametype(
        **_base_kwargs(_loc_1_with_file(tmp_path), wait_for_anchor=fake_wait_for_anchor)
    )

    assert result is False
    assert any("save as" in m.lower() for m in messages)


def test_returns_false_when_name_prompt_never_confirms(tmp_path, monkeypatch):
    messages = []
    monkeypatch.setattr(gametype_bootstrap.ui, "error", messages.append)
    call_count = [0]

    def fake_wait_for_anchor(bbox, template, timeout, poll_interval=0.2):
        call_count[0] += 1
        # Succeeds for file_options (1st) and save_as (2nd), fails for
        # the name-prompt OK anchor (3rd).
        return None if call_count[0] == 3 else (10, 10, 90, 40)

    result = gametype_bootstrap.create_temporary_gametype(
        **_base_kwargs(_loc_1_with_file(tmp_path), wait_for_anchor=fake_wait_for_anchor)
    )

    assert result is False
    assert any("name prompt" in m.lower() for m in messages)


def test_returns_false_when_description_prompt_never_confirms(tmp_path, monkeypatch):
    messages = []
    monkeypatch.setattr(gametype_bootstrap.ui, "error", messages.append)
    call_count = [0]

    def fake_wait_for_anchor(bbox, template, timeout, poll_interval=0.2):
        call_count[0] += 1
        # Succeeds for file_options (1st), save_as (2nd), and the
        # name-prompt OK anchor (3rd); fails for the description-prompt OK
        # anchor (4th).
        return None if call_count[0] == 4 else (10, 10, 90, 40)

    result = gametype_bootstrap.create_temporary_gametype(
        **_base_kwargs(_loc_1_with_file(tmp_path), wait_for_anchor=fake_wait_for_anchor)
    )

    assert result is False
    assert any("description prompt" in m.lower() for m in messages)
