"""The native compiler's last ``if`` in an inline block (``native/`` -- ``Block::compile`` in compiler.cpp).

The last ``if`` in a block writes its conditions into the block's own code, costing nothing. An inline block
has no trigger to share, so native used to give that ``if`` a trigger of its own plus a "Run Nested Trigger"
to reach it: one action more for every such block. Recompiling RCC Onslaught v14's own decompiled script
came to 1055 actions (the variant itself holds 1016), and native refused it -- over 1024 -- every time a
build fell back to it.
"""
import tempfile
from pathlib import Path

import pytest

from in_reach.app.blank_variant import resolve_blank_variant
from in_reach.app.rvt import rvt_bridge
from in_reach.app.rvt.decompile import normalize_script_text

pytestmark = pytest.mark.skipif(
    not rvt_bridge.is_available(), reason="native _reachvarianttool extension not available on this platform"
)

_SOURCE = (
    "for each player do\n"
    "   inline: if current_player.number[0] == 1 then\n"
    "      current_player.number[1] = 2\n"
    "      if current_player.number[2] == 3 then\n"
    "         current_player.number[3] = 4\n"
    "      end\n"
    "   end\n"
    "   current_player.number[4] = 5\n"
    "end\n"
)


@pytest.fixture(scope="module")
def rvt():
    return rvt_bridge.get_rvt()


@pytest.fixture
def compiled(rvt):
    variant = rvt.load(str(resolve_blank_variant(firefight=False)))
    result = variant.multiplayer.compile_script(_SOURCE)
    assert result.success, [m.text for m in list(result.fatal_errors) + list(result.errors)]
    return variant


def test_the_last_if_in_an_inline_block_costs_no_trigger_or_call(compiled) -> None:
    counts = compiled.multiplayer.get_full_size_data().counts
    assert counts["triggers"] == 1
    assert counts["actions"] == 4  # the inline wrapper and the three assignments


def test_it_still_gates_only_what_it_did(rvt, compiled) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "out.bin"
        compiled.save(str(path))
        text = normalize_script_text(rvt.load(str(path)).decompile_script())
    lines = [line.rstrip() for line in text.replace("\r", "").strip().split("\n")]
    start = lines.index("for each player do")  # after the implied declares
    assert lines[start:] == _SOURCE.strip().split("\n")
