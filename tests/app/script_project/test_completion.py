"""Autocomplete for Megalo script text: what :func:`complete` offers for the line up to the cursor."""
from in_reach.app.script_project.completion import complete, script_names, type_of


def _offered(line: str, **kwargs) -> list[str]:
    return [c.text for c in complete(line, **kwargs)[1]]


def test_a_bare_word_is_finished_from_keywords_roots_and_functions() -> None:
    start, found = complete("   cur")

    assert start == 3
    assert [c.text for c in found] == ["current_object", "current_player", "current_team"]
    assert _offered("ali") == ["alias"]


def test_after_game_dot_come_its_members_and_functions() -> None:
    offered = _offered("game.")

    assert "end_round" in offered and "round_timer" in offered and "delete" not in offered
    [end] = complete("game.end_r")[1]
    assert (end.text, end.kind, end.detail) == ("end_round", "function", "end_round()") and end.description


def test_after_a_player_come_a_players_properties_functions_and_slots() -> None:
    offered = _offered("current_player.")

    assert {"biped", "score", "team", "number["} <= set(offered)
    assert "place_at_me" not in offered  # an object's
    assert _offered("global.player[0].sc") == ["score", "script_stat"]


def test_the_type_follows_properties_slots_and_the_scripts_own_names() -> None:
    assert type_of("current_player.biped") == "object"
    assert type_of("global.team[1]") == "team"
    assert type_of("hill", {"hill": "global.object[0]"}) == "object"
    assert "place_at_me" in _offered("hill.", declared={"hill": "global.object[0]"})
    assert "place_at_me" in _offered("base.", text="alias base = global.object[3]\n")


def test_something_it_cant_place_gets_every_types_members() -> None:
    offered = _offered("mystery.")

    assert "place_at_me" in offered and "biped" in offered


def test_global_offers_its_slot_families() -> None:
    assert _offered("global.") == ["number[", "object[", "player[", "team[", "timer["]


def test_the_scripts_own_names_and_words_come_first() -> None:
    text = "alias score_goal = global.number[2]\nscore_bonus = 1\n"

    offered = _offered("score_", text=text)

    assert offered == ["score_goal", "score_bonus"]
    assert script_names(text) == {"score_goal": "global.number[2]"}


def test_nothing_in_a_string_or_a_plain_comment() -> None:
    assert _offered('x = "cur') == []
    assert _offered("-- a note about cur") == []
    assert _offered("1.") == []
    assert _offered("") == []


def test_annotation_names_after_an_at() -> None:
    assert _offered("-- @d") == ["doc"]
    assert "fragment" not in _offered("-- @")  # a single file's are documentation
    assert "fragment" in _offered("-- @f", single_file=False)
    assert complete("   -- @ta")[0] == 7


# -- an alias's target ---------------------------------------------------------------------------------------


def test_an_alias_target_offers_only_what_an_alias_can_stand_for() -> None:
    offered = _offered("alias team_humans = te", text="alias role_none = 0\n")

    assert offered == ["team[", "team.", "temporaries."]
    everything = _offered("alias x = s")
    assert everything == ["script_option[", "script_stat[", "script_traits[", "script_widget["]  # no keyword, no function


def test_an_alias_target_offers_the_scripts_other_names_and_the_unnamed_namespace() -> None:
    offered = _offered("alias boss = r", text="alias role_none = 0\n")
    assert offered == ["role_none"]
    assert "current_player" in _offered("alias boss = cur")


def test_after_a_scope_come_the_slot_families() -> None:
    assert _offered("alias revive_progress = player.") == ["number[", "object[", "player[", "team[", "timer["]
    assert _offered("alias hold = player.t") == ["team[", "timer["]
    assert _offered("alias anchor = global.o") == ["object["]


def test_after_a_known_thing_come_its_properties_and_slots_not_its_functions() -> None:
    offered = _offered("alias mine = current_player.")

    assert "biped" in offered and "number[" in offered and "apply_traits" not in offered


def test_a_number_or_an_index_offers_nothing() -> None:
    assert _offered("alias heal_interval = 6") == []
    assert _offered("alias team_humans = team[0") == []
