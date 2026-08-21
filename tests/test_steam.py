import pytest

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


def test_check_steam_account_single_id_resolves(tmp_path):
    steam_loc = tmp_path / "steam"
    _write_user(steam_loc / "userdata", "111", persona="Alice")
    env_path = tmp_path / ".env"

    assert steam.check_steam_account(env_path, steam_loc) == "111"


def test_check_steam_account_multiple_ids_ambiguous_without_prior_choice(tmp_path):
    steam_loc = tmp_path / "steam"
    _write_user(steam_loc / "userdata", "111", persona="Alice")
    _write_user(steam_loc / "userdata", "222", persona="Bob")
    env_path = tmp_path / ".env"

    assert steam.check_steam_account(env_path, steam_loc) is None


def test_check_steam_account_multiple_ids_resolves_with_prior_choice(tmp_path):
    steam_loc = tmp_path / "steam"
    _write_user(steam_loc / "userdata", "111", persona="Alice")
    _write_user(steam_loc / "userdata", "222", persona="Bob")
    env_path = tmp_path / ".env"
    env_file.update_env_value(env_path, steam.USER_STEAM_LOC_INT_KEY, "222")

    assert steam.check_steam_account(env_path, steam_loc) == "222"


def test_check_steam_account_no_ids_returns_none(tmp_path):
    steam_loc = tmp_path / "steam"
    env_path = tmp_path / ".env"

    assert steam.check_steam_account(env_path, steam_loc) is None


def test_resolve_steam_account_via_menu_prompts_and_saves(tmp_path):
    steam_loc = tmp_path / "steam"
    _write_user(steam_loc / "userdata", "111", persona="Alice")
    _write_user(steam_loc / "userdata", "222", persona="Bob")
    env_path = tmp_path / ".env"

    chosen = steam.resolve_steam_account_via_menu(env_path, steam_loc, select_user=lambda title, options: 1)

    assert chosen == "222"
    assert env_file.get_env_values(env_path)["USER_STEAM_LOC_INT"] == "222"


def test_resolve_steam_account_via_menu_offers_exit_option(tmp_path):
    steam_loc = tmp_path / "steam"
    _write_user(steam_loc / "userdata", "111", persona="Alice")
    _write_user(steam_loc / "userdata", "222", persona="Bob")
    env_path = tmp_path / ".env"

    seen_options = []

    def select_user(title, options):
        seen_options.append(options)
        return 1

    steam.resolve_steam_account_via_menu(env_path, steam_loc, select_user=select_user)

    assert seen_options == [["Alice (111)", "Bob (222)", steam.EXIT]]


def test_resolve_steam_account_via_menu_exits_when_exit_chosen(tmp_path):
    steam_loc = tmp_path / "steam"
    _write_user(steam_loc / "userdata", "111", persona="Alice")
    _write_user(steam_loc / "userdata", "222", persona="Bob")
    env_path = tmp_path / ".env"

    with pytest.raises(SystemExit):
        steam.resolve_steam_account_via_menu(env_path, steam_loc, select_user=lambda title, options: 2)

    assert "USER_STEAM_LOC_INT" not in env_file.get_env_values(env_path)


def test_resolve_steam_account_via_menu_warns_when_no_accounts(tmp_path, monkeypatch):
    steam_loc = tmp_path / "steam"
    (steam_loc / "userdata").mkdir(parents=True)
    env_path = tmp_path / ".env"

    warnings = []
    monkeypatch.setattr(steam.ui, "warning", warnings.append)

    result = steam.resolve_steam_account_via_menu(env_path, steam_loc, select_user=lambda title, options: 0)

    assert result is None
    assert any("No Steam accounts found" in message for message in warnings)


def test_launch_mcc_eac_disabled_uses_option1():
    calls = []

    steam.launch_mcc_eac_disabled(launch_uri=calls.append)

    assert calls == ["steam://launch/976730/option1"]
