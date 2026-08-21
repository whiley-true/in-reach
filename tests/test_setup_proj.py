import pytest

from inreach.app.setup import env_file, locations, mcc_launch, personal_variants, screens, setup_proj, steam, users


def test_setup_project_exits_on_non_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_proj.sys, "platform", "linux")
    (tmp_path / ".env").write_text("", encoding="utf-8")

    with pytest.raises(SystemExit):
        setup_proj.setup_project(tmp_path)


def test_setup_project_runs_all_steps(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_proj.sys, "platform", "win32")
    (tmp_path / ".env").write_text("USER_WIN_NAME=\nSTEAM_INSTALL_LOC='C:\\steam'\n", encoding="utf-8")

    monkeypatch.setattr(users, "list_windows_users", lambda: ["testuser"])

    calls = []
    monkeypatch.setattr(
        setup_proj, "_run_setup_checklist", lambda env_path: calls.append(("checklist", env_path))
    )
    monkeypatch.setattr(
        mcc_launch,
        "run_eac_launch_step",
        lambda project_dir, env_path: calls.append(("mcc_launch", project_dir, env_path)),
    )
    monkeypatch.setattr(
        personal_variants,
        "resolve_personal_variants",
        lambda env_path: calls.append(("personal_variants", env_path)),
    )
    monkeypatch.setattr(screens, "save_screen_config", lambda project_dir: calls.append(("screens", project_dir)))
    monkeypatch.setattr(setup_proj.ui, "clear_screen", lambda: calls.append(("clear_screen",)))

    sleeps = []
    setup_proj.setup_project(tmp_path, sleep=sleeps.append)

    env_path = tmp_path / ".env"
    assert env_file.get_env_values(env_path)["USER_WIN_NAME"] == "testuser"
    assert sleeps == [setup_proj.FINAL_CHECKLIST_HANG_SECONDS]
    assert calls == [
        ("screens", tmp_path),
        ("checklist", env_path),
        ("mcc_launch", tmp_path, env_path),
        ("personal_variants", env_path),
        ("clear_screen",),
    ]


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


def test_run_setup_checklist_shows_one_combined_screen_when_nothing_missing(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    steam_loc = tmp_path / "steam"
    _write_steam_user(steam_loc / "userdata", "111")
    _write_locations_env(tmp_path, env_path, steam_loc)

    checklist_calls = []
    real_checklist = setup_proj.ui.checklist

    def spy_checklist(title, items, check, delay=0.5):
        checklist_calls.append((title, [key for key, _label in items]))
        return real_checklist(title, items, check, delay=delay)

    monkeypatch.setattr(setup_proj.ui, "checklist", spy_checklist)

    setup_proj._run_setup_checklist(env_path, delay=0)

    expected_keys = locations.LOCATION_KEYS + [steam.USER_STEAM_LOC_INT_KEY]
    assert checklist_calls == [(setup_proj._CHECKLIST_TITLE, expected_keys)]
    assert env_file.get_env_values(env_path)[steam.USER_STEAM_LOC_INT_KEY] == "111"


def test_run_setup_checklist_redraws_once_after_resolving_location_and_account(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    steam_loc = tmp_path / "steam"
    _write_steam_user(steam_loc / "userdata", "111", persona="Alice")
    _write_steam_user(steam_loc / "userdata", "222", persona="Bob")

    # Steam's own install location starts out missing, resolved via picker.
    _write_locations_env(tmp_path, env_path, tmp_path / "missing_steam")

    checklist_calls = []
    real_checklist = setup_proj.ui.checklist

    def spy_checklist(title, items, check, delay=0.5):
        checklist_calls.append((title, delay))
        return real_checklist(title, items, check, delay=0)

    monkeypatch.setattr(setup_proj.ui, "checklist", spy_checklist)

    setup_proj._run_setup_checklist(
        env_path,
        prompt_for_missing=lambda key, current: str(steam_loc),
        verify_steam=lambda path: True,
        select_user=lambda title, options: 1,
        delay=0.5,
    )

    # The redraw after resolving should populate prefilled (delay=0), not
    # replay the reveal animation with the caller's real delay.
    assert checklist_calls == [
        (setup_proj._CHECKLIST_TITLE, 0.5),
        (setup_proj._CHECKLIST_TITLE, 0),
    ]
    assert env_file.get_env_values(env_path)[locations.STEAM_KEY] == str(steam_loc)
    assert env_file.get_env_values(env_path)[steam.USER_STEAM_LOC_INT_KEY] == "222"


def test_run_setup_checklist_never_opens_folder_picker_for_steam_account(tmp_path, monkeypatch):
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
    monkeypatch.setattr(setup_proj.ui, "warning", warnings.append)

    setup_proj._run_setup_checklist(
        env_path,
        prompt_for_missing=lambda key, current: prompted.append(key),
        delay=0,
    )

    assert prompted == []
    assert any("No Steam accounts found" in message for message in warnings)


def test_run_setup_checklist_exits_on_fatal_missing_without_extra_redraw(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    steam_loc = tmp_path / "steam"
    _write_steam_user(steam_loc / "userdata", "111")
    _write_locations_env(tmp_path, env_path, steam_loc)
    env_file.update_env_value(env_path, locations.HOTRELOAD_KEY, str(tmp_path / "missing_hotreload"))

    checklist_calls = []
    real_checklist = setup_proj.ui.checklist

    def spy_checklist(title, items, check, delay=0.5):
        checklist_calls.append(title)
        return real_checklist(title, items, check, delay=delay)

    monkeypatch.setattr(setup_proj.ui, "checklist", spy_checklist)

    with pytest.raises(SystemExit):
        setup_proj._run_setup_checklist(env_path, delay=0)

    assert checklist_calls == [setup_proj._CHECKLIST_TITLE]


def test_set_user_win_name_prompts_when_multiple_users(tmp_path, monkeypatch):
    monkeypatch.setattr(users, "list_windows_users", lambda: ["alice", "bob"])
    monkeypatch.setattr(setup_proj.ui, "select_option", lambda title, options: 1)
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")

    setup_proj._set_user_win_name(env_path)

    assert env_file.get_env_values(env_path)["USER_WIN_NAME"] == "bob"
