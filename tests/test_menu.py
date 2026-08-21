import click

from inreach.app.setup import menu, setup_proj


def test_run_init_menu_exits_without_running_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(click.termui, "visible_prompt_func", lambda prompt="": "2")
    called = []
    monkeypatch.setattr(setup_proj, "setup_project", lambda project_dir: called.append(project_dir))

    menu.run_init_menu(tmp_path)

    assert called == []


def test_run_init_menu_runs_setup_then_exits(tmp_path, monkeypatch):
    inputs = iter(["1", "2"])
    monkeypatch.setattr(click.termui, "visible_prompt_func", lambda prompt="": next(inputs))
    called = []
    monkeypatch.setattr(setup_proj, "setup_project", lambda project_dir: called.append(project_dir))

    menu.run_init_menu(tmp_path)

    assert called == [tmp_path]
