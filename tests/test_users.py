from inreach.app.setup import users


def test_list_windows_users_returns_empty_for_missing_dir(tmp_path):
    missing = tmp_path / "does-not-exist"

    assert users.list_windows_users(missing) == []


def test_list_windows_users_excludes_system_folders(tmp_path):
    for name in ["Alice", "Bob", "Public", "Default", "All Users"]:
        (tmp_path / name).mkdir()
    (tmp_path / "not_a_user.txt").write_text("", encoding="utf-8")

    result = users.list_windows_users(tmp_path)

    assert result == ["Alice", "Bob"]
