import click

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
