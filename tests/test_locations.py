from inreach.app.setup import env_file, locations


def test_ask_user_for_path_shows_hint_for_halo_mcc(monkeypatch):
    messages = []
    monkeypatch.setattr(locations.ui, "warning", messages.append)
    monkeypatch.setattr(locations.ui, "confirm", lambda prompt: False)

    result = locations.ask_user_for_path(locations.HALO_MCC_KEY, "C:\\missing")

    assert result is None
    assert any("mcclauncher.exe" in message for message in messages)


def test_verify_steam_install_launches_waits_and_closes():
    popen_calls = []
    sleep_calls = []
    close_calls = []

    ok = locations.verify_steam_install(
        "C:\\steam",
        popen=lambda args: popen_calls.append(args),
        is_process_running=lambda name: True,
        close_process=lambda name: close_calls.append(name),
        sleep=sleep_calls.append,
        wait_seconds=3,
    )

    assert ok is True
    assert popen_calls == [["C:\\steam\\steam.exe"]]
    assert sleep_calls == [3]
    assert close_calls == ["steam.exe"]


def test_check_location_found_and_missing(tmp_path):
    env_path = tmp_path / ".env"
    found = tmp_path / "steam"
    found.mkdir()
    env_file.update_env_value(env_path, locations.STEAM_KEY, str(found))

    assert locations.check_location(env_path, locations.STEAM_KEY) == str(found)
    assert locations.check_location(env_path, locations.HALO_MCC_KEY) is None


def test_resolve_missing_locations_ignores_keys_outside_location_keys(tmp_path):
    """A caller (verify.verify_installs) may pass a combined missing list
    that also covers unrelated checklist items, e.g. the Steam account -
    those must never reach the folder picker."""
    env_path = tmp_path / ".env"
    prompted = []

    changed = locations.resolve_missing_locations(
        env_path,
        ["USER_STEAM_LOC_INT", locations.STEAM_KEY],
        prompt_for_missing=lambda key, current: prompted.append(key),
    )

    assert prompted == [locations.STEAM_KEY]
    assert changed is False  # the lambda above returns None, so nothing was chosen


def test_resolve_missing_locations_skips_fatal_keys(tmp_path):
    env_path = tmp_path / ".env"
    prompted = []

    changed = locations.resolve_missing_locations(
        env_path,
        [locations.REACH_KEY, locations.HOTRELOAD_KEY],
        prompt_for_missing=lambda key, current: prompted.append(key),
    )

    assert prompted == []
    assert changed is False


def test_resolve_missing_locations_updates_env_and_verifies_steam(tmp_path):
    env_path = tmp_path / ".env"
    found = tmp_path / "found"
    found.mkdir()
    verify_calls = []

    changed = locations.resolve_missing_locations(
        env_path,
        [locations.STEAM_KEY],
        prompt_for_missing=lambda key, current: str(found),
        verify_steam=lambda path: verify_calls.append(path) or True,
    )

    assert changed is True
    assert env_file.get_env_values(env_path)[locations.STEAM_KEY] == str(found)
    assert verify_calls == [str(found)]
