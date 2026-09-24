"""Docstrings you can edit: Markdown docstrings over several ``-- @doc`` lines, editing and removing one (which
rewrites those lines in its file), their longer texts in DOCSTRINGS.md, and the documentation's own description."""
import json
from pathlib import Path

import pytest

from in_reach import api
from in_reach.app.script_project.docs import build_docs, render_markdown, rewrite_entry

_SCRIPT = (
    "-- @doc Ends the round at five.\n"  # 1
    "-- @doc\n"  # 2  (a blank line: a new paragraph)
    "-- @doc - first **point**\n"  # 3
    "-- @doc   - nested\n"  # 4
    "for each player do\n"  # 5
    "   -- @doc One more.\n"  # 6
    "   game.end_round()\n"  # 7
    "end\n"
)


def _single(tmp_path: Path, text: str = _SCRIPT, description: str = "") -> Path:
    (tmp_path / "script").mkdir()
    (tmp_path / "script" / "output.mgl").write_text(text, encoding="utf-8")
    (tmp_path / "settings").mkdir()
    (tmp_path / "settings" / "settings.json").write_text(json.dumps({"meta": {"title": "T", "description": description}}), encoding="utf-8")
    return tmp_path


def _script(folder: Path) -> str:
    return (folder / "script" / "output.mgl").read_text(encoding="utf-8")


# -- Markdown entries ---------------------------------------------------------------------------------------


def test_an_entry_keeps_its_lines_as_markdown_and_knows_where_they_are(tmp_path: Path) -> None:
    first, second = build_docs(_single(tmp_path)).notes

    assert first.text == "Ends the round at five.\n\n- first **point**\n  - nested"
    assert first.lines == [1, 2, 3, 4] and first.kind == "code"
    assert (second.text, second.lines) == ("One more.", [6])


def test_a_longer_entry_renders_under_its_first_line(tmp_path: Path) -> None:
    text = render_markdown(build_docs(_single(tmp_path)))

    assert "- `for each player do` -- Ends the round at five. (`output.mgl:1`)\n\n  - first **point**\n    - nested" in text


def test_bare_doc_lines_alone_are_no_entry(tmp_path: Path) -> None:
    assert build_docs(_single(tmp_path, "-- @doc\n-- @doc\ngame.end_round()\n")).notes == []


# -- editing and removing -----------------------------------------------------------------------------------


def test_editing_an_entry_rewrites_its_doc_lines_and_nothing_else(tmp_path: Path) -> None:
    folder = _single(tmp_path)

    api.edit_doc_entry(folder, "output.mgl", 3, "Now **two** lines\nof text")

    assert _script(folder) == (
        "-- @doc Now **two** lines\n-- @doc of text\n"
        "for each player do\n   -- @doc One more.\n   game.end_round()\nend\n"
    )


def test_an_indented_entry_keeps_its_indent(tmp_path: Path) -> None:
    folder = _single(tmp_path)

    api.edit_doc_entry(folder, "output.mgl", 6, "Changed.\n\nWith a paragraph.")

    assert "   -- @doc Changed.\n   -- @doc\n   -- @doc With a paragraph.\n   game.end_round()" in _script(folder)


def test_removing_an_entry_removes_its_doc_lines_and_the_entry(tmp_path: Path) -> None:
    folder = _single(tmp_path)

    api.remove_doc_entry(folder, "output.mgl", 6)

    assert "One more." not in _script(folder) and "   game.end_round()" in _script(folder)
    assert [n.text.split("\n")[0] for n in build_docs(folder).notes] == ["Ends the round at five."]


def test_crlf_files_stay_crlf(tmp_path: Path) -> None:
    folder = _single(tmp_path)
    (folder / "script" / "output.mgl").write_bytes(_SCRIPT.replace("\n", "\r\n").encode("utf-8"))

    api.edit_doc_entry(folder, "output.mgl", 6, "Changed.")

    assert b"-- @doc Changed.\r\n" in (folder / "script" / "output.mgl").read_bytes()


def test_an_entry_that_is_not_there_is_an_api_error(tmp_path: Path) -> None:
    with pytest.raises(api.ApiError):
        api.edit_doc_entry(_single(tmp_path), "output.mgl", 7, "x")


def test_a_file_changed_since_it_was_read_is_refused(tmp_path: Path) -> None:
    folder = _single(tmp_path)
    with pytest.raises(ValueError):
        rewrite_entry(folder, "output.mgl", [5], "x")  # line 5 is code, not a @doc line


# -- the description ----------------------------------------------------------------------------------------


def test_the_overview_has_a_description_section_of_its_own(tmp_path: Path) -> None:
    folder = _single(tmp_path, description="What the game shows.")  # the gametype's in-game one: not this

    assert "## Description\n\n*No description yet.*" in render_markdown(build_docs(folder))
    api.set_docs_description(folder, "First to **five** wins.\n\nTwo paragraphs, even.")

    text = render_markdown(build_docs(folder))
    assert "## Description\n\nFirst to **five** wins.\n\nTwo paragraphs, even.\n" in text
    assert "What the game shows." not in text
    assert json.loads((folder / "script" / "docs.json").read_text(encoding="utf-8"))["description"].startswith("First to")
    meta = json.loads((folder / "settings" / "settings.json").read_text(encoding="utf-8"))["meta"]
    assert meta["description"] == "What the game shows."  # left alone


def test_clearing_everything_removes_docs_json(tmp_path: Path) -> None:
    folder = _single(tmp_path)
    api.set_docs_description(folder, "x")

    api.set_docs_description(folder, "")

    assert not (folder / "script" / "docs.json").exists()


# -- a docstring's longer text, in DOCSTRINGS.md -----------------------------------------------------------------


def _docstrings(folder: Path) -> str:
    return (folder / "script" / "DOCSTRINGS.md").read_text(encoding="utf-8")


def test_docstrings_md_lists_every_docstring_by_title_with_where_it_is(tmp_path: Path) -> None:
    from in_reach.app.script_project.docs import sync_docstrings

    folder = _single(tmp_path)

    sync_docstrings(folder, build_docs(folder))

    text = _docstrings(folder)
    assert text.startswith("# Docstrings\n")
    assert "## Ends the round at five.\n<!-- output.mgl:1 -->\n" in text
    assert "## One more.\n<!-- output.mgl:6 -->\n" in text
    assert text.index("## Ends the round") < text.index("## One more.")


def test_a_text_written_under_a_title_is_the_docstrings_text(tmp_path: Path) -> None:
    from in_reach.app.script_project.docs import sync_docstrings

    folder = _single(tmp_path)
    sync_docstrings(folder, build_docs(folder))
    path = folder / "script" / "DOCSTRINGS.md"
    path.write_text(_docstrings(folder).replace("<!-- output.mgl:6 -->\n", "<!-- output.mgl:6 -->\n\nThe **long** story.\n\n- with a list\n"), encoding="utf-8")

    [note] = [n for n in build_docs(folder).notes if n.line == 6]

    assert note.details == "The **long** story.\n\n- with a list"
    assert "One more. (`output.mgl:6`)\n\n  The **long** story.\n\n  - with a list" in render_markdown(build_docs(folder))
    sync_docstrings(folder, build_docs(folder))  # the text survives a resync
    assert "The **long** story." in _docstrings(folder)


def test_edit_doc_entry_sets_a_text_without_touching_the_script(tmp_path: Path) -> None:
    folder = _single(tmp_path)

    api.edit_doc_entry(folder, "output.mgl", 6, "One more.", "Details.")

    assert _script(folder) == _SCRIPT
    [note] = [n for n in build_docs(folder).notes if n.line == 6]
    assert note.details == "Details."


def test_rewording_the_note_moves_its_text_to_the_new_title(tmp_path: Path) -> None:
    folder = _single(tmp_path)
    api.edit_doc_entry(folder, "output.mgl", 6, "One more.", "Details.")

    api.edit_doc_entry(folder, "output.mgl", 6, "Ends it.")  # text None: kept

    [note] = [n for n in build_docs(folder).notes if n.line == 6]
    assert (note.text, note.details) == ("Ends it.", "Details.")
    assert "## One more." not in _docstrings(folder)


def test_removing_a_docstring_removes_its_text(tmp_path: Path) -> None:
    folder = _single(tmp_path)
    api.edit_doc_entry(folder, "output.mgl", 6, "One more.", "Details.")

    api.remove_doc_entry(folder, "output.mgl", 6)

    assert "## One more." not in _docstrings(folder) and "Details." not in _docstrings(folder)


def test_a_text_whose_docstring_was_reworded_by_hand_is_kept_at_the_end(tmp_path: Path) -> None:
    from in_reach.app.script_project.docs import sync_docstrings

    folder = _single(tmp_path)
    api.edit_doc_entry(folder, "output.mgl", 6, "One more.", "Details.")
    (folder / "script" / "output.mgl").write_text(_SCRIPT.replace("One more.", "Changed by hand."), encoding="utf-8")

    docs = build_docs(folder)
    sync_docstrings(folder, docs)

    assert docs.detached == [{"note": "One more.", "text": "Details."}]
    assert "## Docstring texts no longer in the script" in render_markdown(docs)
    text = _docstrings(folder)
    assert "## Changed by hand." in text and text.index("# No longer in the script") < text.index("## One more.\n\nDetails.")


def test_docstring_section_says_where_to_write_a_docstrings_text(tmp_path: Path) -> None:
    folder = _single(tmp_path)

    path, line = api.docstring_section(folder, "output.mgl", 6)

    lines = path.read_text(encoding="utf-8").split("\n")
    assert path.name == "DOCSTRINGS.md" and lines[line - 3] == "## One more." and lines[line - 2] == "<!-- output.mgl:6 -->"


def test_older_texts_in_docs_json_move_into_docstrings_md(tmp_path: Path) -> None:
    from in_reach.app.script_project.docs import sync_docstrings

    folder = _single(tmp_path)
    (folder / "script" / "docs.json").write_text(json.dumps({
        "description": "Kept.", "entries": [{"file": "output.mgl", "note": "One more.", "text": "From before."}],
    }), encoding="utf-8")

    sync_docstrings(folder, build_docs(folder))

    assert "## One more.\n<!-- output.mgl:6 -->\n\nFrom before." in _docstrings(folder)
    assert json.loads((folder / "script" / "docs.json").read_text(encoding="utf-8")) == {"description": "Kept."}


def test_a_build_keeps_docstrings_md_in_step(tmp_path: Path) -> None:
    from in_reach.app.script_project.docs import write_docs

    folder = _single(tmp_path)

    write_docs(folder, build_docs(folder))

    assert (folder / "script" / "DOCSTRINGS.md").is_file()


def test_refresh_docstrings_moves_each_where_line_with_its_docstring(tmp_path: Path) -> None:
    from in_reach.app.script_project.docs import sync_docstrings

    folder = _single(tmp_path)
    sync_docstrings(folder, build_docs(folder))
    (folder / "script" / "output.mgl").write_text("-- a new first line\n" + _SCRIPT, encoding="utf-8")

    assert api.refresh_docstrings(folder) == folder / "script" / "DOCSTRINGS.md"

    assert "<!-- output.mgl:7 -->" in _docstrings(folder) and "<!-- output.mgl:6 -->" not in _docstrings(folder)
    assert api.refresh_docstrings(folder) is None  # nothing more to change


def test_refresh_docstrings_makes_no_file_that_isnt_there(tmp_path: Path) -> None:
    folder = _single(tmp_path)

    assert api.refresh_docstrings(folder) is None and not (folder / "script" / "DOCSTRINGS.md").exists()
