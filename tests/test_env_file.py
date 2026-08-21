from inreach.app.setup import env_file


def test_update_env_value_replaces_existing_key(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("FOO=\nBAR='baz'\n", encoding="utf-8")

    env_file.update_env_value(env_path, "FOO", "hello")

    text = env_path.read_text(encoding="utf-8")
    assert "FOO='hello'" in text
    assert "BAR='baz'" in text


def test_update_env_value_appends_missing_key(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("FOO=\n", encoding="utf-8")

    env_file.update_env_value(env_path, "NEW_KEY", "value")

    lines = env_path.read_text(encoding="utf-8").splitlines()
    assert "NEW_KEY='value'" in lines


def test_update_env_value_clears_when_empty(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("FOO='old'\n", encoding="utf-8")

    env_file.update_env_value(env_path, "FOO", "")

    assert "FOO=" in env_path.read_text(encoding="utf-8")
    assert "FOO=''" not in env_path.read_text(encoding="utf-8")


def test_get_env_values_interpolates_variables(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("BASE='C:\\Users\\me'\nCHILD='${BASE}\\folder'\n", encoding="utf-8")

    values = env_file.get_env_values(env_path)

    assert values["CHILD"] == "C:\\Users\\me\\folder"


def test_get_env_values_preserves_windows_path_backslashes(tmp_path):
    """Single-quoted values must survive round-tripping without escape mangling
    (double-quoted values would turn "\\v" in "\\variant" into a vertical tab)."""
    env_path = tmp_path / ".env"
    env_file.update_env_value(env_path, "LOC", "C:\\Users\\me\\variant_b\\HaloReach")

    values = env_file.get_env_values(env_path)

    assert values["LOC"] == "C:\\Users\\me\\variant_b\\HaloReach"
