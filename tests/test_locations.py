import pytest

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


def test_resolve_missing_locations_ignores_keys_outside_location_keys(tmp_path):
    """A caller (setup_proj) may pass a combined missing list that also
    covers unrelated checklist items, e.g. the Steam account - those must
    never reach the folder picker."""
    env_path = tmp_path / ".env"
    prompted = []

    changed = locations.resolve_missing_locations(
        env_path,
        ["USER_STEAM_LOC_INT", locations.STEAM_KEY],
        prompt_for_missing=lambda key, current: prompted.append(key),
    )

    assert prompted == [locations.STEAM_KEY]
    assert changed is False  # the lambda above returns None, so nothing was chosen


def _write_all_found(tmp_path, env_path):
    for key in locations.LOCATION_KEYS:
        folder = tmp_path / key.lower()
        folder.mkdir(exist_ok=True)
        env_file.update_env_value(env_path, key, str(folder))


def test_verify_locations_shows_one_combined_checklist_when_nothing_missing(tmp_path, monkeypatch):
    """All items should render as a single screen (one ui.checklist call
    covering every key) rather than a separate clearing screen per item."""
    env_path = tmp_path / ".env"
    _write_all_found(tmp_path, env_path)

    checklist_calls = []
    real_checklist = locations.ui.checklist

    def spy_checklist(title, items, check, delay=0.5):
        checklist_calls.append((title, [key for key, _label in items]))
        return real_checklist(title, items, check, delay=delay)

    monkeypatch.setattr(locations.ui, "checklist", spy_checklist)

    locations.verify_locations(env_path, delay=0)

    assert checklist_calls == [(locations._CHECKLIST_TITLE, locations.LOCATION_KEYS)]


def test_verify_locations_redraws_checklist_after_picker_resolution(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_file.update_env_value(env_path, locations.STEAM_KEY, str(tmp_path / "missing"))
    for key in locations.LOCATION_KEYS[1:]:
        folder = tmp_path / key.lower()
        folder.mkdir()
        env_file.update_env_value(env_path, key, str(folder))

    found = tmp_path / "found"
    found.mkdir()

    checklist_calls = []
    real_checklist = locations.ui.checklist

    def spy_checklist(title, items, check, delay=0.5):
        checklist_calls.append((title, delay))
        return real_checklist(title, items, check, delay=0)

    monkeypatch.setattr(locations.ui, "checklist", spy_checklist)

    locations.verify_locations(
        env_path,
        prompt_for_missing=lambda key, current: str(found),
        verify_steam=lambda path: True,
        delay=0.5,
    )

    # Shown once (with the caller's real delay) for the missing item, then
    # redrawn once more after the picker resolves it - that redraw should
    # populate prefilled (delay=0), not replay the reveal animation.
    assert checklist_calls == [
        (locations._CHECKLIST_TITLE, 0.5),
        (locations._CHECKLIST_TITLE, 0),
    ]


def test_verify_locations_skips_existing_paths(tmp_path):
    env_path = tmp_path / ".env"
    _write_all_found(tmp_path, env_path)

    calls = []
    locations.verify_locations(
        env_path,
        prompt_for_missing=lambda key, current: calls.append(key),
        delay=0,
    )

    assert calls == []


def test_steam_step_opens_picker_and_verifies_launch_when_missing(tmp_path):
    env_path = tmp_path / ".env"
    env_file.update_env_value(env_path, locations.STEAM_KEY, str(tmp_path / "missing"))
    for key in locations.LOCATION_KEYS[1:]:
        folder = tmp_path / key.lower()
        folder.mkdir()
        env_file.update_env_value(env_path, key, str(folder))

    found = tmp_path / "found"
    found.mkdir()
    verify_calls = []

    locations.verify_locations(
        env_path,
        prompt_for_missing=lambda key, current: str(found) if key == locations.STEAM_KEY else None,
        verify_steam=lambda path: verify_calls.append(path) or True,
        delay=0,
    )

    assert env_file.get_env_values(env_path)[locations.STEAM_KEY] == str(found)
    assert verify_calls == [str(found)]


def test_steam_step_leaves_env_unchanged_when_declined(tmp_path):
    env_path = tmp_path / ".env"
    missing = str(tmp_path / "missing")
    env_file.update_env_value(env_path, locations.STEAM_KEY, missing)
    for key in locations.LOCATION_KEYS[1:]:
        folder = tmp_path / key.lower()
        folder.mkdir()
        env_file.update_env_value(env_path, key, str(folder))

    locations.verify_locations(env_path, prompt_for_missing=lambda key, current: None, delay=0)

    assert env_file.get_env_values(env_path)[locations.STEAM_KEY] == missing


def test_halo_mcc_step_opens_picker_without_verifying_launch(tmp_path):
    env_path = tmp_path / ".env"
    steam_loc = tmp_path / "steam"
    steam_loc.mkdir()
    env_file.update_env_value(env_path, locations.STEAM_KEY, str(steam_loc))
    env_file.update_env_value(env_path, locations.HALO_MCC_KEY, str(tmp_path / "missing"))
    for key in locations.LOCATION_KEYS[2:]:
        folder = tmp_path / key.lower()
        folder.mkdir()
        env_file.update_env_value(env_path, key, str(folder))

    found = tmp_path / "mcc_found"
    found.mkdir()
    verify_calls = []

    locations.verify_locations(
        env_path,
        prompt_for_missing=lambda key, current: str(found) if key == locations.HALO_MCC_KEY else None,
        verify_steam=lambda path: verify_calls.append(path) or True,
        delay=0,
    )

    assert env_file.get_env_values(env_path)[locations.HALO_MCC_KEY] == str(found)
    assert verify_calls == []


@pytest.mark.parametrize(
    "key", [locations.REACH_KEY, locations.HOTRELOAD_KEY, locations.STANDARD_VARIANTS_KEY, locations.HOPPER_VARIANTS_KEY]
)
def test_fatal_steps_exit_when_missing(tmp_path, key):
    env_path = tmp_path / ".env"
    for k in locations.LOCATION_KEYS:
        if k == key:
            env_file.update_env_value(env_path, k, str(tmp_path / "missing"))
        else:
            folder = tmp_path / k.lower()
            folder.mkdir()
            env_file.update_env_value(env_path, k, str(folder))

    with pytest.raises(SystemExit):
        locations.verify_locations(
            env_path, prompt_for_missing=lambda key, current: None, delay=0
        )


def test_reach_step_rechecked_against_updated_halo_mcc_location(tmp_path):
    """Reach's path is derived from Halo: MCC via ${} interpolation, so a
    fix to Halo: MCC in this same run must be reflected in Reach's check."""
    env_path = tmp_path / ".env"

    steam_loc = tmp_path / "steam"
    steam_loc.mkdir()
    env_file.update_env_value(env_path, locations.STEAM_KEY, str(steam_loc))
    env_file.update_env_value(env_path, locations.HALO_MCC_KEY, str(tmp_path / "missing_mcc"))

    real_mcc = tmp_path / "real_mcc"
    (real_mcc / "haloreach").mkdir(parents=True)
    env_file.update_env_value(env_path, locations.REACH_KEY, "${HALO_MCC_INSTALL_LOC}\\haloreach")

    for key in (locations.HOTRELOAD_KEY, locations.STANDARD_VARIANTS_KEY, locations.HOPPER_VARIANTS_KEY):
        folder = tmp_path / key.lower()
        folder.mkdir()
        env_file.update_env_value(env_path, key, str(folder))

    locations.verify_locations(
        env_path,
        prompt_for_missing=lambda key, current: str(real_mcc) if key == locations.HALO_MCC_KEY else None,
        verify_steam=lambda path: True,
        delay=0,
    )

    assert env_file.get_env_values(env_path)[locations.HALO_MCC_KEY] == str(real_mcc)
