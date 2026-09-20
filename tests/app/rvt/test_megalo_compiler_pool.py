"""The supplementary template pool as :func:`~in_reach.app.rvt.megalo_compiler.compile_script` uses it,
plus the compiler features that were needed to make a script written against a *blank* base compile
in-house at all (flag ``|`` combinations, ``none`` in flag/string/timer slots, ``script_option[N]``
in an ``_any_variable`` slot).

Every "compiles with the pool" test has a twin proving it *doesn't* without one -- otherwise a pool
that quietly did nothing (because the base already supplied everything) would pass them all.
"""
import logging
import tempfile
from pathlib import Path

import pytest

from in_reach.app import new_project, project
from in_reach.app.blank_variant import resolve_blank_variant
from in_reach.app.rvt import compile as compile_module
from in_reach.app.rvt import megalo_compiler, rvt_bridge, template_source
from in_reach.app.rvt.decompile import normalize_script_text

_JUGGERNAUT_BIN = Path(__file__).parent / "resources" / "juggernaut" / "juggernaut.bin"

pytestmark = pytest.mark.skipif(
    not rvt_bridge.is_available(), reason="native _reachvarianttool extension not available on this platform"
)
_NEEDS_JUGGERNAUT = pytest.mark.skipif(not _JUGGERNAUT_BIN.is_file(), reason="juggernaut fixture .bin not present")


@pytest.fixture(scope="module")
def rvt():
    return rvt_bridge.get_rvt()


@pytest.fixture
def blank(rvt):
    return rvt.load(str(resolve_blank_variant(firefight=False)))


def _pool(rvt):
    return lambda: template_source.build_variants(rvt)


def _compile(rvt, variant, source: str, *, pool: bool = True) -> str:
    """Compiles ``source`` in-house into ``variant`` and returns the decompiled result, read back
    through a real save/reload (what a shipped ``.bin`` would actually contain)."""
    megalo_compiler.compile_script(rvt, variant, source, template_pool=_pool(rvt) if pool else None)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "out.bin"
        variant.save(str(path))
        return normalize_script_text(rvt.load(str(path)).decompile_script())


_LOOP = (
    "for each player do\n"
    "   if current_player.number[0] == 1 and global.number[0] != 2 then\n"
    "      current_player.number[1] += 1\n"
    "      current_player.timer[0].set_rate(-150%)\n"
    "   end\n"
    "end\n"
)


# -- the pool is what makes a blank base workable --------------------------------------------------


def test_a_script_needing_many_shapes_compiles_in_house_on_a_blank_base_with_the_pool(rvt, blank) -> None:
    text = _compile(rvt, blank, _LOOP)
    assert "current_player.number[1] += 1" in text
    assert "current_player.timer[0].set_rate(-150%)" in text
    assert "if current_player.number[0] == 1 and global.number[0] != 2 then" in text


def test_the_same_script_is_unsupported_on_a_blank_base_without_the_pool(rvt, blank) -> None:
    with pytest.raises(megalo_compiler.UnsupportedConstruct, match="no existing"):
        megalo_compiler.compile_script(rvt, blank, _LOOP)


def test_a_percent_rate_not_in_the_engines_supported_set_is_unsupported_even_with_the_pool(rvt, blank) -> None:
    with pytest.raises(megalo_compiler.UnsupportedConstruct):
        megalo_compiler.compile_script(
            rvt, blank, "for each player do\n   current_player.timer[0].set_rate(20%)\nend\n", template_pool=_pool(rvt)
        )


def test_a_chained_reference_at_the_far_end_of_its_pool_compiles_from_the_pool(rvt, blank) -> None:
    source = "global.number[0] = global.object[15].number[7]\n"
    assert "global.number[0] = global.object[15].number[7]" in _compile(rvt, blank, source)


def test_a_trailing_biped_chain_compiles_from_the_pool(rvt, blank) -> None:
    source = "global.object[1] = global.object[0].player[3].biped\n"
    assert "global.object[1] = global.object[0].player[3].biped" in _compile(rvt, blank, source)


def test_a_chain_past_a_pools_real_size_is_still_unsupported_with_the_pool(rvt, blank) -> None:
    # object slot 16 doesn't exist (there are 16, numbered 0-15), so no example of it does either.
    with pytest.raises(megalo_compiler.UnsupportedConstruct):
        megalo_compiler.compile_script(
            rvt, blank, "global.number[0] = global.object[16].number[0]\n", template_pool=_pool(rvt)
        )


def test_a_blank_base_with_the_pool_declares_what_the_script_uses_as_native_does(rvt, blank) -> None:
    """The in-house compiler declares every variable the script uses -- the same declarations native
    emits -- so a script written against a blank base comes out identical either way."""
    megalo_compiler.compile_script(rvt, blank, _LOOP, template_pool=_pool(rvt))
    native = rvt.load(str(resolve_blank_variant(firefight=False)))
    assert native.multiplayer.compile_script(_LOOP).success
    assert "declare player.number[0]" in normalize_script_text(native.decompile_script())
    assert normalize_script_text(blank.decompile_script()) == normalize_script_text(native.decompile_script())


# -- when the pool is (and isn't) built ---------------------------------------------------------


@_NEEDS_JUGGERNAUT
def test_the_pool_is_never_built_when_the_base_supplies_everything_the_script_needs(rvt) -> None:
    calls: list[int] = []

    def provider():
        calls.append(1)
        return template_source.build_variants(rvt)

    variant = rvt.load(str(_JUGGERNAUT_BIN))
    megalo_compiler.compile_script(
        rvt, variant, "global.number[0] = 1\nif global.number[0] == 1 then\n   game.end_round()\nend\n",
        template_pool=provider,
    )
    assert calls == []


def test_the_pool_is_built_at_most_once_however_many_lookups_miss(rvt, blank) -> None:
    calls: list[int] = []

    def provider():
        calls.append(1)
        return template_source.build_variants(rvt)

    megalo_compiler.compile_script(rvt, blank, _LOOP, template_pool=provider)
    assert calls == [1]


def test_no_pool_means_none_is_ever_needed_or_built(rvt, blank) -> None:
    compiler = megalo_compiler._Compiler(rvt, blank)
    assert compiler._load_pool() is False


def test_load_pool_reports_true_only_on_the_call_that_actually_loaded_it(rvt, blank) -> None:
    compiler = megalo_compiler._Compiler(rvt, blank, template_pool=_pool(rvt))
    assert compiler._load_pool() is True
    assert compiler._load_pool() is False


def test_a_template_the_base_already_has_wins_over_the_pools() -> None:
    own, borrowed = object(), object()
    into = megalo_compiler._Templates()
    into.variables[("player", "current_player")] = own
    extra = megalo_compiler._Templates()
    extra.variables[("player", "current_player")] = borrowed
    extra.variables[("timer", "global.timer[]")] = borrowed
    extra.literal_variables[("timer", "global.object[0].timer[0]")] = borrowed
    extra.trigger_ref = extra.literal_scalar = borrowed

    megalo_compiler._merge_templates(into, extra)

    assert into.variables[("player", "current_player")] is own
    assert into.variables[("timer", "global.timer[]")] is borrowed
    assert into.literal_variables[("timer", "global.object[0].timer[0]")] is borrowed
    assert into.trigger_ref is borrowed and into.literal_scalar is borrowed


def test_merging_never_overwrites_a_trigger_ref_or_literal_the_base_has() -> None:
    own, borrowed = object(), object()
    into = megalo_compiler._Templates(trigger_ref=own, literal_scalar=own)
    extra = megalo_compiler._Templates(trigger_ref=borrowed, literal_scalar=borrowed)
    megalo_compiler._merge_templates(into, extra)
    assert into.trigger_ref is own and into.literal_scalar is own


def test_merging_leaves_the_target_variants_own_strings_alone() -> None:
    into = megalo_compiler._Templates(strings={"kept": object()})
    extra = megalo_compiler._Templates(strings={"foreign": object()})
    megalo_compiler._merge_templates(into, extra)
    assert set(into.strings) == {"kept"}


# -- compiler features the blank-base path needed ---------------------------------------------------


def test_flags_combine_with_a_bar_and_decompile_in_bit_order(rvt, blank) -> None:
    source = "for each player do\n   if current_player.killer_type_is(suicide | guardians) then\n      game.end_round()\n   end\nend\n"
    assert "killer_type_is(guardians | suicide)" in _compile(rvt, blank, source)


def test_three_flags_and_a_non_adjacent_pair_both_resolve_to_the_right_bits(rvt) -> None:
    for written, expected in (("guardians | suicide | kill", "guardians | suicide | kill"), ("kill | guardians", "guardians | kill")):
        variant = rvt.load(str(resolve_blank_variant(firefight=False)))
        source = f"for each player do\n   if current_player.killer_type_is({written}) then\n      game.end_round()\n   end\nend\n"
        assert f"killer_type_is({expected})" in _compile(rvt, variant, source)


def test_a_single_flag_and_none_still_work(rvt) -> None:
    for written in ("guardians", "none"):
        variant = rvt.load(str(resolve_blank_variant(firefight=False)))
        source = f"for each player do\n   if current_player.killer_type_is({written}) then\n      game.end_round()\n   end\nend\n"
        assert f"killer_type_is({written})" in _compile(rvt, variant, source)


def test_an_unknown_flag_name_is_unsupported_rather_than_a_wrong_value(rvt, blank) -> None:
    source = "for each player do\n   if current_player.killer_type_is(guardians | not_a_flag) then\n      game.end_round()\n   end\nend\n"
    with pytest.raises(megalo_compiler.UnsupportedConstruct):
        megalo_compiler.compile_script(rvt, blank, source, template_pool=_pool(rvt))


def test_a_bar_between_things_that_are_not_names_is_unsupported(rvt, blank) -> None:
    source = "for each player do\n   if current_player.killer_type_is(guardians | 3) then\n      game.end_round()\n   end\nend\n"
    with pytest.raises(megalo_compiler.UnsupportedConstruct):
        megalo_compiler.compile_script(rvt, blank, source, template_pool=_pool(rvt))


def test_none_is_a_valid_object_timer(rvt, blank) -> None:
    source = "for each object do\n   current_object.set_waypoint_timer(none)\nend\n"
    assert "set_waypoint_timer(none)" in _compile(rvt, blank, source)


def test_an_option_can_be_read_in_an_any_variable_slot_with_no_example_to_copy(rvt, blank) -> None:
    text = _compile(rvt, blank, "global.number[0] = script_option[3]\n")
    assert "global.number[0] = script_option[3]" in text


def test_an_option_index_past_the_engines_option_limit_is_rejected(rvt, blank) -> None:
    with pytest.raises(megalo_compiler.UnsupportedConstruct, match="out of range"):
        megalo_compiler.compile_script(rvt, blank, "global.number[0] = script_option[16]\n", template_pool=_pool(rvt))


def test_a_bare_none_no_longer_pre_empts_the_enum_fallback_for_a_slot_that_isnt_a_variable(rvt, blank) -> None:
    """``none`` is also a variable constant, so a "no template" error used to fire before the enum
    path could accept it as a plain enum member."""
    source = "for each player do\n   if current_player.killer_type_is(none) then\n      game.end_round()\n   end\nend\n"
    assert "killer_type_is(none)" in _compile(rvt, blank, source)


# -- alias + pool together --------------------------------------------------------------------------


def test_an_aliased_script_compiles_on_a_blank_base_with_the_pool(rvt, blank) -> None:
    source = (
        "alias score = current_player.number[0]\n"
        "for each player do\n"
        "   if global.number[0] == score then\n"
        "      current_player.timer[0].set_rate(-150%)\n"
        "   end\n"
        "end\n"
    )
    assert "if global.number[0] == current_player.number[0] then" in _compile(rvt, blank, source)


# -- through compile.run_compile() -----------------------------------------------------------------


def _project(tmp_path: Path, *, source_variant: Path) -> tuple[Path, Path]:
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir(parents=True)
    folder, warning = new_project.create_gametype_project(project_dir, "Pool Test", source_variant=source_variant)
    assert warning is None
    return project_dir, folder


def test_run_compile_builds_a_blank_based_project_with_the_in_house_compiler(tmp_path: Path, caplog) -> None:
    project_dir, folder = _project(tmp_path, source_variant=resolve_blank_variant(firefight=False))
    (folder / "script" / "output.txt").write_text(_LOOP.replace("\n", "\r\n"), encoding="utf-8")

    # In-process, unlike run_compile()'s isolated child, so the fallback log line can be observed.
    with caplog.at_level(logging.INFO, logger="in_reach"):
        result = compile_module._run_compile_in_process(project_dir, folder, save=True)

    assert result.success is True, compile_module.format_build_result(result)
    # Proof this didn't just fall back to native compile_script(), which a blank base used to force.
    assert not [record for record in caplog.records if "falling back" in record.getMessage()]
    compiled = rvt_bridge.get_rvt().load(str(result.output_path))
    text = compiled.decompile_script()
    assert "current_player.timer[0].set_rate(-150%)" in text
    assert "declare player.number[0]" in text
