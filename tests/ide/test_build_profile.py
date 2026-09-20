"""The "Select Build Profile" command palette entry -- the way a user picks which
``script/env/<name>.env`` profile the active project builds with (see
:mod:`in_reach.app.script_preprocess`), rather than hand-editing ``active_profile.txt``."""
import json
from pathlib import Path

import pytest

from in_reach.app import output_view, script_preprocess
from in_reach.ide.main_window import MainWindow


@pytest.fixture
def project_window(qtbot, tmp_path: Path):
    project_dir = tmp_path / ".in-reach"
    project_dir.mkdir()
    (project_dir / ".env").write_text("", encoding="utf-8")
    win = MainWindow(root_dir=tmp_path)
    qtbot.addWidget(win)
    win.show()
    return win


def _project(tmp_path: Path, *profiles: str) -> Path:
    folder = tmp_path / "abcd1234"
    (folder / "settings").mkdir(parents=True)
    (folder / "settings" / "settings.json").write_text(json.dumps({"meta": {"title": "T"}}), encoding="utf-8")
    (folder / "script" / "env").mkdir(parents=True)
    for name in profiles:
        (folder / "script" / "env" / f"{name}.env").write_text("FLAGS=DEV\nSCORE=5\n", encoding="utf-8")
    return folder


def _command(window: MainWindow):
    return next(c for c in window.build_command_palette_commands() if c.label == "Select Build Profile")


def _details(command) -> dict[str, str]:
    return {child.label: child.detail for child in command.children}


def test_the_palette_lists_this_projects_profiles_and_a_no_profile_choice(project_window, tmp_path: Path) -> None:
    project_window._on_project_opened(_project(tmp_path, "release", "dev"))

    labels = [child.label for child in _command(project_window).children]

    assert labels == ["dev", "release", "No profile"]


def test_with_nothing_chosen_no_profile_is_marked_active(project_window, tmp_path: Path) -> None:
    project_window._on_project_opened(_project(tmp_path, "dev", "release"))
    assert _details(_command(project_window)) == {"dev": "", "release": "", "No profile": "active"}


def test_picking_a_profile_makes_it_the_one_the_project_builds_with(project_window, tmp_path: Path) -> None:
    folder = _project(tmp_path, "dev", "release")
    project_window._on_project_opened(folder)

    next(c for c in _command(project_window).children if c.label == "release").action()

    assert script_preprocess.active_profile_name(folder) == "release"


def test_the_active_profile_is_marked_the_next_time_the_palette_opens(project_window, tmp_path: Path) -> None:
    project_window._on_project_opened(_project(tmp_path, "dev", "release"))
    next(c for c in _command(project_window).children if c.label == "dev").action()

    assert _details(_command(project_window)) == {"dev": "active", "release": "", "No profile": ""}


def test_picking_no_profile_clears_the_choice(project_window, tmp_path: Path) -> None:
    folder = _project(tmp_path, "dev")
    project_window._on_project_opened(folder)
    script_preprocess.set_active_profile(folder, "dev")

    next(c for c in _command(project_window).children if c.label == "No profile").action()

    assert script_preprocess.active_profile_name(folder) is None


def test_the_choice_actually_changes_what_the_compiled_view_shows(project_window, tmp_path: Path) -> None:
    folder = _project(tmp_path, "dev")
    (folder / "script" / "output.txt").write_text("-- @if DEV\ndebug()\n-- @end\nwin = ${SCORE}\n", encoding="utf-8")
    (folder / "script" / "env" / "release.env").write_text("SCORE=50\n", encoding="utf-8")
    project_window._on_project_opened(folder)

    next(c for c in _command(project_window).children if c.label == "release").action()
    text = output_view.write_output_view(folder).read_text(encoding="utf-8")

    assert "win = 50" in text and "debug()" not in text


def test_a_project_with_no_profiles_offers_nothing_to_pick(project_window, tmp_path: Path) -> None:
    project_window._on_project_opened(_project(tmp_path))
    assert _command(project_window).children == []


def test_with_no_project_open_there_is_nothing_to_pick(project_window) -> None:
    assert _command(project_window).children == []


def test_choosing_with_no_project_open_is_a_no_op(project_window) -> None:
    project_window._set_build_profile("dev")  # must not raise


def test_a_profile_whose_file_vanished_since_the_palette_opened_is_logged_not_raised(
    project_window, tmp_path: Path
) -> None:
    folder = _project(tmp_path, "dev")
    project_window._on_project_opened(folder)
    stale = next(c for c in _command(project_window).children if c.label == "dev")
    (folder / "script" / "env" / "dev.env").unlink()

    stale.action()  # the entry is now stale; must not raise

    assert script_preprocess.active_profile_name(folder) is None


# -- the status bar's profile indicator -------------------------------------------------------------------------


def _indicator(window: MainWindow):
    return window.status_bar.profile_label


def test_the_indicator_is_hidden_with_no_project_open(project_window) -> None:
    assert _indicator(project_window).isHidden()


def test_the_indicator_shows_the_active_profile_when_a_project_with_profiles_opens(project_window, tmp_path: Path) -> None:
    folder = _project(tmp_path, "dev", "release")
    script_preprocess.set_active_profile(folder, "release")

    project_window._on_project_opened(folder)

    assert not _indicator(project_window).isHidden()
    assert _indicator(project_window).text() == "Profile: release"


def test_the_indicator_says_so_when_profiles_exist_but_none_is_chosen(project_window, tmp_path: Path) -> None:
    project_window._on_project_opened(_project(tmp_path, "dev", "release"))
    assert _indicator(project_window).text() == "No profile"


def test_the_indicator_is_hidden_for_a_project_with_no_profiles(project_window, tmp_path: Path) -> None:
    project_window._on_project_opened(_project(tmp_path))
    assert _indicator(project_window).isHidden()


def test_picking_a_profile_updates_the_indicator_at_once(project_window, tmp_path: Path) -> None:
    project_window._on_project_opened(_project(tmp_path, "dev", "release"))

    next(c for c in _command(project_window).children if c.label == "dev").action()
    assert _indicator(project_window).text() == "Profile: dev"

    next(c for c in _command(project_window).children if c.label == "No profile").action()
    assert _indicator(project_window).text() == "No profile"


def test_closing_the_project_hides_the_indicator_again(project_window, tmp_path: Path) -> None:
    folder = _project(tmp_path, "dev")
    script_preprocess.set_active_profile(folder, "dev")
    project_window._on_project_opened(folder)
    assert not _indicator(project_window).isHidden()

    project_window.close_project()

    assert _indicator(project_window).isHidden()


def test_editing_the_active_profile_pointer_and_saving_refreshes_the_indicator(project_window, tmp_path: Path, qtbot) -> None:
    folder = _project(tmp_path, "dev", "release")
    script_preprocess.set_active_profile(folder, "dev")
    project_window._on_project_opened(folder)
    pointer = folder / "script" / "env" / script_preprocess.ACTIVE_PROFILE_FILENAME

    pointer.write_text("release\n", encoding="utf-8")  # e.g. edited by hand in the editor
    project_window._on_file_saved(pointer)

    assert _indicator(project_window).text() == "Profile: release"


def test_clicking_the_indicator_opens_the_same_pick_as_the_palette(project_window, tmp_path: Path, monkeypatch) -> None:
    project_window._on_project_opened(_project(tmp_path, "dev", "release"))
    opened = []
    monkeypatch.setattr(project_window.quick_access, "open_action_list", lambda commands, heading="": opened.append((commands, heading)))

    _indicator(project_window)._on_click()

    [(commands, heading)] = opened
    assert heading == "Select Build Profile"
    assert [c.label for c in commands] == ["dev", "release", "No profile"]


def test_clicking_the_indicator_for_a_project_that_lost_its_profiles_opens_nothing(project_window, tmp_path: Path, monkeypatch) -> None:
    folder = _project(tmp_path, "dev")
    project_window._on_project_opened(folder)
    opened = []
    monkeypatch.setattr(project_window.quick_access, "open_action_list", lambda *a, **k: opened.append(a))
    (folder / "script" / "env" / "dev.env").unlink()

    _indicator(project_window)._on_click()

    assert opened == []


# -- stamping a release from a profile that isn't the release one --------------------------------------------


def _stampable(project_window, tmp_path: Path, *profiles: str) -> Path:
    folder = _project(tmp_path, *profiles)
    project_window._on_project_opened(folder)
    return folder


def test_stamping_off_the_release_profile_asks_first_and_cancelling_stamps_nothing(project_window, tmp_path: Path, monkeypatch) -> None:
    folder = _stampable(project_window, tmp_path, "dev", "release")
    script_preprocess.set_active_profile(folder, "dev")
    asked, stamped = [], []
    monkeypatch.setattr(project_window, "_confirm_stamp_off_release_profile", lambda active: asked.append(active) or False)
    monkeypatch.setattr("in_reach.app.vcs.stamp", lambda *a, **k: stamped.append(a))

    project_window.vcs_stamp("first", "0.1.0")

    assert asked == ["dev"] and stamped == []


def test_stamping_anyway_stamps(project_window, tmp_path: Path, monkeypatch) -> None:
    folder = _stampable(project_window, tmp_path, "dev", "release")
    stamped = []
    monkeypatch.setattr(project_window, "_confirm_stamp_off_release_profile", lambda active: True)
    monkeypatch.setattr("in_reach.app.vcs.stamp", lambda *a, **k: stamped.append((a, k)))

    project_window.vcs_stamp("first", "0.1.0")

    assert stamped == [((folder, "first"), {"version": "0.1.0"})]
    assert script_preprocess.active_profile_name(folder) is None  # nothing was switched behind the user's back


def test_stamping_on_the_release_profile_does_not_ask(project_window, tmp_path: Path, monkeypatch) -> None:
    folder = _stampable(project_window, tmp_path, "dev", "release")
    script_preprocess.set_active_profile(folder, "release")
    stamped = []
    monkeypatch.setattr(project_window, "_confirm_stamp_off_release_profile", lambda active: pytest.fail("asked"))
    monkeypatch.setattr("in_reach.app.vcs.stamp", lambda *a, **k: stamped.append(a))

    project_window.vcs_stamp("first", "0.1.0")

    assert len(stamped) == 1


@pytest.mark.parametrize("profiles", [(), ("dev",), ("dev", "staging")])
def test_a_project_with_no_release_profile_is_never_asked(project_window, tmp_path: Path, monkeypatch, profiles) -> None:
    _stampable(project_window, tmp_path, *profiles)
    stamped = []
    monkeypatch.setattr(project_window, "_confirm_stamp_off_release_profile", lambda active: pytest.fail("asked"))
    monkeypatch.setattr("in_reach.app.vcs.stamp", lambda *a, **k: stamped.append(a))

    project_window.vcs_stamp("first", "0.1.0")

    assert len(stamped) == 1


def test_the_warning_names_the_profile_in_use_or_says_none(project_window, monkeypatch) -> None:
    from PyQt6.QtWidgets import QMessageBox

    texts = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: texts.append(self.text()) or 0)

    project_window._confirm_stamp_off_release_profile("dev")
    project_window._confirm_stamp_off_release_profile(None)

    assert texts == ["The active build profile is 'dev', not 'release'.", "No build profile is active, not 'release'."]
