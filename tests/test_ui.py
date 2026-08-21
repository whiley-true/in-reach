import click

from inreach.app import ui


def test_select_option_returns_chosen_index(monkeypatch, capsys):
    inputs = iter(["2"])
    monkeypatch.setattr(click.termui, "visible_prompt_func", lambda prompt="": next(inputs))

    index = ui.select_option("Pick one", ["a", "b", "c"])

    assert index == 1
    assert "[2] b" in capsys.readouterr().out


def test_select_option_reprompts_on_invalid_input(monkeypatch):
    inputs = iter(["nope", "9", "1"])
    monkeypatch.setattr(click.termui, "visible_prompt_func", lambda prompt="": next(inputs))

    index = ui.select_option("Pick one", ["a", "b"])

    assert index == 0


def test_confirm_defaults_on_empty_input(monkeypatch):
    monkeypatch.setattr(click.termui, "visible_prompt_func", lambda prompt="": "")

    assert ui.confirm("Continue?", default=True) is True
    assert ui.confirm("Continue?", default=False) is False


def test_confirm_parses_yes_and_no(monkeypatch):
    inputs = iter(["y", "n"])
    monkeypatch.setattr(click.termui, "visible_prompt_func", lambda prompt="": next(inputs))

    assert ui.confirm("Continue?") is True
    assert ui.confirm("Continue?") is False
