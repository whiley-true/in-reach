import subprocess

import pytest

from inreach.app.setup import tesseract


def test_check_tesseract_on_path_found():
    assert tesseract.check_tesseract_on_path(which=lambda name: r"C:\Tesseract-OCR\tesseract.exe") == (
        r"C:\Tesseract-OCR\tesseract.exe"
    )


def test_check_tesseract_on_path_missing():
    assert tesseract.check_tesseract_on_path(which=lambda name: None) is None


def test_refresh_path_from_registry_sets_environ(monkeypatch):
    monkeypatch.setenv("PATH", "stale")

    def fake_run(args, capture_output, text):
        return subprocess.CompletedProcess(args, 0, stdout="C:\\machine;C:\\user", stderr="")

    tesseract._refresh_path_from_registry(run=fake_run)

    assert tesseract.os.environ["PATH"] == "C:\\machine;C:\\user"


def test_refresh_path_from_registry_leaves_path_alone_when_empty(monkeypatch):
    monkeypatch.setenv("PATH", "unchanged")

    def fake_run(args, capture_output, text):
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    tesseract._refresh_path_from_registry(run=fake_run)

    assert tesseract.os.environ["PATH"] == "unchanged"


def test_install_tesseract_happy_path_runs_installer_and_confirms_path(monkeypatch):
    calls = []

    def select_scope(title, options):
        calls.append(("select_scope", title, options))
        return 0

    def run_installer(args, shell):
        calls.append(("run_installer", args, shell))
        return subprocess.CompletedProcess(args, 0)

    def refresh_path():
        calls.append(("refresh_path",))

    result = tesseract.install_tesseract(
        "project_dir",
        select_scope=select_scope,
        run_installer=run_installer,
        refresh_path=refresh_path,
        is_vscode=lambda: False,
        restart_vscode=lambda project_dir: calls.append(("restart_vscode", project_dir)),
        check=lambda: r"C:\Tesseract-OCR\tesseract.exe",
    )

    assert result is True
    assert calls == [
        ("select_scope", "Install Tesseract for", [tesseract.SCOPE_SYSTEM, tesseract.SCOPE_USER]),
        ("run_installer", [str(tesseract.INSTALL_SCRIPT_PATH), "system"], True),
        ("refresh_path",),
    ]


def test_install_tesseract_uses_user_scope_when_second_option_chosen():
    calls = []

    result = tesseract.install_tesseract(
        "project_dir",
        select_scope=lambda title, options: 1,
        run_installer=lambda args, shell: calls.append(args) or subprocess.CompletedProcess(args, 0),
        refresh_path=lambda: None,
        is_vscode=lambda: False,
        restart_vscode=lambda project_dir: None,
        check=lambda: "found",
    )

    assert result is True
    assert calls == [[str(tesseract.INSTALL_SCRIPT_PATH), "user"]]


def test_install_tesseract_returns_false_when_installer_fails(monkeypatch):
    errors = []
    monkeypatch.setattr(tesseract.ui, "error", errors.append)

    result = tesseract.install_tesseract(
        "project_dir",
        select_scope=lambda title, options: 0,
        run_installer=lambda args, shell: subprocess.CompletedProcess(args, 1),
        refresh_path=lambda: pytest.fail("refresh_path should not run after a failed install"),
        is_vscode=lambda: False,
        restart_vscode=lambda project_dir: pytest.fail("restart_vscode should not run after a failed install"),
        check=lambda: None,
    )

    assert result is False
    assert any("failed" in message for message in errors)


def test_install_tesseract_restarts_vscode_when_running_in_vscode():
    calls = []

    tesseract.install_tesseract(
        "project_dir",
        select_scope=lambda title, options: 0,
        run_installer=lambda args, shell: subprocess.CompletedProcess(args, 0),
        refresh_path=lambda: None,
        is_vscode=lambda: True,
        restart_vscode=lambda project_dir: calls.append(project_dir),
        check=lambda: "found",
    )

    assert calls == ["project_dir"]


def test_install_tesseract_errors_when_still_missing_after_install(monkeypatch):
    errors = []
    monkeypatch.setattr(tesseract.ui, "error", errors.append)

    result = tesseract.install_tesseract(
        "project_dir",
        select_scope=lambda title, options: 0,
        run_installer=lambda args, shell: subprocess.CompletedProcess(args, 0),
        refresh_path=lambda: None,
        is_vscode=lambda: False,
        restart_vscode=lambda project_dir: None,
        check=lambda: None,
    )

    assert result is False
    assert any("still isn't resolvable" in message for message in errors)


def test_resolve_tesseract_via_menu_exits_when_confirm_manual_chosen(monkeypatch):
    warnings = []
    monkeypatch.setattr(tesseract.ui, "warning", warnings.append)
    installed = []

    with pytest.raises(SystemExit):
        tesseract.resolve_tesseract_via_menu(
            "project_dir",
            select_option=lambda title, options: 0,
            install=lambda project_dir: installed.append(project_dir),
        )

    assert installed == []
    assert any("It appears Tesseract OCR" in message for message in warnings)


def test_resolve_tesseract_via_menu_installs_when_install_now_chosen(monkeypatch):
    monkeypatch.setattr(tesseract.ui, "warning", lambda message: None)
    installed = []

    tesseract.resolve_tesseract_via_menu(
        "project_dir",
        select_option=lambda title, options: 1,
        install=lambda project_dir: installed.append(project_dir),
    )

    assert installed == ["project_dir"]


def test_restart_vscode_launches_replacement_before_closing_old_window(monkeypatch):
    monkeypatch.setattr(tesseract.ui, "warning", lambda message: None)
    monkeypatch.setattr(tesseract.ui, "press_enter", lambda prompt: None)
    calls = []

    tesseract._restart_vscode(
        "project_dir",
        popen=lambda args, shell: calls.append(("popen", args, shell)),
        close_process=lambda exe_name: calls.append(("close_process", exe_name)),
    )

    assert calls == [
        ("popen", ["code", "project_dir"], True),
        ("close_process", "Code.exe"),
    ]
