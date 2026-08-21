from inreach.app.setup import mcc_launch


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
    )

    assert any("anti-cheat disabled" in message for message in messages)


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
    )

    assert calls == [("launch",)]
