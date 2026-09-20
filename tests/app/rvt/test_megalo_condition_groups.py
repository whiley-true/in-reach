"""How ``and``/``or``/``not`` in a condition mean what they mean in Megalo -- and stay correct.

In Megalo ``or`` binds *tighter* than ``and`` (the reverse of most languages), because that's how the
engine stores a condition list: each condition carries an ``or_group``; ``or`` puts a condition in the
previous one's group and ``and`` starts a new group, so ``a and b or c`` is ``a and (b or c)`` -- groups
``[0, 1, 1]`` -- and ``not`` takes a single term. Native compilation confirms it, and also rejects any
parenthesized condition.

This repo used to parse the other way round (``(a and b) or c``), which for a mixed expression both
inflated the condition count (CNF distribution: 4 conditions where the source had 3 -- enough to push
a real 510-condition script past the engine's 512 cap) and quietly changed what the condition *meant*.
The tests below pin the right reading three ways: the tree shape, agreement with the native compiler on
everything native accepts, and -- for the parenthesized forms native can't compile at all -- a truth
table proving the compiled groups compute the expression's own value for every input.
"""
import itertools
import random
import re

import pytest

from in_reach.app.blank_variant import resolve_blank_variant
from in_reach.app.rvt import megalo_compiler, rvt_bridge, template_source
from in_reach.app.rvt.megalo_ast import parse, render_expr

# -- tree shape and round trip (no native extension needed) ----------------------------------------------


def _shape(expr) -> str:
    """A fully parenthesized rendering of ``expr``'s tree, so the tree itself is what's compared."""
    if expr.kind == "binary" and expr.op in ("and", "or"):
        return f"({_shape(expr.left)} {expr.op} {_shape(expr.right)})"
    if expr.kind == "unary":
        return f"(not {_shape(expr.operand)})"
    return render_expr(expr)


def _tree(text: str) -> str:
    return _shape(parse(f"x = {text}\n").body[0].value)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("a and b or c", "(a and (b or c))"),
        ("a or b and c", "((a or b) and c)"),
        ("a and b or c and d", "((a and (b or c)) and d)"),
        ("a or b or c", "((a or b) or c)"),
        ("a and b and c", "((a and b) and c)"),
        ("not a or b", "((not a) or b)"),
        ("a and not b or c", "(a and ((not b) or c))"),
        ("a == 1 and b == 2 or c == 3", "(a == 1 and (b == 2 or c == 3))"),
    ],
)
def test_or_binds_tighter_than_and(text: str, expected: str) -> None:
    assert _tree(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("(a and b) or c", "((a and b) or c)"),
        ("a and (b and c)", "(a and (b and c))"),
        ("not (a or b)", "(not (a or b))"),
        ("(a or b) and c", "((a or b) and c)"),
    ],
)
def test_parentheses_still_override_it(text: str, expected: str) -> None:
    assert _tree(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "a and b or c", "a or b and c", "a and b or c and d", "not a or b", "a == b and c or d", "a | b == c or d",
        "(a and b) or c", "a and (b and c)", "not (a or b)", "(a or b) and c", "not not a", "a and (b or c) and d",
    ],
)
def test_rendering_an_expression_reparses_to_the_same_tree(text: str) -> None:
    rendered = render_expr(parse(f"x = {text}\n").body[0].value)
    assert _tree(rendered) == _tree(text)


@pytest.mark.parametrize(
    "text", ["a and b or c", "a or b and c", "a and b or c and d", "not a or b", "a == 1 and b == 2 or c == 3"]
)
def test_flat_text_renders_exactly_as_written(text: str) -> None:
    """What decompiling a condition list produces (a flat chain) must come back unchanged."""
    assert render_expr(parse(f"x = {text}\n").body[0].value) == text


def test_a_not_over_a_group_keeps_its_parentheses() -> None:
    """``not (a or b)`` used to print as ``not a or b`` -- a different condition."""
    assert render_expr(parse("x = not (a or b)\n").body[0].value) == "not (a or b)"


# -- agreement with the native compiler ----------------------------------------------------------------------

pytestmark_native = pytest.mark.skipif(
    not rvt_bridge.is_available(), reason="native _reachvarianttool extension not available on this platform"
)

_A, _B, _C, _D = (f"global.number[{i}] == {i + 1}" for i in range(4))


def _structure(variant, rvt):
    """The condition list of the variant's last trigger as ``[(term text, or_group renumbered by first
    appearance, inverted)]`` -- comparable between compilers that number groups differently."""
    mp = variant.multiplayer
    top = mp.trigger(mp.trigger_count - 1)
    conditions = [top.opcode(i) for i in range(top.opcode_count) if isinstance(top.opcode(i), rvt.Condition)]
    renumber: dict[int, int] = {}
    return [
        (c.decompile(variant), renumber.setdefault(c.or_group, len(renumber)), bool(c.inverted)) for c in conditions
    ]


def _compile_native(rvt, condition: str):
    variant = rvt.load(str(resolve_blank_variant(firefight=False)))
    result = variant.multiplayer.compile_script(f"if {condition} then\n   game.end_round()\nend\n")
    return variant, result


def _compile_in_house(rvt, condition: str):
    variant = rvt.load(str(resolve_blank_variant(firefight=False)))
    megalo_compiler.compile_script(
        rvt, variant, f"if {condition} then\n   game.end_round()\nend\n", template_pool=lambda: template_source.build_variants(rvt)
    )
    return variant


@pytest.fixture(scope="module")
def rvt():
    return rvt_bridge.get_rvt()


@pytestmark_native
@pytest.mark.parametrize(
    "condition",
    [
        f"{_A} and {_B} or {_C}",
        f"{_A} or {_B} and {_C}",
        f"{_A} or {_B} or {_C}",
        f"{_A} and {_B} and {_C}",
        f"{_A} and {_B} or {_C} and {_D}",
        f"{_A} or {_B} and {_C} or {_D}",
        f"not {_A} or {_B}",
        f"{_A} and not {_B} or {_C}",
        f"not {_A} and not {_B} or not {_C}",
        f"{_A} or not {_B} and {_C} or {_D} and not {_A}",
    ],
)
def test_in_house_builds_the_same_condition_list_native_does(rvt, condition: str) -> None:
    native_variant, result = _compile_native(rvt, condition)
    assert result.success, [m.text for m in list(result.fatal_errors) + list(result.errors)]
    in_house = _compile_in_house(rvt, condition)
    assert _structure(in_house, rvt) == _structure(native_variant, rvt)


@pytestmark_native
def test_a_mixed_expression_no_longer_costs_more_conditions_than_it_has_terms(rvt) -> None:
    """The regression that started this: `a and b or c` is three conditions, not four."""
    variant = _compile_in_house(rvt, f"{_A} and {_B} or {_C}")
    assert len(_structure(variant, rvt)) == 3


@pytestmark_native
@pytest.mark.parametrize("condition", [f"({_A} and {_B}) or {_C}", f"{_A} and ({_B} or {_C})", f"not ({_A} or {_B})"])
def test_native_cannot_compile_a_parenthesized_condition_at_all(rvt, condition: str) -> None:
    _, result = _compile_native(rvt, condition)
    assert not result.success


# -- a truth table for what native can't compile -----------------------------------------------------------------

_ATOM = re.compile(r"global\.number\[(\d)\] == \d")  # searched, not fully matched: a negated term reads "not <atom>"


def _evaluate_tree(expr, env: dict[int, bool]) -> bool:
    if expr.kind == "binary" and expr.op == "and":
        return _evaluate_tree(expr.left, env) and _evaluate_tree(expr.right, env)
    if expr.kind == "binary" and expr.op == "or":
        return _evaluate_tree(expr.left, env) or _evaluate_tree(expr.right, env)
    if expr.kind == "unary":
        return not _evaluate_tree(expr.operand, env)
    return env[int(_ATOM.search(render_expr(expr)).group(1))]


def _evaluate_compiled(structure, env: dict[int, bool]) -> bool:
    """The engine's own reading of a condition list: OR within an ``or_group``, AND across them."""
    groups: dict[int, bool] = {}
    for text, group, inverted in structure:
        value = env[int(_ATOM.search(text).group(1))] != inverted
        groups[group] = groups.get(group, False) or value
    return all(groups.values())


def _random_condition(rng: random.Random, depth: int) -> str:
    if depth == 0 or rng.random() < 0.25:
        atom = f"global.number[{rng.randrange(4)}] == {rng.randrange(1, 5)}"
        return f"not {atom}" if rng.random() < 0.25 else atom
    left, right = _random_condition(rng, depth - 1), _random_condition(rng, depth - 1)
    combined = f"({left}) {rng.choice(['and', 'or'])} ({right})"
    return f"not ({combined})" if rng.random() < 0.15 else combined


@pytestmark_native
def test_the_compiled_groups_compute_each_expressions_own_value_for_every_input(rvt) -> None:
    rng = random.Random(20260919)
    checked = 0
    for _ in range(120):
        condition = _random_condition(rng, rng.choice([1, 2, 2, 3]))
        expr = parse(f"x = {condition}\n").body[0].value
        try:
            variant = _compile_in_house(rvt, condition)
        except megalo_compiler.UnsupportedConstruct:
            continue  # too large to expand safely -- an intended limit, not a wrong answer
        structure = _structure(variant, rvt)
        for values in itertools.product([False, True], repeat=4):
            env = dict(enumerate(values))
            assert _evaluate_compiled(structure, env) == _evaluate_tree(expr, env), (condition, env)
        checked += 1
    assert checked >= 60  # the generator must actually exercise the compiler, not skip most cases


@pytestmark_native
def test_an_or_of_ands_distributes_into_two_groups_with_the_shared_term_in_both(rvt) -> None:
    structure = _structure(_compile_in_house(rvt, f"({_A} and {_B}) or {_C}"), rvt)
    groups: dict[int, list[str]] = {}
    for text, group, _ in structure:
        groups.setdefault(group, []).append(text)
    assert sorted(groups.values()) == [[_A, _C], [_B, _C]]


# -- the case that surfaced it ---------------------------------------------------------------------------------------


@pytestmark_native
def test_the_condition_count_of_a_recompiled_script_equals_its_terms_not_more(rvt) -> None:
    """Twenty mixed conditions of three terms each. Before the fix they compiled to four apiece (80 vs
    60) -- which is how a real 510-condition script became 540 and lost its in-house build."""
    variant = rvt.load(str(resolve_blank_variant(firefight=False)))
    source = "".join(f"if {_A} and {_B} or {_C} then\n   current_player.number[0] = {i}\nend\n" for i in range(20))
    megalo_compiler.compile_script(rvt, variant, source, template_pool=lambda: template_source.build_variants(rvt))
    assert variant.multiplayer.get_full_size_data().counts["conditions"] == 20 * 3
