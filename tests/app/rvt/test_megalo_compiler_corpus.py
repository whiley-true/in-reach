"""How much of real, shipped Megalo :mod:`in_reach.app.rvt.megalo_compiler` actually covers.

Every scenario here is "recompile a variant's own decompiled script against that same variant" --
the base a real project starts from (see :mod:`in_reach.app.rvt.compile`: ``init_gametype/<id>.bin``),
so its own script supplies the variable templates the compiler clones from. That's deliberately the
*favourable* case: compiling against the packaged blank variant instead has no templates to clone
and falls back to the native compiler for nearly everything (measured: 2 of 426 built-in/hopper/
personal scripts compile in-house against a blank base, vs 425 of 426 against their own) -- a known
gap tracked in :mod:`in_reach.app.rvt.megalo_compiler`'s own docstring, not something this file
pins in place.

The three checked-in fixtures always run (when the native extension is available). A much larger
sweep runs only when ``IN_REACH_CORPUS_DIRS`` names folders of ``.bin`` files (``os.pathsep``-
separated -- e.g. MCC's own ``game_variants``/``hopper_game_variants`` plus a personal variants
folder), since those aren't redistributable and so can't live in this repo::

    IN_REACH_CORPUS_DIRS="C:\\...\\haloreach\\game_variants;C:\\...\\haloreach\\hopper_game_variants" \\
        python -m pytest tests/app/rvt/test_megalo_compiler_corpus.py -q -s
"""
import os
from pathlib import Path

import pytest

from in_reach.app.rvt import megalo_compiler, rvt_bridge, template_source
from in_reach.app.rvt.decompile import normalize_script_text

_FIXTURES_DIR = Path(__file__).parent / "resources"
_FIXTURE_BINS = sorted(_FIXTURES_DIR.glob("*/*.bin"))

#: The sweep's own floor. Measured 423/423 (100%) multiplayer scripts when this was written -- it was
#: 422/423, the one miss being RCC Onslaught v13 (a personal map, 510 of the engine's 512 conditions and
#: 1013 of its 1024 actions). That script needed 540 conditions in-house because the parser had ``and``/
#: ``or`` precedence backwards (Megalo's ``or`` binds tighter, so ``a and b or c`` is three conditions,
#: not four -- see ``test_megalo_condition_groups.py``), and then 1073 actions because every top-level
#: ``for each`` cost an extra "Run Nested Trigger" (see ``test_megalo_top_level_layout.py``). Both are
#: fixed. The floor stays below 100% only because another machine's own variants might legitimately
#: exceed a cap, which the compiler reports by design.
_MIN_CORPUS_COVERAGE = 0.99

pytestmark = pytest.mark.skipif(
    not rvt_bridge.is_available(), reason="native _reachvarianttool extension not available on this platform"
)


def _corpus_bins() -> list[Path]:
    dirs = [Path(p) for p in os.environ.get("IN_REACH_CORPUS_DIRS", "").split(os.pathsep) if p.strip()]
    return sorted(path for folder in dirs if folder.is_dir() for path in folder.glob("*.bin"))


def _recompile_against_itself(rvt, path: Path) -> tuple[bool, str | None]:
    """``(has_script, reason)``. ``has_script`` is ``False`` for a variant with no multiplayer
    script (Firefight) -- nothing to compile, so it must not count toward coverage either way.
    Otherwise ``reason`` is ``None`` if ``path``'s own decompiled script compiles in-house against
    ``path`` itself, or why it didn't."""
    variant = rvt.load(str(path))
    if variant.multiplayer is None:
        return False, None
    source = normalize_script_text(variant.decompile_script())
    try:
        megalo_compiler.compile_script(rvt, variant, source)
    except megalo_compiler.UnsupportedConstruct as exc:
        return True, str(exc)
    return True, None


@pytest.mark.parametrize("path", _FIXTURE_BINS, ids=lambda p: p.stem)
def test_a_fixtures_own_script_compiles_in_house_against_itself(path: Path) -> None:
    has_script, reason = _recompile_against_itself(rvt_bridge.get_rvt(), path)
    assert has_script
    assert reason is None


#: The pool's own floor -- see :func:`test_the_synthetic_pool_alone_covers_the_real_corpus`. Measured
#: 377/377 (100%) when this was written (376/377 before the condition/action fixes described above).
_MIN_POOL_COVERAGE = 0.98

#: The one thing nothing can synthesize any more: a stat on an owner other than ``current_player``
#: (``global.player[3].script_stat[1]``, a team's stat). Widgets, trait sets, options and
#: ``current_player`` stats are all built by the compiler itself now, so they get no exemption here.
def _keeps_from_base(key: tuple[str, str]) -> bool:
    return "script_stat" in key[1] and not key[1].startswith("current_player.script_stat")


@pytest.mark.skipif(not _corpus_bins(), reason="IN_REACH_CORPUS_DIRS not set (or names no .bin files)")
def test_the_synthetic_pool_alone_covers_the_real_corpus() -> None:
    """Every real script, compiled against its own variant with that variant's *own argument templates
    thrown away* -- except a stat on an owner other than ``current_player``, which nothing can
    synthesize -- so only :mod:`~in_reach.app.rvt.template_source` (and the compiler's own builders)
    can supply them. This is the number that says the pool is
    worth having: without it, none of these would compile in-house against a base with no script of
    its own."""
    from in_reach.app.rvt.megalo_ast import parse, resolve_aliases

    rvt = rvt_bridge.get_rvt()
    failures: dict[str, str] = {}
    total = 0
    seen: set[str] = set()
    for path in _corpus_bins():
        if path.name in seen:  # the same file shipped in more than one folder
            continue
        seen.add(path.name)
        try:
            variant = rvt.load(str(path))
        except RuntimeError:
            continue
        if variant.multiplayer is None:
            continue
        total += 1
        source = normalize_script_text(variant.decompile_script())
        compiler = megalo_compiler._Compiler(rvt, variant, template_pool=lambda: template_source.build_variants(rvt))
        own, compiler._templates = compiler._templates, megalo_compiler._Templates(strings=compiler._templates.strings)
        compiler._templates.variables.update({k: v for k, v in own.variables.items() if _keeps_from_base(k)})
        compiler._templates.literal_variables.update({k: v for k, v in own.literal_variables.items() if _keeps_from_base(k)})
        try:
            compiler.compile(resolve_aliases(parse(source)))
        except megalo_compiler.UnsupportedConstruct as exc:
            failures[path.name] = str(exc)
    assert total, "the corpus folders held no multiplayer game variants"
    coverage = 1 - len(failures) / total
    print(f"\npool-only coverage: {total - len(failures)}/{total} ({coverage:.1%})")
    for name, reason in sorted(failures.items()):
        print(f"  unsupported: {name}: {reason[:140]}")
    assert coverage >= _MIN_POOL_COVERAGE


@pytest.mark.skipif(not _corpus_bins(), reason="IN_REACH_CORPUS_DIRS not set (or names no .bin files)")
def test_real_variant_corpus_coverage_stays_above_the_floor() -> None:
    rvt = rvt_bridge.get_rvt()
    failures: dict[str, str] = {}
    total = 0
    for path in _corpus_bins():
        try:
            has_script, reason = _recompile_against_itself(rvt, path)
        except RuntimeError:
            continue  # not a loadable game variant (e.g. a campaign file) -- not this test's business
        if not has_script:
            continue
        total += 1
        if reason is not None:
            failures[path.name] = reason
    assert total, "the corpus folders held no multiplayer game variants"
    coverage = 1 - len(failures) / total
    print(f"\ncorpus coverage: {total - len(failures)}/{total} ({coverage:.1%})")
    for name, reason in sorted(failures.items()):
        print(f"  unsupported: {name}: {reason[:140]}")
    assert coverage >= _MIN_CORPUS_COVERAGE
