import subprocess

import pytest

from in_reach.app import halo_status


def test_is_mcc_running_false_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(halo_status.sys, "platform", "linux")

    assert halo_status.is_mcc_running() is False


def test_is_mcc_running_true_when_tasklist_lists_the_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(halo_status.sys, "platform", "win32")
    calls = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(
            cmd, 0, stdout='"MCC-Win64-Shipping.exe","1234","Console","1","500,000 K"\n', stderr=""
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)

    assert halo_status.is_mcc_running() is True
    assert calls[0][0] == "tasklist"
    assert f"IMAGENAME eq {halo_status.MCC_PROCESS_NAME}" in calls[0]


def test_is_mcc_running_false_when_tasklist_finds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(halo_status.sys, "platform", "win32")

    def _fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 0, stdout="INFO: No tasks are running which match the specified criteria.\n", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)

    assert halo_status.is_mcc_running() is False


def test_is_mcc_running_false_when_the_subprocess_call_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(halo_status.sys, "platform", "win32")

    def _raise(cmd, **kwargs):
        raise OSError("tasklist not found")

    monkeypatch.setattr(subprocess, "run", _raise)

    assert halo_status.is_mcc_running() is False


def test_is_mcc_running_never_shows_a_console_window(monkeypatch: pytest.MonkeyPatch) -> None:
    # This is a console-less GUI app -- shelling out to tasklist without CREATE_NO_WINDOW would
    # briefly flash a console window open every poll.
    monkeypatch.setattr(halo_status.sys, "platform", "win32")
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    halo_status.is_mcc_running()

    assert captured.get("creationflags") == subprocess.CREATE_NO_WINDOW
