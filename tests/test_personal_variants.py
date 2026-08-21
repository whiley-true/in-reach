from inreach.app.setup import env_file, personal_variants


def _write_base_env(tmp_path, loc_1):
    env_path = tmp_path / ".env"
    env_file.update_env_value(env_path, "USER_REACH_STRING", "")
    env_file.update_env_value(env_path, "PERSONAL_VARIANTS_LOC_1", str(loc_1))
    env_file.update_env_value(env_path, "PERSONAL_VARIANTS_LOC_2", "${USER_REACH_STRING}\\HaloReach\\GameType")
    env_file.update_env_value(env_path, "PERSONAL_VARIANTS_LOC", "")
    return env_path


def test_skips_when_loc_1_missing(tmp_path):
    env_path = _write_base_env(tmp_path, tmp_path / "does-not-exist")

    personal_variants.resolve_personal_variants(env_path)

    values = env_file.get_env_values(env_path)
    assert values["USER_REACH_STRING"] == ""


def test_skips_when_no_subfolders(tmp_path):
    loc_1 = tmp_path / "personal"
    loc_1.mkdir()
    env_path = _write_base_env(tmp_path, loc_1)

    personal_variants.resolve_personal_variants(env_path)

    values = env_file.get_env_values(env_path)
    assert values["USER_REACH_STRING"] == ""


def test_auto_selects_single_subfolder(tmp_path):
    loc_1 = tmp_path / "personal"
    (loc_1 / "only_variant").mkdir(parents=True)
    env_path = _write_base_env(tmp_path, loc_1)

    personal_variants.resolve_personal_variants(env_path)

    values = env_file.get_env_values(env_path)
    assert values["USER_REACH_STRING"] == "only_variant"
    assert values["PERSONAL_VARIANTS_LOC_2"] == "only_variant\\HaloReach\\GameType"
    assert values["PERSONAL_VARIANTS_LOC"] == str(loc_1 / "only_variant\\HaloReach\\GameType")


def test_prompts_when_multiple_subfolders(tmp_path):
    loc_1 = tmp_path / "personal"
    (loc_1 / "variant_a").mkdir(parents=True)
    (loc_1 / "variant_b").mkdir(parents=True)
    env_path = _write_base_env(tmp_path, loc_1)

    personal_variants.resolve_personal_variants(env_path, select_variant=lambda title, options: 1)

    values = env_file.get_env_values(env_path)
    assert values["USER_REACH_STRING"] == "variant_b"
