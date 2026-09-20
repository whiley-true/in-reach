"""Text-level edits to a script project (what a drag-and-drop board does): block order, module on/off, fragment moves."""
import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from hill_project import hill_rush

from in_reach import api
from in_reach.app.script_project import edit, link, load_project
from in_reach.cli import main


def _toml(folder: Path) -> str:
    return (folder / "script" / "project.toml").read_text(encoding="utf-8")


# -- block order -------------------------------------------------------------------------------------------------


def test_the_block_order_is_rewritten_and_the_link_follows_it(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "p")

    edit.set_block_order(folder, ["WIN_CHECK", "SETUP", "HILL_PASS"])

    assert load_project(folder).order == ["WIN_CHECK", "SETUP", "HILL_PASS"]
    assert link(folder, write=False).link_map["order"] == ["WIN_CHECK", "SETUP", "HILL_PASS"]


def test_editing_the_order_keeps_comments_and_everything_else(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "p")
    toml = folder / "script" / "project.toml"
    toml.write_text("# my project\n" + _toml(folder).replace("[constants]", "[constants]\n# the score to win\n"), encoding="utf-8")

    edit.set_block_order(folder, ["SETUP", "WIN_CHECK", "HILL_PASS"])

    text = _toml(folder)
    assert text.startswith("# my project") and "# the score to win" in text and "SCORE_TO_WIN = 50" in text
    assert text.count("[[modules]]") == 2


def test_the_order_is_written_even_when_there_was_no_blocks_table(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "p", project_dot_toml='[project]\nname = "x"\n')

    edit.set_block_order(folder, ["SETUP"])

    assert 'order = ["SETUP"]' in _toml(folder)


@pytest.mark.parametrize(("order", "message"), [(["setup"], "valid block name"), (["A", "A"], "listed twice"), (["A B"], "valid block name")])
def test_a_bad_order_is_refused_and_changes_nothing(tmp_path: Path, order: list[str], message: str) -> None:
    folder = hill_rush(tmp_path / "p")
    before = _toml(folder)

    with pytest.raises(edit.EditError, match=message):
        edit.set_block_order(folder, order)

    assert _toml(folder) == before


# -- modules on and off ---------------------------------------------------------------------------------------------


def test_a_disabled_module_contributes_nothing_but_stays_in_the_project(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "p")

    edit.set_module_enabled(folder, "hill_buff", False)
    result = link(folder, write=False)

    assert result.ok and "hill_buff" not in result.compiled and "t_hill_buff" not in result.compiled
    assert "-- HILL_PASS.score" in result.compiled  # hill_score's fragment is alone now, so no longer fused
    assert 'name = "hill_buff"' in _toml(folder) and "enabled = false" in _toml(folder)
    assert not [d for d in load_project(folder).diagnostics if d.code == "module-unlisted"]


def test_enabling_removes_the_key_and_brings_the_module_back(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "p")
    edit.set_module_enabled(folder, "hill_buff", False)

    edit.set_module_enabled(folder, "hill_buff", True)

    assert "enabled" not in _toml(folder)
    assert "t_hill_buff" in link(folder, write=False).compiled


def test_an_unknown_module_is_refused(tmp_path: Path) -> None:
    with pytest.raises(edit.EditError, match="isn't listed"):
        edit.set_module_enabled(hill_rush(tmp_path / "p"), "ghost", False)


def test_a_disabled_modules_resources_are_not_created(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "p")
    edit.set_module_enabled(folder, "hill_buff", False)

    link(folder)

    settings = folder / "settings" / "script_settings.json"
    assert not settings.exists() or "t_hill_buff" not in settings.read_text(encoding="utf-8")


# -- moving a fragment ------------------------------------------------------------------------------------------------


def test_moving_a_fragment_rewrites_only_its_header_line(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "p")
    module = folder / "script" / "modules" / "hill_score" / "hill_score.mgl"
    before = module.read_text(encoding="utf-8")

    changed = edit.move_fragment(folder, "hill_score.score", "WIN_CHECK")

    after = module.read_text(encoding="utf-8")
    assert changed == module
    assert after == before.replace("@fragment HILL_PASS.score", "@fragment WIN_CHECK.score")
    assert [b for b, f in [(f.block, f.id) for f in _fragments(folder)] if f == "hill_score.score"] == ["WIN_CHECK"]


def _fragments(folder: Path):
    from in_reach.app.script_project.model import build_model

    return build_model(load_project(folder)).fragments


def test_moving_a_fragment_to_a_new_block_creates_that_block(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "p")

    edit.move_fragment(folder, "hill_score.score", "BRAND_NEW")
    result = link(folder, write=False)

    assert result.ok and "BRAND_NEW" in result.link_map["order"]


def test_moving_a_fragment_where_it_already_is_changes_nothing(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "p")
    module = folder / "script" / "modules" / "hill_score" / "hill_score.mgl"
    before = module.read_bytes()

    edit.move_fragment(folder, "hill_score.score", "HILL_PASS")

    assert module.read_bytes() == before


def test_line_endings_survive_a_move(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "p")
    module = folder / "script" / "modules" / "hill_score" / "hill_score.mgl"
    module.write_bytes(module.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))

    edit.move_fragment(folder, "hill_score.score", "WIN_CHECK")

    data = module.read_bytes()
    assert b"@fragment WIN_CHECK.score\r\n" in data and b"\n" not in data.replace(b"\r\n", b"")


@pytest.mark.parametrize(("fragment", "block", "message"), [("ghost.f", "HILL_PASS", "no fragment ghost.f"), ("hill_score.score", "hill pass", "valid block name")])
def test_bad_moves_are_refused(tmp_path: Path, fragment: str, block: str, message: str) -> None:
    with pytest.raises(edit.EditError, match=message):
        edit.move_fragment(hill_rush(tmp_path / "p"), fragment, block)


def test_a_project_that_is_not_a_script_project_is_refused(tmp_path: Path) -> None:
    for call in (lambda: edit.set_block_order(tmp_path, ["A"]), lambda: edit.set_module_enabled(tmp_path, "a", False), lambda: edit.move_fragment(tmp_path, "a.b", "C")):
        with pytest.raises(edit.EditError, match="no script/project.toml"):
            call()


# -- api and command line ---------------------------------------------------------------------------------------------


def test_the_api_turns_edit_errors_into_api_errors_and_returns_relative_paths(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "p")

    assert api.move_fragment(folder, "hill_score.score", "WIN_CHECK") == "script/modules/hill_score/hill_score.mgl"
    with pytest.raises(api.ApiError):
        api.set_block_order(folder, ["bad name"])
    with pytest.raises(api.ApiError):
        api.set_module_enabled(folder, "ghost", True)


def test_the_commands_edit_the_composition(tmp_path: Path) -> None:
    runner = CliRunner()
    folder = hill_rush(tmp_path / "p")

    order = runner.invoke(main, ["block-order", "WIN_CHECK", "SETUP", "HILL_PASS", "--folder", str(folder), "--format", "json"])
    off = runner.invoke(main, ["module", "disable", "hill_buff", "--folder", str(folder)])
    on = runner.invoke(main, ["module", "enable", "hill_buff", "--folder", str(folder), "--format", "json"])
    moved = runner.invoke(main, ["move-fragment", "hill_score.score", "SETUP", "--folder", str(folder)])
    bad = runner.invoke(main, ["move-fragment", "ghost.f", "SETUP", "--folder", str(folder)])

    assert json.loads(order.output)["order"] == ["WIN_CHECK", "SETUP", "HILL_PASS"]
    assert "hill_buff: disabled" in off.output and json.loads(on.output)["enabled"] is True
    assert "moved hill_score.score to SETUP" in moved.output
    assert bad.exit_code == 1 and "no fragment ghost.f" in bad.output


def test_the_project_remembers_which_modules_are_switched_off(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "p")
    edit.set_module_enabled(folder, "hill_buff", False)

    project = load_project(folder)

    assert project.disabled_modules == ["hill_buff"] and [m.name for m in project.modules] == ["hill_score"]


def test_a_link_result_carries_the_model_for_front_ends_that_list_fragments(tmp_path: Path) -> None:
    result = link(hill_rush(tmp_path / "p"), write=False)

    assert [f.id for f in result.model.fragments_of("HILL_PASS")] == ["hill_score.score", "hill_buff.buff"]
