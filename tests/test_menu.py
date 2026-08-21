import click
import pytest

from inreach.app.setup import menu, project, setup_proj


def test_run_init_menu_exits_without_creating_project(tmp_path, monkeypatch):
    monkeypatch.setattr(click.termui, "visible_prompt_func", lambda prompt="": "2")
    monkeypatch.setattr(project.sys, "platform", "win32")
    monkeypatch.chdir(tmp_path)
    called = []
    monkeypatch.setattr(setup_proj, "setup_project", lambda project_dir: called.append(project_dir))

    menu.run_init_menu()

    assert called == []
    assert not (tmp_path / ".inreach").exists()


def test_run_init_menu_creates_project_and_runs_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(click.termui, "visible_prompt_func", lambda prompt="": "1")
    monkeypatch.setattr(project.sys, "platform", "win32")
    monkeypatch.chdir(tmp_path)
    called = []
    monkeypatch.setattr(setup_proj, "setup_project", lambda project_dir: called.append(project_dir))

    menu.run_init_menu()

    assert called == [tmp_path / ".inreach"]
    assert (tmp_path / ".inreach" / ".env").exists()


def test_run_init_menu_removes_incomplete_project_on_system_exit(tmp_path, monkeypatch):
    monkeypatch.setattr(click.termui, "visible_prompt_func", lambda prompt="": "1")
    monkeypatch.setattr(project.sys, "platform", "win32")
    monkeypatch.chdir(tmp_path)

    def failing_setup(project_dir):
        raise SystemExit(1)

    monkeypatch.setattr(setup_proj, "setup_project", failing_setup)

    with pytest.raises(SystemExit):
        menu.run_init_menu()

    assert not (tmp_path / ".inreach").exists()


def test_run_init_menu_removes_incomplete_project_on_unexpected_error(tmp_path, monkeypatch):
    monkeypatch.setattr(click.termui, "visible_prompt_func", lambda prompt="": "1")
    monkeypatch.setattr(project.sys, "platform", "win32")
    monkeypatch.chdir(tmp_path)

    def failing_setup(project_dir):
        raise RuntimeError("boom")

    monkeypatch.setattr(setup_proj, "setup_project", failing_setup)

    with pytest.raises(RuntimeError):
        menu.run_init_menu()

    assert not (tmp_path / ".inreach").exists()


def test_run_init_menu_leaves_project_when_setup_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr(click.termui, "visible_prompt_func", lambda prompt="": "1")
    monkeypatch.setattr(project.sys, "platform", "win32")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(setup_proj, "setup_project", lambda project_dir: None)

    menu.run_init_menu()

    assert (tmp_path / ".inreach").exists()
