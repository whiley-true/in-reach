import pytest

from inreach.app.setup import env_file, locations, personal_variants, screens, setup_proj, users


def test_setup_project_exits_on_non_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_proj.sys, "platform", "linux")
    (tmp_path / ".env").write_text("", encoding="utf-8")

    with pytest.raises(SystemExit):
        setup_proj.setup_project(tmp_path)


def test_setup_project_runs_all_steps(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_proj.sys, "platform", "win32")
    (tmp_path / ".env").write_text("USER_WIN_NAME=\n", encoding="utf-8")

    monkeypatch.setattr(users, "list_windows_users", lambda: ["testuser"])

    calls = []
    monkeypatch.setattr(locations, "verify_locations", lambda env_path: calls.append(("locations", env_path)))
    monkeypatch.setattr(
        personal_variants,
        "resolve_personal_variants",
        lambda env_path: calls.append(("personal_variants", env_path)),
    )
    monkeypatch.setattr(screens, "save_screen_config", lambda project_dir: calls.append(("screens", project_dir)))
    monkeypatch.setattr(setup_proj.ui, "clear_screen", lambda: calls.append(("clear_screen",)))

    setup_proj.setup_project(tmp_path)

    env_path = tmp_path / ".env"
    assert env_file.get_env_values(env_path)["USER_WIN_NAME"] == "testuser"
    assert calls == [
        ("locations", env_path),
        ("personal_variants", env_path),
        ("screens", tmp_path),
        ("clear_screen",),
    ]


def test_set_user_win_name_prompts_when_multiple_users(tmp_path, monkeypatch):
    monkeypatch.setattr(users, "list_windows_users", lambda: ["alice", "bob"])
    monkeypatch.setattr(setup_proj.ui, "select_option", lambda title, options: 1)
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")

    setup_proj._set_user_win_name(env_path)

    assert env_file.get_env_values(env_path)["USER_WIN_NAME"] == "bob"
