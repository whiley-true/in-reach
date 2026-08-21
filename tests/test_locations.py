from inreach.app.setup import env_file, locations


def test_verify_locations_skips_existing_paths(tmp_path):
    env_path = tmp_path / ".env"
    existing = tmp_path / "steam"
    existing.mkdir()
    env_file.update_env_value(env_path, "STEAM_INSTALL_LOC", str(existing))

    calls = []
    locations.verify_locations(
        env_path,
        prompt_for_missing=lambda key, current: calls.append(key),
        delay=0,
    )

    assert calls == [key for key in locations.LOCATION_KEYS if key != "STEAM_INSTALL_LOC"]


def test_verify_locations_updates_env_when_user_provides_path(tmp_path):
    env_path = tmp_path / ".env"
    env_file.update_env_value(env_path, "STEAM_INSTALL_LOC", str(tmp_path / "missing"))
    found = tmp_path / "found"
    found.mkdir()

    def fake_prompt(key, current):
        return str(found) if key == "STEAM_INSTALL_LOC" else None

    locations.verify_locations(env_path, prompt_for_missing=fake_prompt, delay=0)

    assert env_file.get_env_values(env_path)["STEAM_INSTALL_LOC"] == str(found)


def test_verify_locations_leaves_env_unchanged_when_declined(tmp_path):
    env_path = tmp_path / ".env"
    missing = str(tmp_path / "missing")
    env_file.update_env_value(env_path, "STEAM_INSTALL_LOC", missing)

    locations.verify_locations(env_path, prompt_for_missing=lambda key, current: None, delay=0)

    assert env_file.get_env_values(env_path)["STEAM_INSTALL_LOC"] == missing
