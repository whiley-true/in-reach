"""The packaged Megalo vocabulary: written from the vendored engine's C++ by ``native/vocabulary.py``, and kept in step
with it."""
import importlib.util
from pathlib import Path

import pytest

from in_reach.app.rvt.megalo_ast import vocabulary

_ROOT = Path(__file__).resolve().parents[3]
_GENERATOR = _ROOT / "native" / "vocabulary.py"


def _generator():
    spec = importlib.util.spec_from_file_location("native_vocabulary", _GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not (_ROOT / "native" / "engine").is_dir(), reason="no vendored engine in this checkout")
def test_the_packaged_vocabulary_is_what_the_engine_source_says() -> None:
    generator = _generator()

    assert generator.render(generator.generate()) == vocabulary.VOCABULARY_FILE.read_text(encoding="utf-8"), (
        "vocabulary.json is out of date -- run: python native/vocabulary.py"
    )


def test_it_knows_game_functions_member_functions_and_their_arguments() -> None:
    words = vocabulary.load()
    by_name = {(f.context, f.name): f for f in words.functions}

    assert ("game", "end_round") in by_name
    place = by_name[("object", "place_at_me")]
    assert place.args == ("type", "label", "flags", "offset", "name") and place.returns == "object"
    assert place.signature == "place_at_me(type, label, flags, offset, name) -> object"
    assert by_name[("object", "is_of_type")].kind == "condition"
    assert ("object", "create_object") in by_name  # a live second name
    assert ("object", "try_get_carrier") not in by_name  # a deprecated one isn't offered


def test_it_knows_properties_and_namespace_members() -> None:
    words = vocabulary.load()

    assert words.properties["player"]["biped"] == "object"
    assert words.properties["object"]["shields"] == "number"  # from a getter/setter opcode
    assert words.namespaces[""]["current_player"] == "player"
    assert words.namespaces["game"]["round_timer"] == "timer"
