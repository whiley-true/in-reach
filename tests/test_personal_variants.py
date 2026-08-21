import pytest

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


def test_no_subfolders_and_bootstrap_fails_exits(tmp_path):
    # Without a personal-variants folder the rest of this tool can't do
    # its job - fatal, not skippable, so menu.run_init_menu's cleanup
    # (which catches BaseException, including SystemExit) can remove the
    # half-configured .inreach project folder.
    loc_1 = tmp_path / "personal"
    loc_1.mkdir()
    env_path = _write_base_env(tmp_path, loc_1)

    with pytest.raises(SystemExit):
        personal_variants.resolve_personal_variants(env_path, create_gametype=lambda loc_1: False)

    values = env_file.get_env_values(env_path)
    assert values["USER_REACH_STRING"] == ""
    assert list(loc_1.iterdir()) == []


def test_no_subfolders_and_no_new_folder_appears_exits(tmp_path):
    loc_1 = tmp_path / "personal"
    loc_1.mkdir()
    env_path = _write_base_env(tmp_path, loc_1)

    with pytest.raises(SystemExit):
        personal_variants.resolve_personal_variants(env_path, create_gametype=lambda loc_1: True)

    values = env_file.get_env_values(env_path)
    assert values["USER_REACH_STRING"] == ""
    assert list(loc_1.iterdir()) == []


def test_no_subfolders_and_bootstrap_creates_folder(tmp_path):
    loc_1 = tmp_path / "personal"
    loc_1.mkdir()
    env_path = _write_base_env(tmp_path, loc_1)

    def fake_create_gametype(personal_variants_loc_1):
        assert personal_variants_loc_1 == loc_1
        gametype_dir = loc_1 / "000901f158282684" / "HaloReach" / "GameType"
        gametype_dir.mkdir(parents=True)
        (gametype_dir / "9b0cfdd5-5f0e-4464-89f1-94997c1cdf9c.bin").write_bytes(b"fake gametype data")
        return True

    personal_variants.resolve_personal_variants(env_path, create_gametype=fake_create_gametype)

    values = env_file.get_env_values(env_path)
    assert values["USER_REACH_STRING"] == "000901f158282684"
    gametype_dir = loc_1 / "000901f158282684" / "HaloReach" / "GameType"
    assert values["PERSONAL_VARIANTS_LOC"] == str(gametype_dir)
    # The throwaway gametype the bootstrap saved is cleaned up once its
    # job (making Reach create the folder) is done.
    assert list(gametype_dir.iterdir()) == []


def test_tells_the_user_the_ui_is_about_to_be_automated(tmp_path, monkeypatch):
    # The gametype bootstrap takes over the mouse/keyboard to drive MCC's
    # own UI - the user should see why before that happens, not just find
    # their input hijacked with no explanation.
    loc_1 = tmp_path / "personal"
    loc_1.mkdir()
    env_path = _write_base_env(tmp_path, loc_1)
    messages = []
    monkeypatch.setattr(personal_variants.ui, "info", messages.append)
    create_gametype_calls = []

    def fake_create_gametype(personal_variants_loc_1):
        # The info message must appear before automation is even
        # attempted, not just before a successful outcome.
        assert messages
        create_gametype_calls.append(1)
        return False

    with pytest.raises(SystemExit):
        personal_variants.resolve_personal_variants(env_path, create_gametype=fake_create_gametype)

    assert create_gametype_calls == [1]
    assert any("mouse/keyboard" in m for m in messages)


def test_auto_selects_single_subfolder(tmp_path):
    loc_1 = tmp_path / "personal"
    (loc_1 / "only_variant" / "HaloReach" / "GameType").mkdir(parents=True)
    env_path = _write_base_env(tmp_path, loc_1)

    personal_variants.resolve_personal_variants(env_path)

    values = env_file.get_env_values(env_path)
    assert values["USER_REACH_STRING"] == "only_variant"
    assert values["PERSONAL_VARIANTS_LOC_2"] == "only_variant\\HaloReach\\GameType"
    assert values["PERSONAL_VARIANTS_LOC"] == str(loc_1 / "only_variant\\HaloReach\\GameType")


def test_ignores_a_subfolder_missing_the_haloreach_gametype_structure(tmp_path):
    loc_1 = tmp_path / "personal"
    # A folder that exists under LocalFiles but isn't actually a personal
    # variants folder - e.g. something else MCC/Windows left behind.
    (loc_1 / "not_a_variant_folder").mkdir(parents=True)
    (loc_1 / "only_variant" / "HaloReach" / "GameType").mkdir(parents=True)
    env_path = _write_base_env(tmp_path, loc_1)

    personal_variants.resolve_personal_variants(env_path)

    values = env_file.get_env_values(env_path)
    assert values["USER_REACH_STRING"] == "only_variant"


def test_prompts_when_multiple_subfolders_and_opens_explorer(tmp_path):
    loc_1 = tmp_path / "personal"
    (loc_1 / "variant_a" / "HaloReach" / "GameType").mkdir(parents=True)
    (loc_1 / "variant_b" / "HaloReach" / "GameType").mkdir(parents=True)
    env_path = _write_base_env(tmp_path, loc_1)

    opened = []
    personal_variants.resolve_personal_variants(
        env_path, select_variant=lambda title, options: 1, open_folder=opened.append
    )

    values = env_file.get_env_values(env_path)
    assert values["USER_REACH_STRING"] == "variant_b"
    assert opened == [str(loc_1 / "variant_b")]
