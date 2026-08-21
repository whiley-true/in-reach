from inreach.app.setup import env_file, steam

LOCALCONFIG_TEMPLATE = """
"UserLocalConfigStore"
{{
	"friends"
	{{
		"PersonaName"		"{persona}"
	}}
}}
"""


def _write_user(userdata_dir, user_id, persona=None):
    config_dir = userdata_dir / user_id / "config"
    config_dir.mkdir(parents=True)
    if persona is not None:
        (config_dir / "localconfig.vdf").write_text(
            LOCALCONFIG_TEMPLATE.format(persona=persona), encoding="utf-8"
        )


def test_list_steam_user_ids_only_includes_configured_users(tmp_path):
    userdata_dir = tmp_path / "userdata"
    _write_user(userdata_dir, "111", persona="Alice")
    (userdata_dir / "222").mkdir(parents=True)  # no config subfolder

    assert steam.list_steam_user_ids(userdata_dir) == ["111"]


def test_list_steam_user_ids_missing_dir_returns_empty(tmp_path):
    assert steam.list_steam_user_ids(tmp_path / "does-not-exist") == []


def test_read_persona_name(tmp_path):
    userdata_dir = tmp_path / "userdata"
    _write_user(userdata_dir, "111", persona="PaPa Smurf")

    assert steam.read_persona_name(userdata_dir, "111") == "PaPa Smurf"


def test_read_persona_name_missing_file_returns_none(tmp_path):
    userdata_dir = tmp_path / "userdata"

    assert steam.read_persona_name(userdata_dir, "111") is None


def test_resolve_steam_user_auto_selects_single_user(tmp_path):
    steam_loc = tmp_path / "steam"
    _write_user(steam_loc / "userdata", "111", persona="Alice")
    env_path = tmp_path / ".env"

    chosen = steam.resolve_steam_user(env_path, steam_loc, delay=0)

    assert chosen == "111"
    assert env_file.get_env_values(env_path)["USER_STEAM_LOC_INT"] == "111"


def test_resolve_steam_user_prompts_when_multiple(tmp_path):
    steam_loc = tmp_path / "steam"
    _write_user(steam_loc / "userdata", "111", persona="Alice")
    _write_user(steam_loc / "userdata", "222", persona="Bob")
    env_path = tmp_path / ".env"

    chosen = steam.resolve_steam_user(env_path, steam_loc, select_user=lambda title, options: 1, delay=0)

    assert chosen == "222"
    assert env_file.get_env_values(env_path)["USER_STEAM_LOC_INT"] == "222"


def test_resolve_steam_user_returns_none_when_no_users(tmp_path):
    steam_loc = tmp_path / "steam"
    env_path = tmp_path / ".env"

    assert steam.resolve_steam_user(env_path, steam_loc, delay=0) is None


def test_resolve_steam_user_redraws_checklist_after_menu(tmp_path, monkeypatch):
    steam_loc = tmp_path / "steam"
    _write_user(steam_loc / "userdata", "111", persona="Alice")
    _write_user(steam_loc / "userdata", "222", persona="Bob")
    env_path = tmp_path / ".env"

    checklist_calls = []
    real_checklist = steam.ui.checklist

    def spy_checklist(title, items, check, delay=0.5):
        checklist_calls.append((title, delay))
        return real_checklist(title, items, check, delay=0)

    monkeypatch.setattr(steam.ui, "checklist", spy_checklist)

    steam.resolve_steam_user(env_path, steam_loc, select_user=lambda title, options: 0, delay=0.5)

    # Once showing the ambiguous/missing state (with the caller's real
    # delay), once more after the menu resolves it - that redraw should
    # populate prefilled (delay=0), not replay the reveal animation.
    assert checklist_calls == [(steam._CHECKLIST_TITLE, 0.5), (steam._CHECKLIST_TITLE, 0)]


def test_launch_mcc_eac_disabled_uses_option1():
    calls = []

    steam.launch_mcc_eac_disabled(launch_uri=calls.append)

    assert calls == ["steam://launch/976730/option1"]
