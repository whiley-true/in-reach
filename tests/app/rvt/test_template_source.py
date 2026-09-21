"""Coverage for :mod:`in_reach.app.rvt.template_source` -- the synthetic argument-template pool.

The pool is only worth anything if (a) the *native* compiler accepts every statement it generates
(otherwise building it fails and the compiler silently loses it), (b) it fits the engine's own caps,
and (c) the variants it builds really contain the examples a blank base lacks. Each is asserted
directly. The tables are engine facts learned from the native compiler (how deep a reference may go,
what a null can and can't do) -- tests that pin them both ways (accepted *and*
rejected) keep them honest if the engine ever changes underneath.
"""
import re

import pytest

from in_reach.app.blank_variant import resolve_blank_variant
from in_reach.app.rvt import megalo_compiler, rvt_bridge, template_source

pytestmark = pytest.mark.skipif(
    not rvt_bridge.is_available(), reason="native _reachvarianttool extension not available on this platform"
)


@pytest.fixture(scope="module")
def rvt():
    return rvt_bridge.get_rvt()


@pytest.fixture(scope="module")
def pool(rvt):
    """Every template the pool yields, scanned exactly as ``compile_script`` scans it."""
    merged = megalo_compiler._Templates()
    variants = template_source.build_variants(rvt)  # kept alive while scanned -- see _load_pool()
    for variant in variants:
        megalo_compiler._merge_templates(merged, megalo_compiler._scan_templates(rvt, variant, variant.multiplayer))
    merged._keepalive = variants
    return merged


def _native_accepts(rvt, statement: str) -> bool:
    variant = rvt.load(str(resolve_blank_variant(firefight=False)))
    return variant.multiplayer.compile_script("on init: do\n   " + statement + "\nend\n").success


# -- generation ---------------------------------------------------------------------------------


def test_statements_are_deterministic_and_never_repeat() -> None:
    first = template_source.statements()
    assert first == template_source.statements()
    texts = [statement for statement, _ in first]
    assert len(texts) == len(set(texts))


def test_scripts_are_deterministic() -> None:
    assert template_source.scripts() == template_source.scripts()


def test_every_generated_script_compiles_natively(rvt) -> None:
    for script in template_source.scripts():
        variant = rvt.load(str(resolve_blank_variant(firefight=False)))
        result = variant.multiplayer.compile_script(script)
        assert result.success, [m.text for m in list(result.fatal_errors) + list(result.errors)][:3]


def test_build_variants_returns_one_variant_per_script(rvt) -> None:
    assert len(template_source.build_variants(rvt)) == len(template_source.scripts())


def test_a_script_native_rejects_raises_instead_of_yielding_a_broken_pool(rvt, monkeypatch) -> None:
    monkeypatch.setattr(template_source, "scripts", lambda: ["this is not megalo\n"])
    with pytest.raises(RuntimeError, match="template pool failed to compile natively"):
        template_source.build_variants(rvt)


def test_every_variant_stays_inside_the_engines_caps(rvt) -> None:
    for variant in template_source.build_variants(rvt):
        mp = variant.multiplayer
        assert mp.trigger_count <= 320  # Limits::max_triggers
        assert sum(mp.trigger(i).opcode_count for i in range(mp.trigger_count)) <= 1024  # max_actions


def test_each_variant_survives_a_save_and_reload(rvt, tmp_path) -> None:
    """A pool that exceeded a cap would compile natively but not load back (see compile.py's own
    save/reload probe for the same failure mode)."""
    for i, variant in enumerate(template_source.build_variants(rvt)):
        path = tmp_path / f"pool{i}.bin"
        variant.save(str(path))
        rvt.load(str(path))


# -- the shape tables ---------------------------------------------------------------------------


def test_every_owner_slot_and_member_slot_of_a_chain_is_covered() -> None:
    statements = {statement for statement, _ in template_source.statements()}
    # global.object has 16 slots, each with 8 numbers / 4 timers / 4 objects / 4 players.
    for n in range(16):
        for m in range(8):
            assert f"global.number[0] = global.object[{n}].number[{m}]" in statements
        for m in range(4):
            assert f"global.object[{n}].timer[{m}].reset()" in statements
            assert f"global.object[{n}].object[{m}].delete()" in statements


def test_chains_past_a_pools_real_size_are_not_generated() -> None:
    statements = {statement for statement, _ in template_source.statements()}
    assert "global.number[0] = global.object[16].number[0]" not in statements  # only 16 object slots
    assert "global.number[0] = global.object[0].number[8]" not in statements  # only 8 numbers per object


def test_a_trailing_biped_may_follow_a_held_player_but_nothing_else_may() -> None:
    statements = {statement for statement, _ in template_source.statements()}
    assert "global.object[0] = global.object[0].player[0].biped" in statements
    # A player held *in* a slot (``x[n].player[m]``) can be followed by a biped, and only a biped;
    # ``global.player[0].number[3]`` is a different thing -- there ``.player[0]`` is the owner itself.
    # (A *method call* on it, ``x[n].player[m].is_spartan()``, is fine -- it isn't another level.)
    deeper = r"\]\.player\[\d+\]\.(?:(?:number|timer|object|player|team)\[|score\b|rating\b|team\b)"
    assert not any(re.search(deeper, s) for s in statements)


def test_native_agrees_a_trailing_biped_is_the_only_property_allowed_three_levels_deep(rvt) -> None:
    assert _native_accepts(rvt, "global.object[1] = global.object[0].player[0].biped")
    assert not _native_accepts(rvt, "global.number[0] = current_team.player[0].number[0]")
    assert not _native_accepts(rvt, "global.number[0] = current_team.player[0].score")


def test_the_pool_carries_no_timer_rates_because_the_compiler_finds_them_itself(rvt, pool) -> None:
    """``TimerRateArgument.value`` is writable now, so a rate is built by search rather than cloned --
    the pool used to need a hand-maintained table of every rate the engine accepts."""
    assert not any("set_rate" in statement for statement, _ in template_source.statements())
    assert not any(typeinfo == "_timer_rate" for typeinfo, _ in pool.variables)


def test_null_constants_are_assignable_but_have_no_members(rvt) -> None:
    assert _native_accepts(rvt, "global.player[0] = no_player")
    assert _native_accepts(rvt, "global.team[0] = no_team")
    assert _native_accepts(rvt, "global.player[0].score += 1")  # fine on a real player...
    assert not _native_accepts(rvt, "no_player.score += 1")  # ...but a null has no members


def test_no_generated_statement_reads_a_settings_table_slot() -> None:
    """``script_option``/``script_traits``/``script_widget``/``script_stat`` slots only exist if the
    base variant defines them, so a pool statement using one would fail to compile on a blank base."""
    for statement, _ in template_source.statements():
        for table in ("script_option[", "script_traits[", "script_widget[", "script_stat["):
            assert table not in statement


def test_a_condition_is_always_its_own_top_level_trigger() -> None:
    """The native compiler leaves an ``if``'s condition scannable only when nothing follows it in the
    same trigger -- so a conditional statement must never share the ``on init`` block."""
    for script in template_source.scripts():
        block, _, rest = script.partition("\nend\n")
        assert "if " not in block and "for each" not in block
        assert "if " in rest or "for each" in rest or not rest.strip()


def test_an_if_needs_a_body_or_the_native_compiler_drops_it(rvt) -> None:
    variant = rvt.load(str(resolve_blank_variant(firefight=False)))
    script = "on init: do\n   if current_player.is_spartan() then\n   end\nend\n"
    assert variant.multiplayer.compile_script(script).success
    assert variant.multiplayer.trigger(0).opcode_count == 0  # nothing left to scan a template from
    # ...which is why the pool's own conditional form always carries a statement.
    assert "global.number[0] = 1" in template_source._RECEIVER_FORMS[template_source._PLAYER]


# -- what the built pool actually contains -------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        ("_any_variable", "global.number[]"),
        ("_any_variable", "current_player.number[]"),
        ("_any_variable", "current_object.timer[]"),
        ("_any_variable", "temporaries.number[]"),
        ("_any_variable", "hud_player.number[]"),
        ("_any_variable", "INT_LITERAL"),
        ("_any_variable", "game.score_to_win"),
        ("_any_variable", "no_player"),
        ("_any_variable", "killed_object"),
        ("player", "current_player"),
        ("player", "global.player[]"),
        ("object", "current_object"),
        ("object", "current_player.biped"),
        ("timer", "global.timer[]"),
        ("timer", "game.round_timer"),
        ("team", "current_team"),
        ("number", "global.number[]"),
        ("number", "INT_LITERAL"),
        ("_player_or_group", "all_players"),
        ("_player_or_group", "no_team"),
    ],
)
def test_the_pool_supplies_each_index_free_example(pool, key) -> None:
    assert key in pool.variables


@pytest.mark.parametrize(
    "key",
    [
        ("_any_variable", "global.object[15].number[7]"),
        ("_any_variable", "global.player[7].timer[3]"),
        ("_any_variable", "team[7].object[5]"),
        ("_any_variable", "temporaries.object[7].number[0]"),
        ("_any_variable", "neutral_team.object[0]"),
        ("_any_variable", "killed_object.number[4]"),
        ("_any_variable", "global.object[0].player[3].biped"),
        ("object", "global.object[3].object[2]"),
        ("object", "global.player[0].player[1].biped"),
        ("object", "current_team.player[3].biped"),
        ("timer", "global.team[2].timer[3]"),
        ("player", "global.object[0].player[0]"),
    ],
)
def test_the_pool_supplies_each_exact_chain(pool, key) -> None:
    assert key in pool.literal_variables


def test_the_pool_supplies_a_nested_trigger_call_and_an_integer_literal(pool) -> None:
    assert pool.trigger_ref is not None  # what a ``for each`` needs and a blank base can't offer
    assert pool.literal_scalar is not None


def test_a_settings_table_reference_is_not_something_a_pool_can_supply(pool) -> None:
    assert not any(t in ("script_traits", "script_widget") for t, _ in pool.variables)
    assert not any("script_stat" in key for _, key in pool.variables)


def test_the_blank_variant_alone_has_none_of_these(rvt) -> None:
    """The reason the pool exists, pinned: a script on a blank base needs it."""
    blank = rvt.load(str(resolve_blank_variant(firefight=False)))
    own = megalo_compiler._scan_templates(rvt, blank, blank.multiplayer)
    assert ("player", "current_player") not in own.variables
    assert own.trigger_ref is None
    assert own.literal_scalar is None
