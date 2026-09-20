"""Fusion: which adjacent fragments become one trigger, and why the others don't (``TO_IMPLEMENT`` §7)."""
from pathlib import Path

import pytest
from hill_project import hill_rush

from in_reach.app.rvt.megalo_ast import MegaloParseError
from in_reach.app.script_project import link
from in_reach.app.script_project.fusion import analyse


def _fragment(name: str, body: str, loop: str = "player", header: str = "") -> str:
    return f"-- @fragment HILL_PASS.{name}\n-- @loop {loop}\n{header}{body}\n"


def _link(tmp_path: Path, first: str, second: str, extra_module_text: str = "", third: str = ""):
    """The Hill Rush project with its two modules' fragments replaced. ``g_phase`` (global.number[1]) is declared."""
    hill_rush(
        tmp_path,
        modules__hill_score__hill_score_dot_mgl=extra_module_text + first,
        modules__hill_buff__hill_buff_dot_mgl=second + third,
    )
    return link(tmp_path, write=False)


def _fused(result) -> list[list[str]]:
    return [group["fragments"] for group in result.link_map["fusion"]["groups"]]


def _declined(result) -> list[str]:
    return [f"{'+'.join(d['fragments'])}: {d['reason']}" for d in result.link_map["fusion"]["declined"]]


# -- what fuses -----------------------------------------------------------------------------------------


def test_adjacent_fragments_with_the_same_loop_become_one_trigger(tmp_path: Path) -> None:
    result = _link(tmp_path, _fragment("a", "current_player.score += 1"), _fragment("b", "current_player.number[0] += 1"))

    assert result.ok and _fused(result) == [["hill_score.a", "hill_buff.b"]]
    assert result.link_map["fusion"]["groups"][0]["saved"] == {"triggers": 1}
    lines = result.compiled.splitlines()
    start = lines.index("-- HILL_PASS (fused: hill_score.a, hill_buff.b)")
    assert lines[start + 1:start + 7] == [
        "for each player do", "   -- hill_score.a", "   current_player.score += 1", "   -- hill_buff.b",
        "   current_player.number[0] += 1", "end",
    ]


def test_three_fragments_fuse_into_one(tmp_path: Path) -> None:
    result = _link(tmp_path, _fragment("a", "x = 1"), _fragment("b", "y = 2"), third=_fragment("c", "z = 3"))

    assert _fused(result) == [["hill_score.a", "hill_buff.b", "hill_buff.c"]]
    assert result.link_map["fusion"]["groups"][0]["saved"]["triggers"] == 2


def test_a_lone_fragment_is_not_reported_as_fused(tmp_path: Path) -> None:
    result = link(hill_rush(tmp_path), write=False)

    assert result.ok


def test_fragments_that_are_not_neighbours_are_not_fused(tmp_path: Path) -> None:
    result = _link(tmp_path, _fragment("a", "x = 1"), _fragment("b", "y = 1", loop="team"), third=_fragment("c", "z = 1"))

    assert _fused(result) == []
    assert len(_declined(result)) == 2  # a|b and b|c; a and c were never neighbours


# -- what doesn't ---------------------------------------------------------------------------------------


def test_different_loops_are_kept_apart_and_the_reason_is_recorded(tmp_path: Path) -> None:
    result = _link(tmp_path, _fragment("a", "x = 1"), _fragment("b", "y = 1", loop="team"))

    assert _fused(result) == [] and _declined(result) == ["hill_score.a+hill_buff.b: different loops (player and team)"]


def test_different_gates_are_kept_apart(tmp_path: Path) -> None:
    result = _link(tmp_path, _fragment("a", "x = 1", header="-- @gate g_phase == 1\n"), _fragment("b", "y = 1"))

    assert _fused(result) == [] and "different gates" in _declined(result)[0]


def test_the_same_gate_fuses_and_is_written_once(tmp_path: Path) -> None:
    gate = "-- @gate g_phase == 1\n"
    result = _link(tmp_path, _fragment("a", "x = 1", header=gate), _fragment("b", "y = 1", header=gate))

    assert _fused(result) == [["hill_score.a", "hill_buff.b"]]
    assert result.compiled.count("if g_phase == 1 then") == 1


def test_fusion_never_keeps_a_fragment_on_its_own(tmp_path: Path) -> None:
    result = _link(tmp_path, _fragment("a", "x = 1", header="-- @fusion never\n"), _fragment("b", "y = 1"))

    assert _fused(result) == [] and _declined(result) == ["hill_score.a+hill_buff.b: @fusion never"]


def test_a_write_to_shared_state_a_sibling_reads_declines_the_merge(tmp_path: Path) -> None:
    result = _link(tmp_path, _fragment("a", "g_phase = 1"), _fragment("b", "if g_phase == 1 then\n   x = 1\nend"))

    assert _fused(result) == []
    assert "hill_score.a and hill_buff.b: one writes global.number[1], which the other reads" in _declined(result)[0]


def test_two_writes_to_the_same_shared_state_decline_the_merge(tmp_path: Path) -> None:
    result = _link(tmp_path, _fragment("a", "g_phase += 1"), _fragment("b", "g_phase *= 2"))

    assert _fused(result) == [] and "global.number[1]" in _declined(result)[0]


def test_the_current_iterations_own_state_never_conflicts_with_itself(tmp_path: Path) -> None:
    result = _link(tmp_path, _fragment("a", "current_player.number[0] += 1"), _fragment("b", "current_player.number[0] += 2"))

    assert _fused(result) == [["hill_score.a", "hill_buff.b"]]


def test_another_players_state_conflicts_with_this_ones_writes(tmp_path: Path) -> None:
    """``current_player.player[0]`` is some *other* player: what the first fragment wrote to ``player.number[0]`` for
    them may or may not have happened yet when the second reads it."""
    result = _link(tmp_path, _fragment("a", "current_player.number[0] = 1"), _fragment("b", "x = current_player.player[0].number[0]"))

    assert _fused(result) == [] and "player.number[0]" in _declined(result)[0]


def test_inside_a_nested_loop_nothing_is_the_iterations_own(tmp_path: Path) -> None:
    body_a = 'for each object with label "hill" do\n   current_object.number[1] = 1\nend'
    body_b = 'for each object with label "hill" do\n   x = current_object.number[1]\nend'

    result = _link(tmp_path, _fragment("a", body_a), _fragment("b", body_b))

    assert _fused(result) == [] and "object.number[1]" in _declined(result)[0]


def test_a_gate_is_a_read_like_any_other(tmp_path: Path) -> None:
    gate = "-- @gate g_phase == 1\n"
    result = _link(tmp_path, _fragment("a", "g_phase = 2", header=gate), _fragment("b", "y = 1", header=gate))

    assert _fused(result) == [] and "global.number[1]" in _declined(result)[0]


def test_subroutine_lowering_is_refused_with_a_warning(tmp_path: Path) -> None:
    result = _link(tmp_path, _fragment("a", "x = 1", header="-- @fusion subroutine\n"), _fragment("b", "y = 1"))

    assert result.ok and _fused(result) == []
    assert [d.code for d in result.diagnostics] == ["fusion-subroutine"] and result.diagnostics[0].severity == "warning"
    assert "isn't implemented" in _declined(result)[0]


# -- preambles and temporaries ---------------------------------------------------------------------------

_PREAMBLE = "-- @preamble in_hill\n-- @provides seen:number\nseen = 0\nif seen == 0 then\n   -- @guard-end\nend\n\n"


def test_fragments_sharing_a_preamble_share_it_and_its_temporaries(tmp_path: Path) -> None:
    result = _link(
        tmp_path,
        _fragment("a", "x = seen", header="-- @preamble in_hill\n"),
        _fragment("b", "y = seen", header="-- @preamble in_hill\n"),
        extra_module_text=_PREAMBLE,
    )

    assert result.ok, [str(d) for d in result.diagnostics]
    [group] = result.link_map["fusion"]["groups"]
    assert group["preamble"] == "in_hill" and group["saved"] == {"triggers": 1, "preambles": 1}
    assert result.compiled.count("alias seen = temporaries.number[0]") == 1
    assert "-- HILL_PASS (fused: hill_score.a, hill_buff.b; preamble in_hill)" in result.compiled
    assert result.link_map["temporaries"] == [{"block": "HILL_PASS", "fragments": ["hill_score.a", "hill_buff.b"], "number": 1}]


def test_fragments_with_different_preambles_are_kept_apart(tmp_path: Path) -> None:
    result = _link(
        tmp_path,
        _fragment("a", "x = seen", header="-- @preamble in_hill\n"),
        _fragment("b", "y = 1"),
        extra_module_text=_PREAMBLE,
    )

    assert _fused(result) == [] and "different preambles (in_hill and none)" in _declined(result)[0]


def test_a_preamble_that_writes_shared_state_is_not_shared(tmp_path: Path) -> None:
    preamble = "-- @preamble bump\n-- @provides seen:number\ng_phase += 1\nseen = 0\n-- @guard-end\n\n"
    result = _link(
        tmp_path,
        _fragment("a", "x = seen", header="-- @preamble bump\n"),
        _fragment("b", "y = seen", header="-- @preamble bump\n"),
        extra_module_text=preamble,
    )

    assert _fused(result) == [] and "preamble bump writes global.number[1]" in _declined(result)[0]


def test_a_fused_trigger_needs_the_temporaries_once_not_once_per_fragment(tmp_path: Path) -> None:
    names = " ".join(f"t{i}:number" for i in range(6))
    preamble = f"-- @preamble wide\n-- @provides {names}\nt0 = 0\n-- @guard-end\n\n"
    result = _link(
        tmp_path,
        _fragment("a", "x = t0", header="-- @preamble wide\n"),
        _fragment("b", "y = t1", header="-- @preamble wide\n"),
        extra_module_text=preamble,
    )

    assert result.ok  # six each would be twelve, over the cap of ten, if they were separate triggers' sum
    assert _fused(result) == [["hill_score.a", "hill_buff.b"]]


# -- force ----------------------------------------------------------------------------------------------


def test_force_fuses_despite_a_conflict_and_says_so(tmp_path: Path) -> None:
    result = _link(
        tmp_path,
        _fragment("a", "g_phase = 1", header="-- @fusion force:pass\n"),
        _fragment("b", "if g_phase == 1 then\n   x = 1\nend", header="-- @fusion force:pass\n"),
    )

    assert result.ok and _fused(result) == [["hill_score.a", "hill_buff.b"]]
    assert result.link_map["fusion"]["groups"][0]["forced"] == "pass"
    [warning] = [d for d in result.diagnostics if d.code == "IR018"]
    assert warning.severity == "warning" and warning.file == "modules/hill_buff/hill_buff.mgl"


def test_force_with_nothing_wrong_is_silent(tmp_path: Path) -> None:
    result = _link(
        tmp_path,
        _fragment("a", "x = 1", header="-- @fusion force:pass\n"),
        _fragment("b", "y = 1", header="-- @fusion force:pass\n"),
    )

    assert _fused(result) == [["hill_score.a", "hill_buff.b"]] and result.diagnostics == []


def test_force_cannot_join_different_loops(tmp_path: Path) -> None:
    result = _link(
        tmp_path,
        _fragment("a", "x = 1", header="-- @fusion force:pass\n"),
        _fragment("b", "y = 1", loop="team", header="-- @fusion force:pass\n"),
    )

    assert not result.ok
    [error] = [d for d in result.diagnostics if d.code == "fusion-force-incompatible"]
    assert "force:pass" in error.message and "different loops" in error.message


def test_force_groups_do_not_merge_with_each_other_or_with_auto_fragments(tmp_path: Path) -> None:
    result = _link(
        tmp_path,
        _fragment("a", "x = 1", header="-- @fusion force:one\n"),
        _fragment("b", "y = 1", header="-- @fusion force:two\n"),
    )

    assert _fused(result) == [] and "not in the same @fusion force group" in _declined(result)[0]


# -- hoisting -------------------------------------------------------------------------------------------


def test_a_guard_every_fragment_shares_is_tested_once(tmp_path: Path) -> None:
    guard = "-- @guard global.number[3] == 1\n"
    result = _link(tmp_path, _fragment("a", "x = 1", header=guard), _fragment("b", "y = 1", header=guard))

    assert result.compiled.count("global.number[3] == 1") == 1
    lines = result.compiled.splitlines()
    start = lines.index("-- HILL_PASS (fused: hill_score.a, hill_buff.b)")
    assert lines[start + 1:start + 9] == [
        "for each player do", "   if global.number[3] == 1 then", "      -- hill_score.a", "      x = 1",
        "      -- hill_buff.b", "      y = 1", "   end", "end",
    ]
    assert result.link_map["fusion"]["groups"][0]["hoisted_guards"] == ["global.number[3] == 1"]


def test_a_guard_only_some_fragments_have_stays_where_it_is(tmp_path: Path) -> None:
    result = _link(tmp_path, _fragment("a", "x = 1", header="-- @guard global.number[3] == 1\n"), _fragment("b", "y = 1"))

    assert _fused(result) == [["hill_score.a", "hill_buff.b"]]
    assert "hoisted_guards" not in result.link_map["fusion"]["groups"][0]
    lines = result.compiled.splitlines()
    start = lines.index("-- HILL_PASS (fused: hill_score.a, hill_buff.b)")
    assert lines[start + 1:start + 7] == [
        "for each player do", "   -- hill_score.a", "   if global.number[3] == 1 then", "      x = 1", "   end", "   -- hill_buff.b",
    ]


def test_a_shared_guard_is_not_hoisted_over_a_write_to_what_it_reads(tmp_path: Path) -> None:
    """The first fragment changes the answer the second's guard would give, so each is tested where it stood."""
    guard = "-- @guard current_player.number[0] == 1\n"
    result = _link(
        tmp_path, _fragment("a", "current_player.number[0] = 2", header=guard), _fragment("b", "y = 1", header=guard)
    )

    assert _fused(result) == [["hill_score.a", "hill_buff.b"]]
    assert result.compiled.count("current_player.number[0] == 1") == 2
    assert "hoisted_guards" not in result.link_map["fusion"]["groups"][0]


# -- the analysis ---------------------------------------------------------------------------------------


def _cells(code: str, aliases: tuple[str, ...] = ()) -> tuple[set, set]:
    access = analyse(list(aliases), [], code)
    return access.reads, access.writes


@pytest.mark.parametrize(
    ("code", "reads", "writes"),
    [
        ("global.number[0] = 1", set(), {("global.number[0]", False)}),
        ("global.number[0] += 1", {("global.number[0]", False)}, {("global.number[0]", False)}),
        ("current_player.number[2] = global.number[0]", {("global.number[0]", False)}, {("player.number[2]", True)}),
        ("temporaries.number[0] = current_player.score", {("player.score", True)}, set()),
        ("team[3].number[1] = 4", set(), {("team.number[1]", False)}),
        ("current_player.biped.number[0] = 1", set(), {("object.number[0]", True)}),
        ("current_player.object[0].number[1] = 1", set(), {("object.number[1]", False)}),
        ("current_player.team.number[0] = 1", set(), {("team.number[0]", False)}),
        ("game.end_round()", {("game", False)}, {("game", False)}),
        ("current_player.apply_traits(script_traits[0])", {("player", True)}, {("player", True)}),
        ("if current_object.is_of_type(x) then\n   global.timer[0] = 5\nend", {("object", True)}, {("global.timer[0]", False)}),
        ("for each object do\n   current_object.number[0] = 1\nend", set(), {("object.number[0]", False)}),
        ("x = no_object", set(), set()),
    ],
)
def test_the_storage_a_piece_of_code_reads_and_writes(code: str, reads: set, writes: set) -> None:
    got_reads, got_writes = _cells(code)

    assert (got_reads - {("x", False)}, got_writes - {("x", False)}) == (reads, writes)


def test_aliases_are_resolved_before_classifying() -> None:
    reads, writes = _cells("g_phase = 1", aliases=("alias g_phase = global.number[1]",))

    assert writes == {("global.number[1]", False)} and reads == set()


def test_a_nested_alias_on_the_current_player_is_the_iterations_own() -> None:
    _, writes = _cells("current_player.p_count = 1", aliases=("alias p_count = player.number[3]",))

    assert writes == {("player.number[3]", True)}


def test_conditions_given_separately_are_reads() -> None:
    from in_reach.app.rvt.megalo_ast import parse_expression

    access = analyse([], [parse_expression("global.number[2] == 1")], "")

    assert access.reads == {("global.number[2]", False)} and access.writes == set()


def test_code_that_doesnt_parse_is_unanalysable() -> None:
    from in_reach.app.script_project.fusion import Unanalysable

    with pytest.raises(Unanalysable):
        analyse([], [], "if x then")
    assert MegaloParseError  # the parser's own error is what's translated
