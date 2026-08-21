from inreach.app import verify
from inreach.app.setup import mcc_launch


def _no_preceding_items(project_dir):
    """A ``checklist_items_and_check`` stub with no preceding items - keeps
    these tests isolated to MCC-launch/personal-gametype behavior instead
    of also exercising the real install-locations/Steam/Tesseract checks
    ``verify.checklist_items_and_check`` performs by default."""
    return [], lambda key: None


def test_launches_records_and_checks_personal_variants_before_closing(tmp_path):
    calls = []
    launched = []
    env_path = tmp_path / ".env"

    mcc_launch.run_eac_launch_step(
        tmp_path,
        env_path,
        confirm=lambda prompt: True,
        is_process_running=lambda name: False,
        close_process=lambda name: calls.append(("close", name)),
        launch=lambda: launched.append("launched"),
        wait_for_process=lambda name, timeout: True,
        record=lambda project_dir, title_matcher: calls.append(("record", project_dir)),
        resolve_personal_variants=lambda env_path: calls.append(("personal_variants", env_path)),
        checklist_items_and_check=_no_preceding_items,
        delay=0,
    )

    assert launched == ["launched"]
    # The personal-variants (player gametype folder) check must happen
    # before MCC is closed - once it can create the folder, that'll mean
    # driving the game's own UI, which needs it still running.
    assert calls == [
        ("record", tmp_path),
        ("personal_variants", env_path),
        ("close", mcc_launch.MCC_PROCESS_NAME),
    ]


def test_informs_user_before_launching(tmp_path, monkeypatch):
    messages = []
    monkeypatch.setattr(mcc_launch.ui, "info", messages.append)

    mcc_launch.run_eac_launch_step(
        tmp_path,
        tmp_path / ".env",
        confirm=lambda prompt: True,
        is_process_running=lambda name: False,
        close_process=lambda name: None,
        launch=lambda: None,
        wait_for_process=lambda name, timeout: True,
        record=lambda project_dir, title_matcher: None,
        resolve_personal_variants=lambda env_path: None,
        checklist_items_and_check=_no_preceding_items,
        delay=0,
    )

    assert any("anti-cheat disabled" in message for message in messages)


def test_shows_mcc_launch_and_personal_gametype_in_the_same_checklist_as_installs(tmp_path, monkeypatch):
    # The user should see these as two more items in the exact same
    # checklist verify.verify_installs already showed (same title, same
    # widget), not a second, separately-titled checklist screen.
    checklist_calls = []
    real_checklist = mcc_launch.ui.checklist

    def spy_checklist(title, items, check, delay=0.5):
        checklist_calls.append((title, [key for key, _label in items]))
        return real_checklist(title, items, check, delay=delay)

    monkeypatch.setattr(mcc_launch.ui, "checklist", spy_checklist)

    def fake_preceding_items(project_dir):
        return [("some_install_location", "Some install location")], lambda key: "found"

    mcc_launch.run_eac_launch_step(
        tmp_path,
        tmp_path / ".env",
        confirm=lambda prompt: True,
        is_process_running=lambda name: False,
        close_process=lambda name: None,
        launch=lambda: None,
        wait_for_process=lambda name, timeout: True,
        record=lambda project_dir, title_matcher: None,
        resolve_personal_variants=lambda env_path: None,
        checklist_items_and_check=fake_preceding_items,
        delay=0,
    )

    assert checklist_calls == [
        (verify.CHECKLIST_TITLE, ["some_install_location", mcc_launch.MCC_LAUNCH_KEY, mcc_launch.PERSONAL_GAMETYPE_KEY])
    ]


def test_uses_the_real_verify_checklist_items_by_default(tmp_path, monkeypatch):
    # Without an override, this should share verify's real checklist
    # builder (not something bespoke to this module) - confirmed by
    # checking the real install-location keys show up alongside the two
    # new ones, resolved lazily rather than as the parameter's own default
    # value (see the module docstring for why: verify.py is still
    # mid-import when mcc_launch.py is first loaded).
    from inreach.app.setup import locations, steam, tesseract

    checklist_calls = []
    real_checklist = mcc_launch.ui.checklist

    def spy_checklist(title, items, check, delay=0.5):
        checklist_calls.append([key for key, _label in items])
        return real_checklist(title, items, check, delay=delay)

    monkeypatch.setattr(mcc_launch.ui, "checklist", spy_checklist)

    mcc_launch.run_eac_launch_step(
        tmp_path,
        tmp_path / ".env",
        confirm=lambda prompt: True,
        is_process_running=lambda name: False,
        close_process=lambda name: None,
        launch=lambda: None,
        wait_for_process=lambda name, timeout: True,
        record=lambda project_dir, title_matcher: None,
        resolve_personal_variants=lambda env_path: None,
        delay=0,
    )

    expected_keys = [
        *locations.LOCATION_KEYS,
        steam.USER_STEAM_LOC_INT_KEY,
        tesseract.CHECKLIST_KEY,
        mcc_launch.MCC_LAUNCH_KEY,
        mcc_launch.PERSONAL_GAMETYPE_KEY,
    ]
    assert checklist_calls == [expected_keys]


def test_closes_running_mcc_when_confirmed(tmp_path):
    calls = []
    env_path = tmp_path / ".env"

    mcc_launch.run_eac_launch_step(
        tmp_path,
        env_path,
        confirm=lambda prompt: True,
        is_process_running=lambda name: True,
        close_process=lambda name: calls.append(("close", name)),
        launch=lambda: calls.append(("launch",)),
        wait_for_process=lambda name, timeout: True,
        record=lambda project_dir, title_matcher: calls.append(("record", project_dir)),
        resolve_personal_variants=lambda env_path: calls.append(("personal_variants", env_path)),
        checklist_items_and_check=_no_preceding_items,
        delay=0,
    )

    assert calls == [
        ("close", mcc_launch.MCC_PROCESS_NAME),
        ("launch",),
        ("record", tmp_path),
        ("personal_variants", env_path),
        ("close", mcc_launch.MCC_PROCESS_NAME),
    ]


def test_skips_when_user_declines_to_close_running_mcc(tmp_path):
    calls = []

    mcc_launch.run_eac_launch_step(
        tmp_path,
        tmp_path / ".env",
        confirm=lambda prompt: False,
        is_process_running=lambda name: True,
        close_process=lambda name: calls.append(("close", name)),
        launch=lambda: calls.append(("launch",)),
        wait_for_process=lambda name, timeout: True,
        record=lambda project_dir, title_matcher: calls.append(("record", project_dir)),
        resolve_personal_variants=lambda env_path: calls.append(("personal_variants", env_path)),
        checklist_items_and_check=_no_preceding_items,
        delay=0,
    )

    assert calls == []


def test_does_not_record_when_launch_times_out(tmp_path):
    calls = []

    mcc_launch.run_eac_launch_step(
        tmp_path,
        tmp_path / ".env",
        confirm=lambda prompt: True,
        is_process_running=lambda name: False,
        close_process=lambda name: calls.append(("close", name)),
        launch=lambda: calls.append(("launch",)),
        wait_for_process=lambda name, timeout: False,
        record=lambda project_dir, title_matcher: calls.append(("record", project_dir)),
        resolve_personal_variants=lambda env_path: calls.append(("personal_variants", env_path)),
        checklist_items_and_check=_no_preceding_items,
        delay=0,
    )

    assert calls == [("launch",)]
