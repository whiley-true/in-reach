import pytest

from inreach.app import verify
from inreach.app.setup import env_file, mcc_launch, screens, setup_proj, users


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
        verify, "verify_installs", lambda project_dir: calls.append(("verify", project_dir))
    )
    monkeypatch.setattr(
        mcc_launch,
        "run_eac_launch_step",
        lambda project_dir, env_path: calls.append(("mcc_launch", project_dir, env_path)),
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
        ("verify", tmp_path),
        ("mcc_launch", tmp_path, env_path),
        ("clear_screen",),
    ]


def test_set_user_win_name_prompts_when_multiple_users(tmp_path, monkeypatch):
    monkeypatch.setattr(users, "list_windows_users", lambda: ["alice", "bob"])
    monkeypatch.setattr(setup_proj.ui, "select_option", lambda title, options: 1)
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")

    setup_proj._set_user_win_name(env_path)

    assert env_file.get_env_values(env_path)["USER_WIN_NAME"] == "bob"


def test_set_user_win_name_menu_offers_exit_option(tmp_path, monkeypatch):
    monkeypatch.setattr(users, "list_windows_users", lambda: ["alice", "bob"])
    seen_options = []

    def select_option(title, options):
        seen_options.append(options)
        return 1

    monkeypatch.setattr(setup_proj.ui, "select_option", select_option)
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")

    setup_proj._set_user_win_name(env_path)

    assert seen_options == [["alice", "bob", setup_proj.EXIT]]


def test_set_user_win_name_exits_when_exit_chosen(tmp_path, monkeypatch):
    monkeypatch.setattr(users, "list_windows_users", lambda: ["alice", "bob"])
    monkeypatch.setattr(setup_proj.ui, "select_option", lambda title, options: 2)
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")

    with pytest.raises(SystemExit):
        setup_proj._set_user_win_name(env_path)

    assert "USER_WIN_NAME" not in env_file.get_env_values(env_path)
