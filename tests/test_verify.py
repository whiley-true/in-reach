import logging

from inreach.app import verify


def test_verify_installs_logs_starting_verification(caplog):
    with caplog.at_level(logging.INFO, logger="inreach"):
        verify.verify_installs()
    assert "Starting verification" in caplog.text


def test_verify_installs_exits_early_on_non_windows(monkeypatch, capsys, caplog):
    monkeypatch.setattr(verify.sys, "platform", "linux")

    with caplog.at_level(logging.ERROR, logger="inreach"):
        verify.verify_installs()

    assert "only supported on Windows" in capsys.readouterr().out
