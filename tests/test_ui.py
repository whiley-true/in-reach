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


def test_press_enter_returns_on_empty_input(monkeypatch, capsys):
    monkeypatch.setattr(click.termui, "visible_prompt_func", lambda prompt="": "")

    ui.press_enter("Press enter to confirm")

    assert "Press enter to confirm" in capsys.readouterr().out


def test_confirm_parses_yes_and_no(monkeypatch):
    inputs = iter(["y", "n"])
    monkeypatch.setattr(click.termui, "visible_prompt_func", lambda prompt="": next(inputs))

    assert ui.confirm("Continue?") is True
    assert ui.confirm("Continue?") is False


def test_checklist_ticks_off_found_items_and_returns_missing(capsys):
    found = {"a": "somewhere", "c": "elsewhere"}
    items = [("a", "Item A"), ("b", "Item B"), ("c", "Item C")]

    missing = ui.checklist("Checking things", items, lambda key: found.get(key), delay=0)

    assert missing == ["b"]
    out = capsys.readouterr().out
    assert "[x] Item A - found at somewhere" in out
    assert "[ ] Item B - not found" in out
    assert "[x] Item C - found at elsewhere" in out


def test_checklist_waits_delay_seconds_between_items(monkeypatch):
    sleeps = []
    monkeypatch.setattr(ui.time, "sleep", sleeps.append)
    items = [("a", "Item A"), ("b", "Item B")]

    ui.checklist("Checking things", items, lambda key: "found", delay=0.5)

    assert sleeps == [0.5, 0.5]


def test_clear_screen_noop_when_not_a_tty(monkeypatch, capsys):
    monkeypatch.setattr(ui.sys.stdout, "isatty", lambda: False)

    ui.clear_screen()

    assert capsys.readouterr().out == ""


def test_clear_screen_writes_ansi_sequence_when_tty(monkeypatch, capsys):
    monkeypatch.setattr(ui.sys.stdout, "isatty", lambda: True)

    ui.clear_screen()

    assert capsys.readouterr().out == "\x1b[3J\x1b[2J\x1b[H"
