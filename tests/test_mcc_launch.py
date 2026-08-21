from inreach.app.setup import mcc_launch


def test_launches_and_records_when_not_running(tmp_path):
    calls = []
    launched = []

    mcc_launch.run_eac_launch_step(
        tmp_path,
        tmp_path / ".env",
        confirm=lambda prompt: True,
        is_process_running=lambda name: False,
        close_process=lambda name: calls.append(("close", name)),
        launch=lambda: launched.append("launched"),
        wait_for_process=lambda name, timeout: True,
        record=lambda project_dir, title_matcher: calls.append(("record", project_dir)),
    )

    assert launched == ["launched"]
    assert calls == [("record", tmp_path), ("close", mcc_launch.MCC_PROCESS_NAME)]


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
    )

    assert any("anti-cheat disabled" in message for message in messages)


def test_closes_running_mcc_when_confirmed(tmp_path):
    calls = []

    mcc_launch.run_eac_launch_step(
        tmp_path,
        tmp_path / ".env",
        confirm=lambda prompt: True,
        is_process_running=lambda name: True,
        close_process=lambda name: calls.append(("close", name)),
        launch=lambda: calls.append(("launch",)),
        wait_for_process=lambda name, timeout: True,
        record=lambda project_dir, title_matcher: calls.append(("record", project_dir)),
    )

    assert calls == [
        ("close", mcc_launch.MCC_PROCESS_NAME),
        ("launch",),
        ("record", tmp_path),
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
    )

    assert calls == [("launch",)]
