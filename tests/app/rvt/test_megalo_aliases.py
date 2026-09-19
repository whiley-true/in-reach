"""Coverage for :mod:`in_reach.app.rvt.megalo_ast.aliases` -- compile-time ``alias`` resolution.

The pure tests pin the pass's own scoping rules against the AST alone. The oracle tests then check
those same rules against the one authority that matters: the native ``compile_script()`` -- for each
script, compiling the aliased text must decompile to exactly what compiling the *resolved* text does,
so any drift between this pass and real Megalo alias semantics fails here rather than in a user's
project. The end-to-end tests prove :func:`~in_reach.app.rvt.megalo_compiler.compile_script` now
handles aliases itself instead of raising :class:`~in_reach.app.rvt.megalo_compiler.
UnsupportedConstruct` (which used to push every alias-using script onto the native compiler's own,
non-idempotent inlining behaviour -- see that module's docstring).
"""
from pathlib import Path

import pytest

from in_reach.app.blank_variant import resolve_blank_variant
from in_reach.app.rvt import megalo_compiler, rvt_bridge
from in_reach.app.rvt.decompile import normalize_script_text
from in_reach.app.rvt.megalo_ast import (
    AliasDeclaration, Assignment, Call, Identifier, MegaloAliasError, RESERVED_NAMES, parse,
    render_expr, resolve_aliases, unparse, walk,
)

_JUGGERNAUT_BIN = Path(__file__).parent / "resources" / "juggernaut" / "juggernaut.bin"
_NEEDS_NATIVE_RVT = pytest.mark.skipif(
    not (_JUGGERNAUT_BIN.is_file() and rvt_bridge.is_available()),
    reason="fixture .bin not present, or native _reachvarianttool extension not available on this platform",
)


def _resolved(text: str):
    return resolve_aliases(parse(text))


def _rendered_assignments(script) -> list[str]:
    return [f"{render_expr(n.target)} {n.op} {render_expr(n.value)}" for n in walk(script) if isinstance(n, Assignment)]


# -- pure AST behaviour ---------------------------------------------------------------------------


def test_declarations_are_removed_and_uses_are_substituted() -> None:
    script = _resolved("alias score = global.number[0]\non init: do\n   score = 1\nend\n")
    assert not any(isinstance(n, AliasDeclaration) for n in walk(script))
    assert _rendered_assignments(script) == ["global.number[0] = 1"]


def test_alias_of_a_literal_substitutes_the_literal() -> None:
    script = _resolved("alias five = 5\non init: do\n   global.number[0] = five\nend\n")
    assert _rendered_assignments(script) == ["global.number[0] = 5"]


def test_alias_substitutes_inside_conditions_and_call_arguments() -> None:
    script = _resolved(
        "alias n = global.number[0]\n"
        "on init: do\n"
        "   if global.number[1] == n then\n"
        "      current_player.number[0] = n\n"
        "   end\n"
        "end\n"
    )
    text = unparse(script)
    assert "n" not in [node.name for node in walk(script) if isinstance(node, Identifier)]
    assert "global.number[1] == global.number[0]" in text
    assert "current_player.number[0] = global.number[0]" in text


def test_alias_as_the_base_of_a_member_chain_and_a_method_call() -> None:
    script = _resolved(
        "alias p = current_player\nalias t = global.timer[0]\n"
        "on init: do\n   p.number[0] = 1\n   t.set_rate(-100%)\nend\n"
    )
    text = unparse(script)
    assert "current_player.number[0] = 1" in text
    assert "global.timer[0].set_rate(-100%)" in text


def test_alias_of_an_alias_resolves_through_the_chain() -> None:
    script = _resolved("alias a = global.number[0]\nalias b = a\non init: do\n   b = 2\nend\n")
    assert _rendered_assignments(script) == ["global.number[0] = 2"]


def test_alias_declared_in_a_block_is_not_visible_after_its_end() -> None:
    script = _resolved(
        "on init: do\n"
        "   if global.number[0] == 0 then\n"
        "      alias z = global.number[1]\n"
        "      z = 1\n"
        "   end\n"
        "   z = 2\n"
        "end\n"
    )
    assert _rendered_assignments(script) == ["global.number[1] = 1", "z = 2"]


def test_inner_alias_shadows_outer_and_the_outer_is_restored_after_the_block() -> None:
    script = _resolved(
        "alias x = global.number[0]\n"
        "on init: do\n"
        "   do\n"
        "      alias x = global.number[1]\n"
        "      x = 1\n"
        "   end\n"
        "   x = 2\n"
        "end\n"
    )
    assert _rendered_assignments(script) == ["global.number[1] = 1", "global.number[0] = 2"]


def test_redeclaring_a_name_in_the_same_scope_rebinds_it() -> None:
    script = _resolved(
        "alias x = global.number[0]\nalias x = global.number[1]\non init: do\n   x = 1\nend\n"
    )
    assert _rendered_assignments(script) == ["global.number[1] = 1"]


def test_a_use_before_the_declaration_is_left_alone() -> None:
    script = _resolved("on init: do\n   x = 1\nend\nalias x = global.number[0]\n")
    assert _rendered_assignments(script) == ["x = 1"]


def test_function_bodies_see_earlier_top_level_aliases_but_not_later_ones() -> None:
    script = _resolved(
        "function early()\n   n = 1\nend\n"
        "alias n = global.number[0]\n"
        "function late()\n   n = 2\nend\n"
    )
    assert _rendered_assignments(script) == ["n = 1", "global.number[0] = 2"]


def test_altif_and_alt_bodies_each_get_their_own_scope() -> None:
    script = _resolved(
        "alias v = global.number[0]\n"
        "on init: do\n"
        "   if v == 0 then\n"
        "      alias v = global.number[1]\n"
        "      v = 1\n"
        "   altif v == 1 then\n"
        "      v = 2\n"
        "   alt\n"
        "      v = 3\n"
        "   end\n"
        "end\n"
    )
    assert _rendered_assignments(script) == [
        "global.number[1] = 1", "global.number[0] = 2", "global.number[0] = 3",
    ]


def test_declare_values_are_substituted_and_for_each_bodies_are_resolved() -> None:
    script = _resolved(
        "alias start = 7\nalias n = global.number[1]\n"
        "declare global.number[0] = start\n"
        'on init: for each object with label "hill" do\n   n = 1\nend\n'
    )
    text = unparse(script)
    assert "declare global.number[0]" in text and "= 7" in text
    assert 'with label "hill"' in text
    assert _rendered_assignments(script) == ["global.number[1] = 1"]


def test_an_alias_as_a_lone_event_body_leaves_an_empty_do_block() -> None:
    script = _resolved("on init: alias x = global.number[0]\n")
    assert unparse(script).strip().splitlines()[0].startswith("on init:")
    assert not any(isinstance(n, AliasDeclaration) for n in walk(script))


def test_a_bare_callee_identifier_is_never_treated_as_an_alias() -> None:
    script = _resolved("alias helper = global.number[0]\nfunction helper()\n   global.number[1] = 1\nend\non init: do\n   helper()\nend\n")
    calls = [n for n in walk(script) if isinstance(n, Call)]
    assert [render_expr(c) for c in calls] == ["helper()"]


@pytest.mark.parametrize("name", sorted(RESERVED_NAMES))
def test_a_reserved_name_cannot_be_aliased(name: str) -> None:
    with pytest.raises(MegaloAliasError, match=r"line 1"):
        _resolved(f"alias {name} = global.number[0]\n")


def test_the_error_reports_the_declarations_own_line() -> None:
    with pytest.raises(MegaloAliasError, match=r"line 4: 'number'"):
        _resolved("on init: do\n   global.number[0] = 1\nend\nalias number = global.number[1]\n")


def test_the_input_script_is_not_mutated() -> None:
    original = parse("alias x = global.number[0]\non init: do\n   x = 1\nend\n")
    before = original.model_dump_json()
    resolve_aliases(original)
    assert original.model_dump_json() == before


def test_a_script_without_aliases_comes_back_structurally_identical() -> None:
    text = "declare global.number[0]\non init: do\n   global.number[0] = 1\nend\n"
    original = parse(text)
    assert resolve_aliases(original) == original


def test_substituted_expressions_carry_the_use_sites_span() -> None:
    script = _resolved("alias n = global.number[0]\n\n\non init: do\n   n = 1\nend\n")
    assign = next(n for n in walk(script) if isinstance(n, Assignment))
    lines = {node.span.start_line for node in walk(assign.target)}
    assert lines == {5}  # the `n = 1` line, not the `alias` line (1)


def test_substituted_values_are_independent_copies() -> None:
    script = _resolved("alias n = global.number[0]\non init: do\n   n = 1\n   n = 2\nend\n")
    first, second = [n for n in walk(script) if isinstance(n, Assignment)]
    assert first.target is not second.target


# -- oracle: native compile_script() agrees with the resolved text -------------------------------

_ORACLE_SCRIPTS = {
    "top-level alias": "alias x = global.number[0]\non init: do\n   x = 1\nend\n",
    "alias of literal": "alias five = 5\non init: do\n   global.number[0] = five\nend\n",
    "alias of timer + method": "alias t = global.timer[0]\non init: do\n   t.set_rate(-100%)\nend\n",
    "alias of self-reference": "alias p = current_player\nfor each player do\n   p.number[0] = 1\nend\n",
    "alias as call argument": "alias n = global.number[0]\non init: do\n   current_player.number[0] = n\nend\n",
    "alias on a compound assignment": "alias n = global.number[0]\non init: do\n   n += 1\nend\n",
    "alias as the right operand": (
        "alias n = global.number[0]\n"
        "on init: do\n   if global.number[1] == n then\n      global.number[1] = 1\n   end\nend\n"
    ),
    "inner shadows outer": (
        "alias x = global.number[0]\non init: do\n   alias x = global.number[1]\n   x = 1\nend\n"
    ),
    "redeclare in the same scope": (
        "alias x = global.number[0]\nalias x = global.number[1]\non init: do\n   x = 1\nend\n"
    ),
    "alias of an alias inside a block": (
        "alias n = global.number[0]\non init: do\n   alias m = n\n   m = 2\nend\n"
    ),
    "function body sees a top-level alias": (
        "alias n = global.number[0]\nfunction f()\n   n = 1\nend\non init: do\n   f()\nend\n"
    ),
}


def _native_script(rvt, text: str) -> str:
    variant = rvt.load(str(resolve_blank_variant(firefight=False)))
    result = variant.multiplayer.compile_script(text)
    assert result.success, [m.text for m in list(result.fatal_errors) + list(result.errors)]
    return normalize_script_text(variant.decompile_script())


@_NEEDS_NATIVE_RVT
@pytest.mark.parametrize("name", list(_ORACLE_SCRIPTS))
def test_resolved_text_compiles_natively_to_the_same_script_as_the_aliased_text(name: str) -> None:
    rvt = rvt_bridge.get_rvt()
    source = _ORACLE_SCRIPTS[name]
    assert _native_script(rvt, unparse(_resolved(source))) == _native_script(rvt, source)


@_NEEDS_NATIVE_RVT
def test_native_also_rejects_use_of_an_alias_after_its_block_ends() -> None:
    rvt = rvt_bridge.get_rvt()
    variant = rvt.load(str(resolve_blank_variant(firefight=False)))
    result = variant.multiplayer.compile_script(
        "on init: do\n   if global.number[0] == 0 then\n      alias z = global.number[1]\n      z = 1\n   end\n   z = 2\nend\n"
    )
    assert not result.success


# -- end to end: the in-house compiler now handles aliases itself ---------------------------------


@pytest.fixture
def juggernaut():
    rvt = rvt_bridge.get_rvt()
    return rvt, lambda: rvt.load(str(_JUGGERNAUT_BIN))


@_NEEDS_NATIVE_RVT
def test_compile_script_compiles_an_aliased_script_identically_to_its_concrete_spelling(juggernaut) -> None:
    rvt, load = juggernaut
    aliased = load()
    concrete = load()
    megalo_compiler.compile_script(
        rvt, aliased,
        "alias score = global.number[0]\nscore = 1\nif score == 1 then\n   game.end_round()\nend\n",
    )
    megalo_compiler.compile_script(
        rvt, concrete, "global.number[0] = 1\nif global.number[0] == 1 then\n   game.end_round()\nend\n"
    )
    assert normalize_script_text(aliased.decompile_script()) == normalize_script_text(concrete.decompile_script())


@_NEEDS_NATIVE_RVT
def test_compile_script_rejects_a_reserved_alias_name_as_unsupported_so_the_native_compiler_reports_it(juggernaut) -> None:
    rvt, load = juggernaut
    with pytest.raises(megalo_compiler.UnsupportedConstruct, match="alias error"):
        megalo_compiler.compile_script(rvt, load(), "alias current_player = global.player[0]\n")


@_NEEDS_NATIVE_RVT
def test_the_native_compiler_also_rejects_that_reserved_alias_name(juggernaut) -> None:
    rvt, load = juggernaut
    result = load().multiplayer.compile_script("alias current_player = global.player[0]\non init: do\nend\n")
    assert not result.success
