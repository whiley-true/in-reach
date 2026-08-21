from inreach.app.setup import env_file, project


def test_create_project_returns_none_off_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(project.sys, "platform", "linux")

    result = project.create_project(tmp_path)

    assert result is None
    assert not (tmp_path / ".inreach").exists()


def test_create_project_creates_folder_and_copies_env(tmp_path, monkeypatch):
    monkeypatch.setattr(project.sys, "platform", "win32")

    result = project.create_project(tmp_path)

    assert result == tmp_path / ".inreach"
    assert (result / ".env").exists()
    assert (result / ".gitignore").exists()
    values = env_file.get_env_values(result / ".env")
    assert values["ROOT_DIR"] == str(tmp_path)
    assert values["LOG_FILE"]
    assert values["LOG_LEVEL"] == "INFO"
    assert values["OUTPUT_TO_STREAM"] == "false"


def test_create_project_returns_none_if_already_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(project.sys, "platform", "win32")
    (tmp_path / ".inreach").mkdir()

    result = project.create_project(tmp_path)

    assert result is None
