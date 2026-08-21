import logging

import pytest

from inreach.app import verify
from inreach.app.setup import env_file, locations, project, steam

LOCALCONFIG_TEMPLATE = """
"UserLocalConfigStore"
{{
	"friends"
	{{
		"PersonaName"		"{persona}"
	}}
}}
"""


def _write_steam_user(userdata_dir, user_id, persona="Player"):
    config_dir = userdata_dir / user_id / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "localconfig.vdf").write_text(LOCALCONFIG_TEMPLATE.format(persona=persona), encoding="utf-8")


def _write_locations_env(tmp_path, env_path, steam_loc):
    env_file.update_env_value(env_path, locations.STEAM_KEY, str(steam_loc))
    for key in locations.LOCATION_KEYS[1:]:
        folder = tmp_path / key.lower()
        folder.mkdir()
        env_file.update_env_value(env_path, key, str(folder))


def test_find_project_dir_returns_none_when_missing(tmp_path):
    assert verify.find_project_dir(tmp_path) is None


def test_find_project_dir_returns_path_when_present(tmp_path):
    (tmp_path / project.PROJECT_DIR_NAME).mkdir()

    assert verify.find_project_dir(tmp_path) == tmp_path / project.PROJECT_DIR_NAME


def test_verify_installs_shows_one_combined_screen_and_records_persona(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    steam_loc = tmp_path / "steam"
    _write_steam_user(steam_loc / "userdata", "111", persona="Alice")
    _write_locations_env(tmp_path, env_path, steam_loc)

    checklist_calls = []
    real_checklist = verify.ui.checklist

    def spy_checklist(title, items, check, delay=0.5):
        checklist_calls.append((title, [key for key, _label in items]))
        return real_checklist(title, items, check, delay=delay)

    monkeypatch.setattr(verify.ui, "checklist", spy_checklist)

    verify.verify_installs(tmp_path, delay=0)

    expected_keys = locations.LOCATION_KEYS + [steam.USER_STEAM_LOC_INT_KEY]
    assert checklist_calls == [(verify._CHECKLIST_TITLE, expected_keys)]
    values = env_file.get_env_values(env_path)
    assert values[steam.USER_STEAM_LOC_INT_KEY] == "111"
    assert values[steam.USER_STEAM_PROFILE_NAME_KEY] == "Alice"


def test_verify_installs_redraws_once_prefilled_after_resolving_location_and_account(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    steam_loc = tmp_path / "steam"
    _write_steam_user(steam_loc / "userdata", "111", persona="Alice")
    _write_steam_user(steam_loc / "userdata", "222", persona="Bob")

    # Steam's own install location starts out missing, resolved via picker.
    _write_locations_env(tmp_path, env_path, tmp_path / "missing_steam")

    checklist_calls = []
    real_checklist = verify.ui.checklist

    def spy_checklist(title, items, check, delay=0.5):
        checklist_calls.append((title, delay))
        return real_checklist(title, items, check, delay=0)

    monkeypatch.setattr(verify.ui, "checklist", spy_checklist)

    verify.verify_installs(
        tmp_path,
        prompt_for_missing=lambda key, current: str(steam_loc),
        verify_steam=lambda path: True,
        select_user=lambda title, options: 1,
        delay=0.5,
    )

    # Shown once with the caller's real delay, then redrawn once prefilled
    # (delay=0) after resolving - never left sitting on the picker/menu.
    assert checklist_calls == [
        (verify._CHECKLIST_TITLE, 0.5),
        (verify._CHECKLIST_TITLE, 0),
    ]
    values = env_file.get_env_values(env_path)
    assert values[locations.STEAM_KEY] == str(steam_loc)
    assert values[steam.USER_STEAM_LOC_INT_KEY] == "222"
    assert values[steam.USER_STEAM_PROFILE_NAME_KEY] == "Bob"


def test_verify_installs_never_opens_folder_picker_for_steam_account(tmp_path, monkeypatch):
    """Regression: when only the Steam account item is missing (locations
    are all fine), it must be resolved via the account menu/warning path,
    never handed to the location folder picker."""
    env_path = tmp_path / ".env"
    steam_loc = tmp_path / "steam"
    steam_loc.mkdir()
    (steam_loc / "userdata").mkdir()  # no accounts under it
    _write_locations_env(tmp_path, env_path, steam_loc)

    prompted = []
    warnings = []
    monkeypatch.setattr(verify.ui, "warning", warnings.append)

    verify.verify_installs(
        tmp_path,
        prompt_for_missing=lambda key, current: prompted.append(key),
        delay=0,
    )

    assert prompted == []
    assert any("No Steam accounts found" in message for message in warnings)


def test_verify_installs_exits_on_fatal_missing_without_extra_redraw(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    steam_loc = tmp_path / "steam"
    _write_steam_user(steam_loc / "userdata", "111")
    _write_locations_env(tmp_path, env_path, steam_loc)
    env_file.update_env_value(env_path, locations.HOTRELOAD_KEY, str(tmp_path / "missing_hotreload"))

    checklist_calls = []
    real_checklist = verify.ui.checklist

    def spy_checklist(title, items, check, delay=0.5):
        checklist_calls.append(title)
        return real_checklist(title, items, check, delay=delay)

    monkeypatch.setattr(verify.ui, "checklist", spy_checklist)

    with pytest.raises(SystemExit):
        verify.verify_installs(tmp_path, delay=0)

    assert checklist_calls == [verify._CHECKLIST_TITLE]


def test_verify_installs_rechecks_reach_against_updated_halo_mcc_location(tmp_path):
    """Reach's path is derived from Halo: MCC via ${} interpolation, so a
    fix to Halo: MCC in this same run must be reflected in Reach's check."""
    env_path = tmp_path / ".env"
    steam_loc = tmp_path / "steam"
    _write_steam_user(steam_loc / "userdata", "111")
    env_file.update_env_value(env_path, locations.STEAM_KEY, str(steam_loc))
    env_file.update_env_value(env_path, locations.HALO_MCC_KEY, str(tmp_path / "missing_mcc"))

    real_mcc = tmp_path / "real_mcc"
    (real_mcc / "haloreach").mkdir(parents=True)
    env_file.update_env_value(env_path, locations.REACH_KEY, "${HALO_MCC_INSTALL_LOC}\\haloreach")

    for key in (locations.HOTRELOAD_KEY, locations.STANDARD_VARIANTS_KEY, locations.HOPPER_VARIANTS_KEY):
        folder = tmp_path / key.lower()
        folder.mkdir()
        env_file.update_env_value(env_path, key, str(folder))

    verify.verify_installs(
        tmp_path,
        prompt_for_missing=lambda key, current: str(real_mcc) if key == locations.HALO_MCC_KEY else None,
        verify_steam=lambda path: True,
        delay=0,
    )

    assert env_file.get_env_values(env_path)[locations.HALO_MCC_KEY] == str(real_mcc)


def test_run_verify_exits_on_non_windows(monkeypatch):
    monkeypatch.setattr(verify.sys, "platform", "linux")

    with pytest.raises(SystemExit):
        verify.run_verify()


def test_run_verify_errors_when_no_project_found(tmp_path, monkeypatch):
    monkeypatch.setattr(verify.sys, "platform", "win32")

    with pytest.raises(SystemExit):
        verify.run_verify(tmp_path)


def test_run_verify_runs_installs_against_found_project(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(verify.sys, "platform", "win32")
    (tmp_path / project.PROJECT_DIR_NAME).mkdir()

    calls = []
    monkeypatch.setattr(verify, "verify_installs", lambda project_dir: calls.append(project_dir))

    with caplog.at_level(logging.INFO, logger="inreach"):
        verify.run_verify(tmp_path)

    assert "Starting verification" in caplog.text
    assert calls == [tmp_path / project.PROJECT_DIR_NAME]
