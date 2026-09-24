"""Convert to Alias: a piece of script named, every whole copy of it replaced, and its alias line added."""
import pytest

from in_reach.app.script_project.refactor import check_alias_name, convert_to_alias, occurrences

_SCRIPT = (
    "-- ALIASES\n"
    "alias role_none = 0\n"
    "\n"
    "for each player do\n"
    '   if current_player.number[5] > 15 then -- player.number[5] in a comment\n'
    '      game.show_message_to(current_player, none, "player.number[5]")\n'
    "      current_player.number[5] = 5\n"
    "      current_player.number[50] = 5\n"
    "   end\n"
    "end\n"
)


def _texts(text: str, snippet: str) -> list[str]:
    return [text[a:b] for a, b in occurrences(text, snippet)]


def test_only_whole_copies_in_code_count() -> None:
    assert len(_texts(_SCRIPT, "current_player.number[5]")) == 2  # not [50], not in the comment or the string
    assert len(_texts(_SCRIPT, "5")) == 2  # the two "= 5", not 15, not the index in [5] of a longer slot
    assert _texts(_SCRIPT, "number[5]") == []  # part of a longer name: current_player.number[5]


def test_convert_to_alias_replaces_the_copies_and_adds_the_alias_after_the_others() -> None:
    result = convert_to_alias(_SCRIPT, "current_player.number[5]", "revive_progress")

    lines = result.split("\n")
    assert lines[1:3] == ["alias role_none = 0", "alias revive_progress = current_player.number[5]"]
    assert "   if revive_progress > 15 then -- player.number[5] in a comment" in lines
    assert "      revive_progress = 5" in lines and "      current_player.number[50] = 5" in lines
    assert '"player.number[5]"' in result  # the string is left alone


def test_with_no_aliases_it_goes_after_the_opening_comments() -> None:
    result = convert_to_alias("-- my mode\n\nfor each player do\n   x = global.number[2]\nend\n", "global.number[2]", "score")

    assert result.split("\n")[:4] == ["-- my mode", "", "alias score = global.number[2]", "for each player do"]
    assert "   x = score" in result


def test_the_name_must_be_new_and_usable() -> None:
    assert check_alias_name(_SCRIPT, "role_none") == "there is already an alias named 'role_none'"
    assert "already uses" in check_alias_name(_SCRIPT, "end")
    assert "isn't a name" in check_alias_name(_SCRIPT, "2fast")
    assert check_alias_name(_SCRIPT, "fresh") is None
    with pytest.raises(ValueError):
        convert_to_alias(_SCRIPT, "current_player.number[5]", "end")
    with pytest.raises(ValueError):
        convert_to_alias(_SCRIPT, "nothing_like_this", "fresh")


def test_a_new_alias_goes_below_the_declarations_block() -> None:
    text = (
        "alias role_none = 0\n"
        "\n"
        "declare global.number[0] with network priority low\n"
        "declare player.number[5] with network priority local\n"
        "\n"
        "for each player do\n"
        "   current_player.number[5] = 1\n"
        "end\n"
    )

    lines = convert_to_alias(text, "current_player.number[5]", "revive_progress").split("\n")

    assert lines[2:5] == [
        "declare global.number[0] with network priority low",
        "declare player.number[5] with network priority local",
        "alias revive_progress = current_player.number[5]",
    ]


def test_aliases_already_below_the_declarations_stay_together() -> None:
    text = "declare global.number[0]\nalias a = 1\n\nx = global.number[0]\n"

    lines = convert_to_alias(text, "global.number[0]", "score").split("\n")

    assert lines[:3] == ["declare global.number[0]", "alias a = 1", "alias score = global.number[0]"]
    assert lines[4] == "x = score"  # the declaration keeps its slot; the use is named
