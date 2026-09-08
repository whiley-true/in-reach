from pathlib import Path

import pytest

from in_reach.app import env_file, system_verify
from in_reach.app.system_verify import Outcome, VerifyRun

_LOCALCONFIG = """
"UserLocalConfigStore"
{
    "friends"
    {
        "PersonaName"     "{persona}"
    }
}
"""


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """A ``.in-reach`` folder with a blank ``.env``, as ``in-reach run`` would have made it."""
    project = tmp_path / ".in-reach"
    project.mkdir()
    (project / ".env").write_text("", encoding="utf-8")
    return project


def _step(env_key: str):
    return next(step for step in system_verify.STEPS if step.env_key == env_key)


def _run(project_dir: Path, tmp_path: Path, **kwargs) -> VerifyRun:
    """A run whose every default points inside ``tmp_path`` -- including the one hardcoded default
    in the chain, the Steam install, which would otherwise resolve for real on a machine that has
    Steam installed and quietly satisfy steps a test needs to leave unresolved."""
    return VerifyRun(project_dir, home=tmp_path, steam_default=tmp_path / "no-steam-here", **kwargs)


def _make_steam_install(root: Path, *accounts: tuple[str, str]) -> Path:
    """Builds a fake Steam install, with one ``userdata`` account per ``(id, persona)`` pair."""
    steam = root / "Steam"
    (steam / "steamapps" / "common").mkdir(parents=True)
    for account_id, persona in accounts:
        config_dir = steam / "userdata" / account_id / "config"
        config_dir.mkdir(parents=True)
        (config_dir / "localconfig.vdf").write_text(
            _LOCALCONFIG.replace("{persona}", persona), encoding="utf-8"
        )
    return steam


def _make_reach_install(steam: Path) -> Path:
    reach = steam / "steamapps" / "common" / "Halo The Master Chief Collection" / "haloreach"
    for name in ("game_variants", "hopper_game_variants", "map_variants", "hopper_map_variants"):
        (reach / name).mkdir(parents=True)
    return reach


def _make_local_files(home: Path, *reach_strings: str) -> Path:
    local_files = home / "AppData" / "LocalLow" / "MCC" / "LocalFiles"
    for reach_string in reach_strings:
        (local_files / reach_string / "HaloReach" / "GameType").mkdir(parents=True)
    local_files.mkdir(parents=True, exist_ok=True)
    return local_files


# -- the checklist itself ---------------------------------------------------------------------------


def test_steps_are_the_twelve_asked_for_in_order() -> None:
    assert [step.label for step in system_verify.STEPS] == [
        "Tesseract OCR Installed on Path",
        "Steam Install Location",
        "Halo MCC Install",
        "Halo Reach (In MCC)",
        "Halo Reach Hot Reload",
        "Standard Game Variants",
        "Hopper Game Variants",
        "Standard Map Variants",
        "Hopper Map Variants",
        "Steam Account Uuid (and user)",
        "Personal Game Variants Folder",
        "Personal Map Variants Folder",
    ]


def test_a_fresh_project_has_every_step_unticked(project_dir: Path) -> None:
    verified = system_verify.verified_keys(project_dir)

    assert set(verified) == {step.env_key for step in system_verify.STEPS}
    assert not any(verified.values())


def test_a_step_ticks_once_its_env_key_holds_a_value(project_dir: Path) -> None:
    env_file.update_env_value(project_dir / ".env", system_verify.STEAM_KEY, r"C:\Steam")

    assert system_verify.verified_keys(project_dir)[system_verify.STEAM_KEY] is True


def test_clear_entries_unticks_everything_including_the_derived_values(project_dir: Path) -> None:
    env_path = project_dir / ".env"
    for key in system_verify.CLEARED_KEYS:
        env_file.update_env_value(env_path, key, "something")
    env_file.update_env_value(env_path, "LOG_LEVEL", "DEBUG")

    system_verify.clear_entries(project_dir)

    assert not any(system_verify.verified_keys(project_dir).values())
    values = env_file.get_env_values(env_path)
    assert values[system_verify.USER_REACH_STRING_KEY] == ""
    assert values[system_verify.USER_STEAM_PROFILE_NAME_KEY] == ""
    # Only the checklist's own keys -- an unrelated setting is left alone.
    assert values["LOG_LEVEL"] == "DEBUG"


# -- Tesseract --------------------------------------------------------------------------------------


def test_tesseract_resolves_from_path(project_dir: Path, tmp_path: Path) -> None:
    exe = tmp_path / "tesseract.exe"
    exe.write_text("", encoding="utf-8")
    run = _run(project_dir, tmp_path, which=lambda _name: str(exe))

    result = run.check(_step(system_verify.TESSERACT_KEY))

    assert result.outcome == Outcome.FOUND
    assert result.value == str(exe)


def test_tesseract_missing_from_path_is_reported_with_an_install_hint(
    project_dir: Path, tmp_path: Path
) -> None:
    run = _run(project_dir, tmp_path, which=lambda _name: None)

    result = run.check(_step(system_verify.TESSERACT_KEY))

    assert result.outcome == Outcome.MISSING
    assert "winget" in result.step.hint


# -- locations --------------------------------------------------------------------------------------


def test_a_manual_steam_override_cascades_into_every_path_derived_from_it(
    project_dir: Path, tmp_path: Path
) -> None:
    steam = _make_steam_install(tmp_path)
    reach = _make_reach_install(steam)
    run = _run(project_dir, tmp_path, which=lambda _name: None)

    run.accept(_step(system_verify.STEAM_KEY), str(steam))

    for key, expected in (
        (system_verify.HALO_MCC_KEY, reach.parent),
        (system_verify.REACH_KEY, reach),
        (system_verify.STANDARD_VARIANTS_KEY, reach / "game_variants"),
        (system_verify.HOPPER_VARIANTS_KEY, reach / "hopper_game_variants"),
        (system_verify.STANDARD_MAP_VARIANTS_KEY, reach / "map_variants"),
        (system_verify.HOPPER_MAP_VARIANTS_KEY, reach / "hopper_map_variants"),
    ):
        result = run.check(_step(key))
        assert result.outcome == Outcome.FOUND, key
        assert Path(result.value) == expected
        run.accept(_step(key), result.value)


def test_a_location_that_does_not_exist_reports_where_it_looked(project_dir: Path, tmp_path: Path) -> None:
    run = _run(project_dir, tmp_path, which=lambda _name: None)

    result = run.check(_step(system_verify.HOTRELOAD_KEY))

    assert result.outcome == Outcome.MISSING
    # The suggestion is what the manual folder picker opens at -- it has to be the path the step
    # actually looked in, not a blank.
    expected = tmp_path / "AppData" / "LocalLow" / "MCC" / "Temporary" / "HaloReach" / "HotReload"
    assert Path(result.suggestion) == expected


def test_an_already_stored_location_is_kept_rather_than_rederived(project_dir: Path, tmp_path: Path) -> None:
    custom = tmp_path / "elsewhere" / "game_variants"
    custom.mkdir(parents=True)
    _make_reach_install(_make_steam_install(tmp_path))
    env_file.update_env_value(project_dir / ".env", system_verify.STANDARD_VARIANTS_KEY, str(custom))
    run = _run(project_dir, tmp_path, which=lambda _name: None)

    result = run.check(_step(system_verify.STANDARD_VARIANTS_KEY))

    assert result.outcome == Outcome.FOUND
    assert Path(result.value) == custom


# -- Steam account ----------------------------------------------------------------------------------


def test_a_single_steam_account_resolves_itself(project_dir: Path, tmp_path: Path) -> None:
    steam = _make_steam_install(tmp_path, ("12345", "Whiley"))
    run = _run(project_dir, tmp_path, which=lambda _name: None)
    run.accept(_step(system_verify.STEAM_KEY), str(steam))

    result = run.check(_step(system_verify.STEAM_ACCOUNT_KEY))

    assert result.outcome == Outcome.FOUND
    assert result.value == "12345"
    assert "Whiley" in result.detail


def test_accepting_a_steam_account_also_records_its_persona_name(project_dir: Path, tmp_path: Path) -> None:
    steam = _make_steam_install(tmp_path, ("12345", "Whiley"))
    run = _run(project_dir, tmp_path, which=lambda _name: None)
    run.accept(_step(system_verify.STEAM_KEY), str(steam))

    run.accept(_step(system_verify.STEAM_ACCOUNT_KEY), "12345")

    values = env_file.get_env_values(project_dir / ".env")
    assert values[system_verify.STEAM_ACCOUNT_KEY] == "12345"
    assert values[system_verify.USER_STEAM_PROFILE_NAME_KEY] == "Whiley"


def test_several_steam_accounts_are_offered_as_a_labelled_choice(project_dir: Path, tmp_path: Path) -> None:
    steam = _make_steam_install(tmp_path, ("111", "Whiley"), ("222", "Someone Else"))
    run = _run(project_dir, tmp_path, which=lambda _name: None)
    run.accept(_step(system_verify.STEAM_KEY), str(steam))

    result = run.check(_step(system_verify.STEAM_ACCOUNT_KEY))

    assert result.outcome == Outcome.CHOICE
    assert [(c.value, c.label) for c in result.choices] == [
        ("111", "Whiley (111)"),
        ("222", "Someone Else (222)"),
    ]


def test_no_steam_accounts_at_all_is_missing_not_a_choice(project_dir: Path, tmp_path: Path) -> None:
    steam = _make_steam_install(tmp_path)
    run = _run(project_dir, tmp_path, which=lambda _name: None)
    run.accept(_step(system_verify.STEAM_KEY), str(steam))

    assert run.check(_step(system_verify.STEAM_ACCOUNT_KEY)).outcome == Outcome.MISSING


# -- personal folders -------------------------------------------------------------------------------


def test_a_single_personal_gametype_folder_resolves_and_records_the_reach_string(
    project_dir: Path, tmp_path: Path
) -> None:
    local_files = _make_local_files(tmp_path, "000901f158282684")
    run = _run(project_dir, tmp_path, which=lambda _name: None)

    result = run.check(_step(system_verify.PERSONAL_VARIANTS_KEY))
    assert result.outcome == Outcome.FOUND
    assert Path(result.value) == local_files / "000901f158282684" / "HaloReach" / "GameType"

    run.accept(_step(system_verify.PERSONAL_VARIANTS_KEY), result.value)
    values = env_file.get_env_values(project_dir / ".env")
    assert values[system_verify.USER_REACH_STRING_KEY] == "000901f158282684"
    assert Path(values[system_verify.LOCAL_FILES_KEY]) == local_files


def test_several_personal_gametype_folders_are_offered_as_a_choice(project_dir: Path, tmp_path: Path) -> None:
    _make_local_files(tmp_path, "aaa", "bbb")
    run = _run(project_dir, tmp_path, which=lambda _name: None)

    result = run.check(_step(system_verify.PERSONAL_VARIANTS_KEY))

    assert result.outcome == Outcome.CHOICE
    assert [choice.label for choice in result.choices] == ["aaa", "bbb"]


def test_no_saved_gametype_yet_is_missing_with_the_in_game_hint(project_dir: Path, tmp_path: Path) -> None:
    _make_local_files(tmp_path)
    run = _run(project_dir, tmp_path, which=lambda _name: None)

    result = run.check(_step(system_verify.PERSONAL_VARIANTS_KEY))

    assert result.outcome == Outcome.MISSING
    assert "Save As" in result.step.hint


def test_the_personal_map_folder_is_derived_from_the_gametype_folder_and_created_on_accept(
    project_dir: Path, tmp_path: Path
) -> None:
    local_files = _make_local_files(tmp_path, "000901f158282684")
    run = _run(project_dir, tmp_path, which=lambda _name: None)
    variants = run.check(_step(system_verify.PERSONAL_VARIANTS_KEY))
    run.accept(_step(system_verify.PERSONAL_VARIANTS_KEY), variants.value)

    result = run.check(_step(system_verify.PERSONAL_MAPS_KEY))
    expected = local_files / "000901f158282684" / "HaloReach" / "Map"
    assert result.outcome == Outcome.FOUND
    assert Path(result.value) == expected
    # MCC only makes this folder on the first saved Forge map -- accept() shouldn't wait for that.
    assert not expected.exists()

    run.accept(_step(system_verify.PERSONAL_MAPS_KEY), result.value)
    assert expected.is_dir()


def test_the_personal_map_folder_needs_the_gametype_folder_first(project_dir: Path, tmp_path: Path) -> None:
    _make_local_files(tmp_path, "000901f158282684")
    run = _run(project_dir, tmp_path, which=lambda _name: None)

    assert run.check(_step(system_verify.PERSONAL_MAPS_KEY)).outcome == Outcome.MISSING


# -- misc -------------------------------------------------------------------------------------------


def test_record_windows_user_stamps_the_running_account(project_dir: Path, tmp_path: Path) -> None:
    run = _run(project_dir, tmp_path, which=lambda _name: None, username="whiley")

    run.record_windows_user()

    assert env_file.get_env_values(project_dir / ".env")[system_verify.USER_WIN_NAME_KEY] == "whiley"


def test_an_unreadable_localconfig_yields_a_bare_id_rather_than_raising(tmp_path: Path) -> None:
    userdata = tmp_path / "userdata"
    (userdata / "999" / "config").mkdir(parents=True)
    (userdata / "999" / "config" / "localconfig.vdf").write_text("not vdf at all", encoding="utf-8")

    assert system_verify.list_steam_account_ids(userdata) == ["999"]
    assert system_verify.read_steam_persona(userdata, "999") == ""


