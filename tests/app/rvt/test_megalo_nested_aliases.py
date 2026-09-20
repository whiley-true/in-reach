"""Aliases for a *nested* variable: ``alias p_n = player.number[0]``, used as ``current_player.p_n``.

Native accepts this (``current_player.p_n`` means ``current_player.number[0]``), and it is how the linker names
per-player, per-object and per-team storage. The alias pass used to substitute only a bare identifier, so a script
using one fell out of the in-house compiler and back to native. A member access whose *name* is such an alias
now becomes ``<target>.<type>[N]``.
"""
import pytest

from in_reach.app.rvt import megalo_compiler, rvt_bridge, template_source
from in_reach.app.rvt.decompile import normalize_script_text
from in_reach.app.rvt.megalo_ast import parse, render_expr, resolve_aliases, unparse, walk


def _resolved(text: str) -> str:
    return unparse(resolve_aliases(parse(text))).replace("\r\n", "\n").strip()


def test_a_nested_alias_used_as_a_member_becomes_the_real_variable() -> None:
    text = "alias p_n = player.number[0]\ncurrent_player.p_n += 1\n"

    assert _resolved(text) == "current_player.number[0] += 1"


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        ("player.number[3]", "current_player.number[3]"),
        ("player.timer[1]", "current_player.timer[1]"),
        ("player.object[0]", "current_player.object[0]"),
        ("object.number[2]", "current_player.number[2]"),  # the owner is whatever the use says, as in native
        ("team.number[1]", "current_player.number[1]"),
    ],
)
def test_every_nested_scope_and_type(alias: str, expected: str) -> None:
    assert _resolved(f"alias v = {alias}\nx = current_player.v\n").endswith(f"x = {expected}")


def test_the_owner_can_be_any_expression() -> None:
    text = "alias c_role = object.number[0]\nglobal.number[1] = global.object[2].c_role\n"

    assert _resolved(text).endswith("global.number[1] = global.object[2].number[0]")


def test_a_call_on_a_nested_alias_is_resolved_through_the_member() -> None:
    text = "alias p_t = player.timer[0]\ncurrent_player.p_t.set_rate(-100%)\n"

    assert _resolved(text) == "current_player.timer[0].set_rate(-100%)"


def test_an_alias_of_a_nested_alias_target_still_resolves() -> None:
    text = "alias slot = 2\nalias p_n = player.number[slot]\nx = current_player.p_n\n"

    assert _resolved(text).endswith("x = current_player.number[2]")


def test_a_global_alias_is_still_a_plain_substitution() -> None:
    text = "alias g_phase = global.number[0]\ng_phase = 1\n"

    assert _resolved(text) == "global.number[0] = 1"


def test_a_temporaries_alias_is_still_a_plain_substitution() -> None:
    text = "alias tmp = temporaries.number[0]\ntmp = 1\n"

    assert _resolved(text) == "temporaries.number[0] = 1"


def test_an_ordinary_member_that_is_not_an_alias_is_untouched() -> None:
    assert _resolved("alias p_n = player.number[0]\nx = current_player.score\n").endswith("x = current_player.score")


def test_the_alias_declaration_itself_is_dropped() -> None:
    assert "alias" not in _resolved("alias p_n = player.number[0]\nx = 1\n")


def test_the_new_nodes_carry_the_position_of_the_use() -> None:
    script = resolve_aliases(parse("alias p_n = player.number[0]\n\ncurrent_player.p_n += 1\n"))

    target = script.body[0].target
    assert (target.span.start_line, target.span.start_col) == (3, 0)
    assert render_expr(target) == "current_player.number[0]"
    assert all(node.span.start_line == 3 for node in walk(target))


# -- against the engine ---------------------------------------------------------------------------------

pytestmark_native = pytest.mark.skipif(not rvt_bridge.is_available(), reason="native extension not available")

_SCRIPT = """alias p_t = player.timer[0]
alias p_n = player.number[0]
alias c_role = object.number[0]
alias g_phase = global.number[0]
for each player do
   current_player.p_n += 1
   current_player.p_t = 5
   current_player.p_t.set_rate(-100%)
   g_phase = current_player.p_n
end
for each object with label "hill" do
   current_object.c_role = 2
end
"""


def _blank(rvt):
    from in_reach.app.blank_variant import resolve_blank_variant

    return rvt.load(str(resolve_blank_variant(firefight=False)))


@pytestmark_native
def test_the_in_house_compiler_builds_a_script_with_nested_aliases_itself_and_agrees_with_native() -> None:
    rvt = rvt_bridge.get_rvt()
    native = _blank(rvt)
    assert native.multiplayer.compile_script(_SCRIPT).success
    in_house = _blank(rvt)

    # raises UnsupportedConstruct (a fallback to native) if it can't -- which is what used to happen
    megalo_compiler.compile_script(rvt, in_house, _SCRIPT, template_pool=lambda: template_source.build_variants(rvt))

    assert normalize_script_text(in_house.decompile_script()) == normalize_script_text(native.decompile_script())
