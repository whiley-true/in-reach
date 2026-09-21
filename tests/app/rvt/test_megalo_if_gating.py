"""What an ``if`` gates, in what :mod:`in_reach.app.rvt.megalo_compiler` builds.

In a Megalo trigger a condition gates *every* opcode after it in the same code block, not just an
``if`` body -- there is no way to gate a span and then resume unconditionally. So an ``if`` with
something after it needs its own "Run Inline Nested Trigger" wrapper *containing the condition*, which
is how native compiles it (``inline: if A then ... end``). The compiler used to put the condition in the
enclosing block and only the body in the wrapper, so the condition also gated everything that followed:
``if A then X end`` then ``Z`` built a script where ``Z`` only ran when ``A`` held. Its decompiled text
showed exactly that (``Z`` nested inside the ``if``); the existing test only checked that both lines
appeared.

Each test compiles a script, saves and reloads it, and checks the *decompiled* structure -- the
engine's own reading of what each condition gates.
"""
import tempfile
from pathlib import Path

import pytest

from in_reach.app.rvt import megalo_compiler, rvt_bridge
from in_reach.app.rvt.decompile import normalize_script_text
from in_reach.app.rvt.megalo_ast import parse, walk

_JUGGERNAUT_BIN = Path(__file__).parent / "resources" / "juggernaut" / "juggernaut.bin"

pytestmark = [
    pytest.mark.skipif(
        not rvt_bridge.is_available(), reason="native _reachvarianttool extension not available on this platform"
    ),
    pytest.mark.skipif(not _JUGGERNAUT_BIN.is_file(), reason="juggernaut fixture .bin not present"),
]


@pytest.fixture(scope="module")
def rvt():
    return rvt_bridge.get_rvt()


def _built(rvt, source: str):
    """``source`` compiled in-house onto juggernaut, saved, reloaded, and its decompiled text parsed."""
    variant = rvt.load(str(_JUGGERNAUT_BIN))
    megalo_compiler.compile_script(rvt, variant, source)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "out.bin"
        variant.save(str(path))
        text = normalize_script_text(rvt.load(str(path)).decompile_script())
    return parse(text)


def _flattened(stmts) -> list:
    """``stmts`` with every plain ``do`` block replaced by its own contents: a ``do`` gates nothing, and
    the decompiler shows a top-level trigger that starts with an inline block as one."""
    flat = []
    for stmt in stmts:
        if stmt.kind == "do" and not stmt.inline:
            flat.extend(_flattened(stmt.body))
        elif stmt.kind != "declare":
            flat.append(stmt)
    return flat


def _statements(script) -> list:
    return _flattened(script.body)


def _shape(stmts) -> list[str]:
    """One word per statement, looking through plain ``do`` blocks: ``if`` for an ``if`` (whatever its
    body), else its kind."""
    return [stmt.kind for stmt in _flattened(stmts)]


def test_a_statement_after_an_if_is_not_gated_by_it(rvt) -> None:
    script = _built(rvt, "if global.number[0] == 1 then\n   global.number[1] = 2\nend\nglobal.number[2] = 3\n")

    top = _statements(script)

    assert _shape(top) == ["if", "assign"]
    assert len(top[0].body) == 1  # the body is still just its own statement
    assert top[1].target.index.value == 2  # ... and the trailing one really is global.number[2]


def test_sibling_ifs_do_not_gate_each_other(rvt) -> None:
    source = (
        "if global.number[0] == 1 then\n   global.number[1] = 1\nend\n"
        "if global.number[0] == 2 then\n   global.number[1] = 2\nend\n"
        "global.number[2] = 3\n"
    )

    assert _shape(_statements(_built(rvt, source))) == ["if", "if", "assign"]


def test_a_statement_between_two_ifs_is_ungated(rvt) -> None:
    source = (
        "if global.number[0] == 1 then\n   global.number[1] = 1\nend\n"
        "global.number[2] = 5\n"
        "if global.number[0] == 2 then\n   global.number[1] = 2\nend\n"
    )

    assert _shape(_statements(_built(rvt, source))) == ["if", "assign", "if"]


def test_every_branch_of_an_alt_chain_stays_reachable(rvt) -> None:
    """``alt``/``altif`` branches are compiled as separate ``if``s whose conditions name the earlier
    branches' negations -- so an earlier branch's condition gating a later one would make that later
    branch impossible to run."""
    source = (
        "if global.number[0] == 1 then\n   global.number[1] = 1\n"
        "altif global.number[0] == 2 then\n   global.number[1] = 2\n"
        "alt\n   global.number[1] = 3\nend\n"
        "global.number[2] = 9\n"
    )

    top = _statements(_built(rvt, source))

    assert _shape(top) == ["if", "if", "if", "assign"]


def test_the_trailing_statement_inside_a_loop_is_ungated_too(rvt) -> None:
    source = (
        "for each player do\n"
        "   if current_player.number[0] == 1 then\n      current_player.number[1] += 1\n   end\n"
        "   current_player.number[0] = 2\n"
        "end\n"
    )

    loop = _statements(_built(rvt, source))[0]

    assert loop.kind == "for_each"
    assert _shape(loop.body) == ["if", "assign"]


def test_an_if_nested_in_an_if_still_nests(rvt) -> None:
    """The fix must not flatten real nesting: a statement *inside* the outer ``if`` stays gated by it."""
    source = (
        "if global.number[0] == 1 then\n"
        "   if global.number[1] == 2 then\n      global.number[2] = 3\n   end\n"
        "   global.number[3] = 4\n"
        "end\n"
    )

    outer = _statements(_built(rvt, source))[0]

    assert _shape([outer]) == ["if"]
    assert _shape(outer.body) == ["if", "assign"]


def test_a_trailing_if_still_needs_no_wrapper(rvt) -> None:
    """Nothing follows it, so there is nothing to protect: still built directly, as before."""
    text = _built(rvt, "if global.number[0] == 1 then\n   game.end_round()\nend\n")

    assert not [node for node in walk(text) if getattr(node, "inline", False)]


# -- round trip -----------------------------------------------------------------------------------------
# Decompiling a script this compiler built prints `inline: if ...` / `inline: do ...`, which the parser
# used to reject -- so the text couldn't be compiled again in-house (it fell back to native).

_ROUND_TRIP_SCRIPTS = {
    "an if with something after it": "if global.number[0] == 1 then\n   global.number[1] = 2\nend\nglobal.number[2] = 3\n",
    "an alt chain": (
        "if global.number[0] == 1 then\n   global.number[1] = 1\n"
        "altif global.number[0] == 2 then\n   global.number[1] = 2\n"
        "alt\n   global.number[1] = 3\nend\nglobal.number[2] = 9\n"
    ),
    "a loop": (
        "for each player do\n"
        "   if current_player.number[0] == 1 then\n      current_player.number[1] += 1\n   end\n"
        "   current_player.number[0] = 2\n"
        "end\n"
    ),
    "nested ifs": (
        "if global.number[0] == 1 then\n"
        "   if global.number[1] == 2 then\n      global.number[2] = 3\n   end\n"
        "   global.number[3] = 4\n"
        "end\n"
    ),
}


def _decompiled(rvt, variant) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "out.bin"
        variant.save(str(path))
        return normalize_script_text(rvt.load(str(path)).decompile_script())


@pytest.mark.parametrize("source", _ROUND_TRIP_SCRIPTS.values(), ids=_ROUND_TRIP_SCRIPTS.keys())
def test_a_scripts_own_decompiled_text_recompiles_in_house_to_the_same_thing(rvt, source: str) -> None:
    first = rvt.load(str(_JUGGERNAUT_BIN))
    megalo_compiler.compile_script(rvt, first, source)
    text = _decompiled(rvt, first)
    assert "inline:" in text or "for each" in text, "the script should have produced an inline block"

    again = rvt.load(str(_JUGGERNAUT_BIN))
    megalo_compiler.compile_script(rvt, again, text)  # raises UnsupportedConstruct if it can't be built in-house

    assert _decompiled(rvt, again) == text
