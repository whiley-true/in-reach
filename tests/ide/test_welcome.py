from pathlib import Path

import pytest
from PyQt6.QtWidgets import QDialog

from in_reach.app import env_file, new_project, recent, system_verify
from in_reach.app.categories import EngineCategory
from in_reach.app.system_verify import Outcome, VerifyRun
from in_reach.ide.new_project_dialog import NewProjectDialog
from in_reach.ide.settings_info_dialog import SettingsInfoDialog
from in_reach.ide.verify_dialog import VerifyDialog
from in_reach.ide.welcome import WelcomeTab

_LOCALCONFIG = """
"UserLocalConfigStore" { "friends" { "PersonaName" "{persona}" } }
"""


@pytest.fixture
def root_dir(tmp_path: Path) -> Path:
    """A project root with an empty ``.in-reach/.env`` inside it."""
    (tmp_path / ".in-reach").mkdir()
    (tmp_path / ".in-reach" / ".env").write_text("", encoding="utf-8")
    return tmp_path


@pytest.fixture
def welcome(qtbot, root_dir: Path) -> WelcomeTab:
    tab = WelcomeTab(root_dir=root_dir)
    qtbot.addWidget(tab)
    return tab


def _step(env_key: str):
    return next(step for step in system_verify.STEPS if step.env_key == env_key)


def _set(root_dir: Path, key: str, value: str) -> None:
    env_file.update_env_value(root_dir / ".in-reach" / ".env", key, value)


# -- background --------------------------------------------------------------------------------


def test_scroll_area_uses_the_pane_background_not_the_window_background(welcome: WelcomeTab) -> None:
    # Regression guard: QScrollArea auto-fills its viewport using the Window palette role by
    # default, not Base -- which read as "the welcome page shows the IDE's own chrome color
    # instead of a pane's" (PROMPT.md). Both the scroll area and its separate viewport widget need
    # to be pinned to Base explicitly.
    from PyQt6.QtGui import QPalette
    from PyQt6.QtWidgets import QScrollArea

    scroll = welcome.findChild(QScrollArea)
    assert scroll is not None
    for widget in (scroll, scroll.viewport()):
        assert widget.backgroundRole() == QPalette.ColorRole.Base
        assert widget.autoFillBackground() is True


# -- the verify quadrant -----------------------------------------------------------------------------


def test_the_verify_quadrant_has_a_steam_tab_and_an_empty_custom_tab(welcome: WelcomeTab) -> None:
    labels = [welcome.verify_tabs.tabText(i) for i in range(welcome.verify_tabs.count())]

    assert labels == ["Steam (Halo MCC)", "Custom"]


def test_a_fresh_project_shows_zero_of_twelve_verified(welcome: WelcomeTab) -> None:
    total = len(system_verify.STEPS)
    assert welcome.verified_count_label.text() == f"0 of {total} settings verified."


def test_refresh_updates_the_count_as_the_env_gains_values(welcome: WelcomeTab, root_dir: Path) -> None:
    _set(root_dir, system_verify.STEAM_KEY, r"C:\Steam")

    welcome.refresh()

    total = len(system_verify.STEPS)
    assert welcome.verified_count_label.text() == f"1 of {total} settings verified."

    _set(root_dir, system_verify.HALO_MCC_KEY, r"C:\Steam\mcc")
    welcome.refresh()

    assert welcome.verified_count_label.text() == f"2 of {total} settings verified."


def test_clear_entries_resets_the_count_to_zero(welcome: WelcomeTab, root_dir: Path) -> None:
    for step in system_verify.STEPS:
        _set(root_dir, step.env_key, "value")
    welcome.refresh()
    total = len(system_verify.STEPS)
    assert welcome.verified_count_label.text() == f"{total} of {total} settings verified."

    welcome.clear_entries_button.click()

    assert welcome.verified_count_label.text() == f"0 of {total} settings verified."


def test_what_is_this_button_opens_the_settings_info_dialog(
    welcome: WelcomeTab, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[SettingsInfoDialog] = []

    def fake_exec(dialog: SettingsInfoDialog) -> int:
        opened.append(dialog)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(SettingsInfoDialog, "exec", fake_exec)

    welcome.what_is_this_button.click()

    assert len(opened) == 1
    assert opened[0].windowTitle() == "What is this?"


# -- the Start quadrant -----------------------------------------------------------------------------


def test_built_in_action_needs_both_standard_and_hopper_variants(welcome: WelcomeTab, root_dir: Path) -> None:
    assert welcome.new_builtin_button.isEnabled() is False

    _set(root_dir, system_verify.STANDARD_VARIANTS_KEY, r"C:\standard")
    welcome.refresh()
    assert welcome.new_builtin_button.isEnabled() is False

    _set(root_dir, system_verify.HOPPER_VARIANTS_KEY, r"C:\hopper")
    welcome.refresh()
    assert welcome.new_builtin_button.isEnabled() is True


def test_personal_action_needs_the_personal_variants_folder(welcome: WelcomeTab, root_dir: Path) -> None:
    assert welcome.new_personal_button.isEnabled() is False

    _set(root_dir, system_verify.PERSONAL_VARIANTS_KEY, r"C:\personal")
    welcome.refresh()

    assert welcome.new_personal_button.isEnabled() is True


def test_blank_and_load_are_always_available_and_pickle_import_is_stubbed(welcome: WelcomeTab) -> None:
    assert welcome.new_blank_button.isEnabled() is True
    assert welcome.load_project_button.isEnabled() is True
    assert welcome.import_pickle_button.isEnabled() is False


def test_new_blank_project_scaffolds_a_folder_and_lands_in_recent(
    welcome: WelcomeTab, root_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def accept(dialog: NewProjectDialog) -> int:
        dialog.title_edit.setText("Slayer Plus")
        dialog.description_edit.setText("A better slayer")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(NewProjectDialog, "exec", accept)
    opened: list[Path] = []
    welcome.project_opened.connect(opened.append)

    welcome.new_blank_button.click()

    assert len(opened) == 1
    folder = opened[0]
    # The folder is a generated id now, not the title -- see new_project.create_gametype_project.
    assert folder.parent == root_dir
    assert folder.name != "Slayer Plus"
    assert (folder / "settings").is_dir()
    assert new_project.read_project_title(folder) == "Slayer Plus"
    assert recent.list_recent(welcome.project_dir) == [folder]

    # PROMPT.md: RVT wasn't running for blank gametypes (there was no .bin at all to point it at)
    # -- a blank project now starts from in-reach's own bundled blank multiplayer template, so
    # there's always something for RVT to open and something that got decompiled into settings/.
    bin_path = new_project.source_variant_path(welcome.project_dir, folder)
    assert bin_path.is_file()
    assert (folder / "edit" / "rvt" / "script.txt").is_file()


def test_new_blank_firefight_project_starts_from_the_firefight_template_with_no_category(
    welcome: WelcomeTab, root_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from in_reach.app import blank_variant

    def accept(dialog: NewProjectDialog) -> int:
        dialog.title_edit.setText("Wave Defense")
        dialog.firefight_radio.setChecked(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(NewProjectDialog, "exec", accept)
    opened: list[Path] = []
    welcome.project_opened.connect(opened.append)

    welcome.new_blank_button.click()

    assert len(opened) == 1
    folder = opened[0]
    bin_path = new_project.source_variant_path(welcome.project_dir, folder)
    assert bin_path.read_bytes() == blank_variant.resolve_blank_variant(firefight=True).read_bytes()
    document = (folder / "settings" / "settings.json").read_text(encoding="utf-8")
    assert '"category": "none"' in document


def test_a_cancelled_new_project_dialog_creates_nothing(
    welcome: WelcomeTab, root_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(NewProjectDialog, "exec", lambda self: QDialog.DialogCode.Rejected)

    welcome.new_blank_button.click()

    assert list(root_dir.glob("*")) == [root_dir / ".in-reach"]


def test_a_category_icon_mismatch_warning_is_shown_but_does_not_block_creation(
    welcome: WelcomeTab, root_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def accept(dialog: NewProjectDialog) -> int:
        dialog.title_edit.setText("Odd Slayer")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(NewProjectDialog, "exec", accept)
    real_create = new_project.create_gametype_project

    def fake_create(*args, **kwargs):
        folder, _warning = real_create(*args, **kwargs)
        return folder, "Category and icon don't match."

    monkeypatch.setattr(new_project, "create_gametype_project", fake_create)
    shown: list[str] = []
    monkeypatch.setattr(
        "in_reach.ide.welcome.QMessageBox.warning", lambda *args, **kwargs: shown.append(args[2])
    )
    opened: list[Path] = []
    welcome.project_opened.connect(opened.append)

    welcome.new_blank_button.click()

    assert shown == ["Category and icon don't match."]
    assert len(opened) == 1


def test_new_project_from_a_built_in_variant_copies_it_in(
    welcome: WelcomeTab, root_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Decompiling isn't this test's concern (see test_new_project.py for that) -- these fixture
    # .bins are just placeholder bytes, not a real Reach variant, and the real native extension
    # failing to parse one would otherwise surface as a warning dialog mid-test.
    monkeypatch.setattr(new_project, "_decompile_source_variant", lambda *args, **kwargs: None)
    standard = root_dir / "game_variants"
    hopper = root_dir / "hopper_game_variants"
    standard.mkdir()
    hopper.mkdir()
    (standard / "Slayer.bin").write_bytes(b"\x00slayer")
    (hopper / "Team Slayer.bin").write_bytes(b"\x00team")
    _set(root_dir, system_verify.STANDARD_VARIANTS_KEY, str(standard))
    _set(root_dir, system_verify.HOPPER_VARIANTS_KEY, str(hopper))
    welcome.refresh()

    captured: list[NewProjectDialog] = []

    def accept(dialog: NewProjectDialog) -> int:
        captured.append(dialog)
        dialog.title_edit.setText("From Slayer")
        dialog.variant_combo.setCurrentIndex(dialog.variant_combo.findText("Standard: Slayer"))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(NewProjectDialog, "exec", accept)
    opened: list[Path] = []
    welcome.project_opened.connect(opened.append)

    welcome.new_builtin_button.click()

    assert [captured[0].variant_combo.itemText(i) for i in range(captured[0].variant_combo.count())] == [
        "Standard: Slayer",
        "Hopper: Team Slayer",
    ]
    folder = opened[0]
    copied = welcome.project_dir / new_project.INIT_GAMETYPE_DIRNAME / f"{folder.name}.bin"
    assert copied.read_bytes() == b"\x00slayer"


def test_new_project_from_an_empty_variant_folder_says_so(
    welcome: WelcomeTab, root_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    personal = root_dir / "personal"
    personal.mkdir()
    _set(root_dir, system_verify.PERSONAL_VARIANTS_KEY, str(personal))
    welcome.refresh()
    shown: list[str] = []
    monkeypatch.setattr(
        "in_reach.ide.welcome.QMessageBox.information", lambda *args, **kwargs: shown.append(args[2])
    )
    monkeypatch.setattr(NewProjectDialog, "exec", lambda self: pytest.fail("should not have opened"))

    welcome.new_personal_button.click()

    assert len(shown) == 1
    assert "No game variants" in shown[0]


def test_load_project_adds_the_chosen_folder_to_recent(
    welcome: WelcomeTab, root_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    existing = root_dir / "Existing Project"
    existing.mkdir()
    monkeypatch.setattr(WelcomeTab, "ask_project_folder", lambda self: str(existing))

    welcome.load_project_button.click()

    assert recent.list_recent(welcome.project_dir) == [existing]


def test_cancelling_the_load_picker_changes_nothing(
    welcome: WelcomeTab, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(WelcomeTab, "ask_project_folder", lambda self: "")

    welcome.load_project_button.click()

    assert recent.list_recent(welcome.project_dir) == []


# -- the Recent quadrant ----------------------------------------------------------------------------


def test_recent_shows_a_placeholder_until_there_is_something_to_show(
    welcome: WelcomeTab, root_dir: Path
) -> None:
    assert welcome._recent_empty_label.isHidden() is False

    existing = root_dir / "Existing Project"
    existing.mkdir()
    recent.add_recent(welcome.project_dir, existing)
    welcome.refresh()

    assert welcome._recent_empty_label.isHidden() is True


def test_clicking_a_recent_entry_reopens_it(welcome: WelcomeTab, root_dir: Path) -> None:
    older = root_dir / "Older"
    newer = root_dir / "Newer"
    older.mkdir()
    newer.mkdir()
    recent.add_recent(welcome.project_dir, older)
    recent.add_recent(welcome.project_dir, newer)
    welcome.refresh()
    opened: list[Path] = []
    welcome.project_opened.connect(opened.append)

    buttons = [
        welcome._recent_layout.itemAt(i).widget() for i in range(1, welcome._recent_layout.count())
    ]
    assert [button.text() for button in buttons] == [" Newer", " Older"]
    buttons[1].click()

    assert opened == [older]
    # Reopening it moves it back to the front.
    assert recent.list_recent(welcome.project_dir) == [older, newer]


# -- the New Project dialog -------------------------------------------------------------------------


def test_new_project_dialog_gates_create_on_a_non_empty_title(qtbot) -> None:
    from PyQt6.QtWidgets import QDialogButtonBox

    dialog = NewProjectDialog()
    qtbot.addWidget(dialog)
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)

    assert ok.isEnabled() is False
    # No longer folder-name rules -- characters a Windows folder name would reject are fine now,
    # since the title no longer names the project folder (see new_project.is_valid_title).
    dialog.title_edit.setText("no/slashes: needed <now>?")
    assert ok.isEnabled() is True
    dialog.title_edit.setText("   ")
    assert ok.isEnabled() is False


def test_new_project_dialog_title_help_stays_visible_and_only_its_emphasis_changes(qtbot) -> None:
    # Regression guard: the helper text used to vanish entirely (setVisible(False)) the moment a
    # single keystroke made the title technically valid -- jarring since almost any first letter
    # already qualifies. It should stay put the whole time; only its emphasis (muted once valid,
    # full contrast while not) should change.
    dialog = NewProjectDialog()
    qtbot.addWidget(dialog)

    assert dialog.title_help_label.isHidden() is False
    assert dialog.title_help_label.isEnabled() is True  # empty title -- shown as an active rule

    dialog.title_edit.setText("Slayer Plus")
    assert dialog.title_help_label.isHidden() is False
    assert dialog.title_help_label.isEnabled() is False  # valid now -- muted, not gone

    dialog.title_edit.setText("")
    assert dialog.title_help_label.isEnabled() is True


def test_new_project_dialog_hides_the_variant_chooser_for_a_blank_project(qtbot) -> None:
    dialog = NewProjectDialog()
    qtbot.addWidget(dialog)

    assert dialog.selected_variant() is None
    assert dialog.variant_combo.isVisibleTo(dialog) is False


def test_new_project_dialog_returns_the_chosen_variant(qtbot, tmp_path: Path) -> None:
    dialog = NewProjectDialog(variants=[("Slayer", tmp_path / "Slayer.bin")])
    qtbot.addWidget(dialog)

    assert dialog.selected_variant() == tmp_path / "Slayer.bin"


def test_new_project_dialog_asks_game_type_only_for_a_blank_project(qtbot) -> None:
    dialog = NewProjectDialog(ask_game_type=True)
    qtbot.addWidget(dialog)

    assert dialog.multiplayer_radio.isChecked() is True
    assert dialog.is_firefight() is False
    assert dialog.category_combo.isVisibleTo(dialog) is True

    dialog.firefight_radio.setChecked(True)

    assert dialog.is_firefight() is True
    assert dialog.category_combo.isVisibleTo(dialog) is False
    assert dialog.category() == EngineCategory.none


def test_new_project_dialog_without_ask_game_type_has_no_game_type_picker(qtbot) -> None:
    dialog = NewProjectDialog()
    qtbot.addWidget(dialog)

    assert dialog.is_firefight() is False
    assert not hasattr(dialog, "multiplayer_radio")


def test_new_project_dialog_resolves_a_blank_variant_for_multiplayer_by_default(qtbot) -> None:
    from in_reach.app import blank_variant

    dialog = NewProjectDialog(ask_game_type=True)
    qtbot.addWidget(dialog)

    assert dialog.selected_variant() == blank_variant.resolve_blank_variant(firefight=False)

    dialog.firefight_radio.setChecked(True)

    assert dialog.selected_variant() == blank_variant.resolve_blank_variant(firefight=True)


def test_description_field_caps_at_137_characters_and_takes_any_text(qtbot) -> None:
    dialog = NewProjectDialog()
    qtbot.addWidget(dialog)

    assert dialog.description_edit.maxLength() == new_project.MAX_DESCRIPTION_LENGTH == 137

    # Unlike the title, the description isn't used as a folder name -- characters Windows forbids
    # in a filename are perfectly fine here.
    dialog.title_edit.setText("Slayer Plus")
    dialog.description_edit.setText('Slayer, but: faster / stronger * "better"?')

    assert dialog.description() == 'Slayer, but: faster / stronger * "better"?'
    from PyQt6.QtWidgets import QDialogButtonBox

    assert dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled() is True


def test_description_help_shows_a_live_character_count(qtbot) -> None:
    dialog = NewProjectDialog()
    qtbot.addWidget(dialog)

    assert dialog.description_help_label.text() == "0/137 characters"

    dialog.description_edit.setText("Slayer Plus")

    assert dialog.description_help_label.text() == "11/137 characters"


def test_description_help_is_muted_until_the_field_is_focused(qtbot) -> None:
    dialog = NewProjectDialog()
    qtbot.addWidget(dialog)
    dialog.show()

    assert dialog.description_help_label.isEnabled() is False

    dialog.description_edit.setFocus()
    qtbot.waitUntil(lambda: dialog.description_edit.hasFocus(), timeout=2000)
    assert dialog.description_help_label.isEnabled() is True

    dialog.title_edit.setFocus()
    qtbot.waitUntil(lambda: dialog.title_edit.hasFocus(), timeout=2000)
    assert dialog.description_help_label.isEnabled() is False


def test_variant_dropdown_caps_its_visible_item_count(qtbot, tmp_path: Path) -> None:
    variants = [(f"Variant {i}", tmp_path / f"v{i}.bin") for i in range(30)]
    dialog = NewProjectDialog(variants=variants)
    qtbot.addWidget(dialog)

    assert dialog.variant_combo.maxVisibleItems() <= 12


def test_variant_dropdown_is_editable_and_searchable(qtbot, tmp_path: Path) -> None:
    variants = [("Slayer", tmp_path / "Slayer.bin"), ("Oddball", tmp_path / "Oddball.bin")]
    dialog = NewProjectDialog(variants=variants)
    qtbot.addWidget(dialog)

    assert dialog.variant_combo.isEditable() is True
    assert dialog.variant_combo.completer() is not None
    assert dialog.variant_combo.insertPolicy() == dialog.variant_combo.InsertPolicy.NoInsert


# -- the Verify Now popout --------------------------------------------------------------------------


def _dialog_for(qtbot, root_dir: Path, **run_kwargs) -> VerifyDialog:
    project_dir = root_dir / ".in-reach"
    # Every default has to point somewhere empty, or a machine that really does have Steam/
    # Tesseract installed would resolve steps these tests need to leave unresolved.
    run = VerifyRun(
        project_dir, home=root_dir / "home", steam_default=root_dir / "no-steam-here", **run_kwargs
    )
    dialog = VerifyDialog(project_dir, run=run)
    qtbot.addWidget(dialog)
    return dialog


def test_verify_dialog_walks_every_step_and_reports_what_it_could_not_find(
    qtbot, root_dir: Path
) -> None:
    dialog = _dialog_for(qtbot, root_dir, which=lambda _name: None)

    # Nothing exists under this test's fake home/Program Files, so every step parks on MISSING and
    # gets skipped -- which is the run reaching the end without a single answer being invented.
    for _ in system_verify.STEPS:
        dialog.process_next_step()
        assert dialog.manual_button.isVisibleTo(dialog) is True
        dialog.skip_step()
    dialog.process_next_step()

    assert dialog.close_button.text() == "Done"
    assert dialog.detail_label.text() == f"0 of {len(system_verify.STEPS)} steps verified."
    assert dialog.results_list.count() == len(system_verify.STEPS)
    assert not any(system_verify.verified_keys(root_dir / ".in-reach").values())


def test_verify_dialog_accepts_a_resolved_step_without_asking(qtbot, root_dir: Path) -> None:
    exe = root_dir / "tesseract.exe"
    exe.write_text("", encoding="utf-8")
    dialog = _dialog_for(qtbot, root_dir, which=lambda _name: str(exe))

    dialog.process_next_step()

    assert dialog.manual_button.isVisibleTo(dialog) is False
    values = env_file.get_env_values(root_dir / ".in-reach" / ".env")
    assert values[system_verify.TESSERACT_KEY] == str(exe)
    assert dialog.results_list.item(0).text().startswith("✓")


def test_verify_dialog_shows_the_help_tip_for_a_step_that_has_one(qtbot, root_dir: Path) -> None:
    dialog = _dialog_for(qtbot, root_dir, which=lambda _name: None)

    dialog.process_next_step()

    assert dialog.hint_label.isVisibleTo(dialog) is True
    assert "winget" in dialog.hint_label.text()


def test_verify_dialog_does_not_grow_when_a_step_reveals_the_hint_or_choice_controls(
    qtbot, root_dir: Path
) -> None:
    # Regression guard: the dialog used to only grow into the hint_label/choice_combo's own space
    # partway through a run, which Windows can't always resize into cleanly (a noisy but harmless
    # "QWindowsWindow::setGeometry: Unable to set geometry" warning). Height is reserved for both
    # up front now, so the outer window stays a fixed height across the whole run.
    dialog = _dialog_for(qtbot, root_dir, which=lambda _name: None)
    height_before = dialog.height()

    dialog.process_next_step()  # reveals hint_label for the winget step

    assert dialog.hint_label.isVisibleTo(dialog) is True
    assert dialog.height() == height_before


def test_verify_dialog_offers_detected_steam_users_as_a_choice(qtbot, root_dir: Path) -> None:
    steam = root_dir / "Steam"
    for account_id, persona in (("111", "Whiley"), ("222", "Someone Else")):
        config = steam / "userdata" / account_id / "config"
        config.mkdir(parents=True)
        (config / "localconfig.vdf").write_text(
            _LOCALCONFIG.replace("{persona}", persona), encoding="utf-8"
        )
    _set(root_dir, system_verify.STEAM_KEY, str(steam))
    dialog = _dialog_for(qtbot, root_dir, which=lambda _name: None)
    dialog._index = list(system_verify.STEPS).index(_step(system_verify.STEAM_ACCOUNT_KEY))

    dialog.process_next_step()

    assert dialog.choice_combo.isVisibleTo(dialog) is True
    assert dialog.use_button.isVisibleTo(dialog) is True
    assert dialog.manual_button.isVisibleTo(dialog) is False
    assert [dialog.choice_combo.itemText(i) for i in range(dialog.choice_combo.count())] == [
        "Whiley (111)",
        "Someone Else (222)",
    ]
    assert "More than one Steam account" in dialog.hint_label.text()

    dialog.choice_combo.setCurrentIndex(1)
    dialog.use_button.click()

    values = env_file.get_env_values(root_dir / ".in-reach" / ".env")
    assert values[system_verify.STEAM_ACCOUNT_KEY] == "222"
    assert values[system_verify.USER_STEAM_PROFILE_NAME_KEY] == "Someone Else"


def test_verify_dialog_lets_a_missing_location_be_set_manually(
    qtbot, root_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chosen = root_dir / "Elsewhere" / "Steam"
    chosen.mkdir(parents=True)
    dialog = _dialog_for(qtbot, root_dir, which=lambda _name: None)
    dialog._index = list(system_verify.STEPS).index(_step(system_verify.STEAM_KEY))
    monkeypatch.setattr(VerifyDialog, "ask_directory", lambda self, start_at: str(chosen))

    dialog.process_next_step()
    assert dialog.pending_result().outcome == Outcome.MISSING
    dialog.manual_button.click()

    assert env_file.get_env_values(root_dir / ".in-reach" / ".env")[system_verify.STEAM_KEY] == str(chosen)


def test_verify_dialog_leaves_a_step_parked_when_the_manual_picker_is_cancelled(
    qtbot, root_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dialog = _dialog_for(qtbot, root_dir, which=lambda _name: None)
    dialog._index = list(system_verify.STEPS).index(_step(system_verify.STEAM_KEY))
    monkeypatch.setattr(VerifyDialog, "ask_directory", lambda self, start_at: "")

    dialog.process_next_step()
    dialog.manual_button.click()

    assert dialog.results_list.count() == 0
    assert dialog.manual_button.isVisibleTo(dialog) is True
    assert env_file.get_env_values(root_dir / ".in-reach" / ".env").get(system_verify.STEAM_KEY, "") == ""


def test_verify_dialog_stores_a_manually_picked_steam_account_by_id_not_by_path(
    qtbot, root_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = root_dir / "Steam" / "userdata" / "333"
    account.mkdir(parents=True)
    dialog = _dialog_for(qtbot, root_dir, which=lambda _name: None)
    dialog._index = list(system_verify.STEPS).index(_step(system_verify.STEAM_ACCOUNT_KEY))
    monkeypatch.setattr(VerifyDialog, "ask_directory", lambda self, start_at: str(account))

    dialog.process_next_step()
    dialog.manual_button.click()

    assert env_file.get_env_values(root_dir / ".in-reach" / ".env")[system_verify.STEAM_ACCOUNT_KEY] == "333"


def test_verify_now_refreshes_the_count_when_the_run_finishes(
    welcome: WelcomeTab, root_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_exec(dialog: VerifyDialog) -> int:
        _set(root_dir, system_verify.STEAM_KEY, r"C:\Steam")
        dialog.run_finished.emit()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(VerifyDialog, "start", lambda self: None)
    monkeypatch.setattr(VerifyDialog, "exec", fake_exec)

    welcome.verify_now_button.click()

    total = len(system_verify.STEPS)
    assert welcome.verified_count_label.text() == f"1 of {total} settings verified."
