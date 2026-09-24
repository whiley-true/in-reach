"""The words ReachVariantTool's Megalo syntax has, as data: ``vocabulary.json`` beside this module, written from the vendored
engine's own C++ by ``native/vocabulary.py`` (never by hand) -- every action and condition function, the properties of
each variable type, and the members of the ``game`` namespace and the unnamed one. Reading it never loads the native
module."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

VOCABULARY_FILE = Path(__file__).with_name("vocabulary.json")
#: The variable types, each of which is also a slot family (``global.number[0]``, ``current_player.object[1]``).
VARIABLE_TYPES = ("number", "object", "player", "team", "timer")


@dataclass(frozen=True)
class Function:
    name: str
    kind: str  # "action" | "condition"
    #: What it is called on: ``"game"`` (``game.end_round()``), a variable type (``current_object.delete()``), another
    #: argument type, or ``None`` (a bare call).
    context: str | None
    args: tuple[str, ...]
    returns: str | None
    description: str

    @property
    def signature(self) -> str:
        call = f"{self.name}({', '.join(self.args)})"
        return f"{call} -> {self.returns}" if self.returns else call


@dataclass(frozen=True)
class Vocabulary:
    functions: tuple[Function, ...]
    #: type -> property name -> the property's type (``player`` -> ``biped`` -> ``object``).
    properties: dict[str, dict[str, str]] = field(default_factory=dict)
    #: namespace (``""`` is the unnamed one) -> member -> its type.
    namespaces: dict[str, dict[str, str]] = field(default_factory=dict)

    def functions_on(self, context: str | None) -> list[Function]:
        return [f for f in self.functions if f.context == context]


@lru_cache(maxsize=1)
def load() -> Vocabulary:
    """The packaged vocabulary (read once)."""
    data = json.loads(VOCABULARY_FILE.read_text(encoding="utf-8"))
    functions = tuple(
        Function(f["name"], f["kind"], f["context"], tuple(f["args"]), f["returns"], f["description"]) for f in data["functions"]
    )
    return Vocabulary(functions, data["properties"], data["namespaces"])
