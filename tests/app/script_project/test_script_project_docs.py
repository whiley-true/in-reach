"""Documentation generated from the script (:mod:`in_reach.app.script_project.docs`, ``api.docs``, ``in-reach docs``):
``@doc`` notes attached to what they document, ``@tags`` indexed, READMEs, and what the linker decided."""
import json
from pathlib import Path

from click.testing import CliRunner
from hill_project import hill_rush

from in_reach import api
from in_reach.app.rvt.megalo_ast.annotations import parse_annotations
from in_reach.app.script_project import link
from in_reach.app.script_project.docs import build_docs, docs_dir, render_markdown, write_docs
from in_reach.app.script_project.edit import set_module_enabled
from in_reach.cli import main

# A single file names its own slots (a script project is what picks them), so its notes sit on code.
_SCRIPT = """-- @tags scoring, hud
-- @doc First to five wins.
-- @see scoring

-- @doc The leader's score, shown on the HUD.
declare global.number[0] with network priority low
for each player do
   -- @doc Ends the round at five.
   if current_player.score >= 5 then
      game.end_round()
   end
end
"""

# The design example's setup block, with notes beside its declarations.
_SETUP_WITH_NOTES = (
    "-- @number g_phase priority=low\n"
    "-- @doc Which phase of the round it is.\n"
    "on init: do\n"
    "   g_phase = 0\n"
    "end\n"
)


def _single(tmp_path: Path, text: str = _SCRIPT) -> Path:
    (tmp_path / "script").mkdir()
    (tmp_path / "script" / "output.mgl").write_text(text, encoding="utf-8")
    return tmp_path


# -- @tags --------------------------------------------------------------------------------------------------


def test_tags_take_commas_or_spaces_and_drop_repeats() -> None:
    [tags] = parse_annotations("-- @tags scoring, hud game-mode hud\n").items
    assert tags.tags == ["scoring", "hud", "game-mode"]


def test_tags_need_at_least_one_plain_tag() -> None:
    result = parse_annotations('-- @tags\n-- @tags "quoted"\n')
    assert [d.span.start_line for d in result.diagnostics] == [1, 2]


def test_see_can_name_a_fragment() -> None:
    [see] = parse_annotations("-- @see hill_score.score\n").items
    assert see.tag == "hill_score.score"


def test_tags_see_and_doc_are_fine_in_a_single_file(tmp_path: Path) -> None:
    assert link(_single(tmp_path), write=False).diagnostics == []


def test_a_see_that_points_at_nothing_is_a_warning(tmp_path: Path) -> None:
    result = link(_single(tmp_path, "-- @see nowhere\ngame.end_round()\n"), write=False)
    assert result.ok and [(d.severity, d.code, d.line) for d in result.diagnostics] == [("warning", "see-unknown", 1)]


# -- notes --------------------------------------------------------------------------------------------------


def test_each_note_is_attached_to_what_it_documents(tmp_path: Path) -> None:
    docs = build_docs(_single(tmp_path))

    assert [(n.kind, n.subject, n.line) for n in docs.notes] == [
        ("file", "output.mgl", 2),  # a blank line follows its run
        ("code", "declare global.number[0] with network priority low", 5),  # right above code
        ("code", "if current_player.score >= 5 then", 8),
    ]
    assert docs.mode == "single" and docs.tags == {"hud": ["file output.mgl"], "scoring": ["file output.mgl"]}
    [see] = docs.files[0].see
    assert (see.target, see.resolves_to) == ("scoring", "tag")
    assert docs.storage == []  # nothing is allocated for a single file


def test_storage_carries_its_slot_and_its_note(tmp_path: Path) -> None:
    docs = build_docs(hill_rush(tmp_path, blocks__setup_dot_mgl=_SETUP_WITH_NOTES))

    [phase] = [entry for entry in docs.storage if entry["name"] == "g_phase"]
    assert phase == {"slot": "global.number[1]", "owner": "blocks/setup.mgl", "name": "g_phase", "doc": "Which phase of the round it is."}


def test_a_note_of_several_lines_keeps_them(tmp_path: Path) -> None:
    docs = build_docs(_single(tmp_path, "-- @doc one\n-- @doc two\ngame.end_round()\n"))
    assert docs.notes[0].text == "one\ntwo"


def test_the_markdown_overview_of_a_single_file(tmp_path: Path) -> None:
    folder = _single(tmp_path)
    (folder / "script" / "README.md").write_text("# Race to five\n\nA tiny mode.\n", encoding="utf-8")

    text = render_markdown(build_docs(folder))

    assert text.startswith(f"# {folder.name}\n\nSingle-file script -- no env.\n\nTags: `hud` `scoring`\n")
    assert "## Race to five\n\nA tiny mode." in text  # the README, one level down
    assert "## About\n\nFirst to five wins." in text
    assert "- `declare global.number[0] with network priority low` -- The leader's score, shown on the HUD. (`output.mgl:5`)" in text
    assert "- `if current_player.score >= 5 then` -- Ends the round at five. (`output.mgl:8`)" in text


def test_a_script_that_does_not_link_is_still_documented(tmp_path: Path) -> None:
    folder = _single(tmp_path, "-- @doc still here\ndeclare global.number[0]\ndeclare global.number[0]\n")

    docs = build_docs(folder)

    assert not docs.linked and docs.notes[0].text == "still here"
    assert "doesn't link right now" in render_markdown(docs)


# -- a script project ---------------------------------------------------------------------------------------


def test_a_projects_blocks_modules_and_readmes(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path)
    scripts = folder / "script"
    (scripts / "blocks" / "setup.md").write_text("Runs once.\n", encoding="utf-8")
    (scripts / "modules" / "hill_score" / "README.md").write_text("Scores the hill.\n", encoding="utf-8")
    manifest = scripts / "modules" / "hill_score" / "module.toml"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace('version = "1.0.0"', 'version = "1.0.0"\ntags = ["koth"]'), encoding="utf-8")

    docs = build_docs(folder)

    assert docs.mode == "project" and docs.env == "dev" and docs.flags == ["DEV"]
    assert [b.name for b in docs.blocks] == ["SETUP", "HILL_PASS", "WIN_CHECK"]
    setup, hill, win = docs.blocks
    assert setup.readme.text == "Runs once.\n" and setup.file == "blocks/setup.mgl"
    assert [f["id"] for f in hill.fragments] == ["hill_score.score", "hill_buff.buff"] and hill.file is None
    [module] = [m for m in docs.modules if m.name == "hill_score"]
    assert module.readme.text == "Scores the hill.\n" and module.tags == ["koth"] and module.blocks == ["HILL_PASS"]
    assert docs.tags == {"koth": ["module hill_score"]}
    assert docs.fusion["groups"][0]["fragments"] == ["hill_score.score", "hill_buff.buff"]
    [note] = docs.notes
    assert (note.file, note.kind) == ("blocks/win_check.mgl", "code")
    assert "- `if global.number[0] == 5 then` -- ends the game (`blocks/win_check.mgl:1`)" in render_markdown(docs)


def test_a_disabled_module_is_still_described_from_its_manifest(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path)
    set_module_enabled(folder, "hill_score", False)

    docs = build_docs(folder)

    [module] = [m for m in docs.modules if m.name == "hill_score"]
    assert not module.enabled and module.version == "1.0.0"
    assert "## Module hill_score 1.0.0 (disabled)" in render_markdown(docs)


def test_each_doc_in_a_run_belongs_to_the_declaration_beside_it(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path, blocks__setup_dot_mgl=(
        "-- @doc said before anything is declared\n"
        "-- @number g_a\n"
        "-- @doc about g_a\n"
        "-- @trait t_b { name = \"B\" }\n"
        "-- @doc about t_b\n"
        "-- @doc more about t_b\n"
        "on init: do\n"
        "end\n"
    ))

    docs = build_docs(folder)

    notes = [(n.kind, n.subject, n.text, n.line) for n in docs.notes if n.file == "blocks/setup.mgl"]
    assert notes == [
        ("name", "g_a", "said before anything is declared\nabout g_a", 1),
        ("name", "t_b", "about t_b\nmore about t_b", 5),
    ]
    assert {r["name"]: r["doc"] for r in docs.resources}["t_b"] == "about t_b\nmore about t_b"


# -- writing, the api and the command -----------------------------------------------------------------------


def test_the_overview_is_written_only_when_it_changes(tmp_path: Path) -> None:
    folder = _single(tmp_path)
    first = write_docs(folder, build_docs(folder))
    again = write_docs(folder, build_docs(folder))

    assert [p.name for p in first] == ["overview.md", "overview.json"] and again == []
    data = json.loads((docs_dir(folder) / "overview.json").read_text(encoding="utf-8"))
    assert data["docs_schema"] == 1 and data["mode"] == "single" and data["files"][0]["notes"][0]["text"] == "First to five wins."


def test_api_docs_can_leave_the_build_alone(tmp_path: Path) -> None:
    folder = _single(tmp_path)
    result = api.docs(folder, write=False)
    assert result.written == [] and not (folder / "build").exists() and result.markdown.startswith("# ")


def test_the_docs_command_prints_the_overview_and_writes_it(tmp_path: Path) -> None:
    folder = _single(tmp_path)

    text = CliRunner().invoke(main, ["docs", str(folder)])
    data = CliRunner().invoke(main, ["docs", str(folder), "--format", "json", "--no-write"])

    assert text.exit_code == 0 and "## About" in text.output
    assert (docs_dir(folder) / "overview.md").is_file()
    assert json.loads(data.output)["docs"]["mode"] == "single"


def test_api_docs_can_reuse_a_check(tmp_path: Path) -> None:
    folder = _single(tmp_path)
    checked = api.check(folder)
    assert api.docs(folder, write=False, checked=checked).docs.notes[0].text == "First to five wins."


# -- views: a tag filter, and what a hover shows ------------------------------------------------------------


def test_filtering_by_a_tag_keeps_what_carries_it(tmp_path: Path) -> None:
    from in_reach.app.script_project.docs import filter_docs

    folder = hill_rush(tmp_path)
    manifest = folder / "script" / "modules" / "hill_buff" / "module.toml"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace('name = "hill_buff"', 'name = "hill_buff"\ntags = ["buffs"]'), encoding="utf-8")

    narrowed = filter_docs(build_docs(folder), "buffs")

    assert [m.name for m in narrowed.modules] == ["hill_buff"] and narrowed.blocks == []
    assert [f.path for f in narrowed.files] == ["modules/hill_buff/hill_buff.mgl"]
    assert [r["name"] for r in narrowed.resources] == ["t_hill_buff"] and narrowed.storage == []
    assert narrowed.tags == {"buffs": ["module hill_buff"]}


def test_hover_texts_name_slots_resources_and_fragments(tmp_path: Path) -> None:
    from in_reach.app.script_project.docs import hover_texts

    texts = hover_texts(build_docs(hill_rush(tmp_path)))

    assert texts["g_phase"] == "g_phase = global.number[1]  (blocks/setup.mgl)"
    assert texts["t_hill_buff"].startswith("t_hill_buff: trait 0  (module hill_buff)")
    assert texts["hill_score.score"] == "fragment hill_score.score: for each player in HILL_PASS"
    assert texts["HILL_PASS"] == "block HILL_PASS (fragments only)"


def test_hover_text_carries_a_names_note(tmp_path: Path) -> None:
    from in_reach.app.script_project.docs import hover_texts

    texts = hover_texts(build_docs(hill_rush(tmp_path, blocks__setup_dot_mgl=_SETUP_WITH_NOTES)))

    assert texts["g_phase"] == "g_phase = global.number[1]  (blocks/setup.mgl)\nWhich phase of the round it is."


def test_a_single_files_tags_can_be_hovered(tmp_path: Path) -> None:
    from in_reach.app.script_project.docs import hover_texts

    assert hover_texts(build_docs(_single(tmp_path)))["scoring"] == "tag scoring: file output.mgl"


def test_a_single_files_page_is_titled_with_the_projects_title(tmp_path: Path) -> None:
    folder = _single(tmp_path)
    (folder / "settings").mkdir()
    (folder / "settings" / "settings.json").write_text(json.dumps({"meta": {"title": "Race to Five"}}), encoding="utf-8")

    assert build_docs(folder).name == "Race to Five"
