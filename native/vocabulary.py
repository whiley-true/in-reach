"""Writes ``src/in_reach/app/rvt/megalo_ast/vocabulary.json`` -- the words ReachVariantTool's Megalo syntax has -- from the
vendored engine's own C++ (``native/engine``): every action and condition function (its name, what it is called on --
``game.``, an object, a player, a team, a timer, a number, or nothing -- its arguments in script order, and its
description), the properties of each variable type, and the members of the ``game`` namespace and of the unnamed one
(``current_player``, ``no_object``, ...).

Nothing here runs the engine: the names are read from the source text, so the data can be packaged without the native
module and read by anything (the IDE's autocomplete). Run it again after updating ``native/engine``::

    python native/vocabulary.py

``tests/app/rvt/test_megalo_vocabulary.py`` fails if the packaged file no longer matches what this would write.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "native" / "engine" / "ReachVariantTool" / "game_variants" / "components" / "megalo"
OUTPUT = ROOT / "src" / "in_reach" / "app" / "rvt" / "megalo_ast" / "vocabulary.json"

#: OpcodeArgValue<X> -> the script type a value of it is, for the ones a function or property can be a member of.
_TYPES = {
    "Object": "object",
    "Player": "player",
    "Team": "team",
    "Timer": "timer",
    "Scalar": "number",
    "PlayerOrGroup": "player",
    "ObjectPlayerVariable": "object",
}
_VARIABLE_FILES = ("object", "player", "team", "timer", "number")

_STRING = r'"(?:[^"\\]|\\.)*"'
_STRINGS = re.compile(rf"(?:{_STRING}\s*)+")
_ARG = re.compile(r'OpcodeArgBase\(\s*"([^"]*)"\s*,\s*OpcodeArgValue(\w+)::typeinfo(\s*,\s*true)?')
_PROPERTY = re.compile(r'Script::Property\(\s*"([^"]+)"\s*,\s*OpcodeArgValue(\w+)::typeinfo')
_MEMBER = re.compile(r'NamespaceMember::make_\w+_member\(\s*"([^"]+)"\s*,\s*OpcodeArgValue(\w+)::typeinfo')
_NAMESPACE = re.compile(r'Namespace\s+\w+\s*=\s*Namespace\(\s*"([^"]*)"')


def _type(value: str) -> str:
    """An ``OpcodeArgValue<X>`` suffix as a script type name."""
    return _TYPES.get(value, value[0].lower() + value[1:])


def _unquote(literals: str) -> str:
    """Adjacent C string literals, joined and unescaped (enough for the engine's descriptions)."""
    parts = re.findall(_STRING, literals)
    text = "".join(part[1:-1] for part in parts)
    return text.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")


def _blocks(text: str, opener: str) -> list[str]:
    """The text of every ``opener( ... )`` call, parentheses balanced (strings skipped)."""
    blocks = []
    start = text.find(opener + "(")
    while start != -1:
        index = start + len(opener) + 1
        depth = 1
        while depth and index < len(text):
            char = text[index]
            if char == '"':
                index += 1
                while text[index] != '"':
                    index += 2 if text[index] == "\\" else 1
            elif char == "/" and text.startswith("//", index):
                index = text.index("\n", index)
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            index += 1
        blocks.append(text[start + len(opener) + 1 : index - 1])
        start = text.find(opener + "(", index)
    return blocks


def _split_args(text: str) -> list[str]:
    """``text``'s top-level comma-separated parts (braces and parentheses nested)."""
    parts, depth, current = [], 0, ""
    for char in text:
        if char in "({":
            depth += 1
        elif char in ")}":
            depth -= 1
        if char == "," and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += char
    if current.strip():
        parts.append(current.strip())
    return parts


def _opcodes(kind: str, text: str, opener: str) -> tuple[list[dict], list[tuple[str, str, str]]]:
    """Every function one of ``text``'s opcodes maps to, and every property a getter/setter gives a type."""
    functions: list[dict] = []
    properties: list[tuple[str, str, str]] = []
    for block in _blocks(text, opener):
        literals = _STRINGS.findall(block.split("{", 1)[0])
        if len(literals) < 2:
            continue
        description = _unquote(literals[1])
        args = [(name, _type(value), bool(out)) for name, value, out in _ARG.findall(block)]
        mapping_at = block.find("OpcodeFuncToScriptMapping::make_")
        if mapping_at == -1:
            continue
        maker = re.match(r"OpcodeFuncToScriptMapping::make_(\w+)\(", block[mapping_at:]).group(1)
        parts = _split_args(_blocks(block[mapping_at:], f"OpcodeFuncToScriptMapping::make_{maker}")[0])
        if maker in ("function", "doubly_contextual_call"):
            name = parts[0].strip('"')
            secondary = parts[1].strip('"')
            order = [int(i) for i in re.findall(r"-?\d+", parts[2])]
            rest = parts[3:] if maker == "function" else parts[4:]
            context_part = rest[0] if rest else "no_context"
            flags = rest[1] if len(rest) > 1 else ""
            if "game_namespace" in context_part:
                context = "game"
            elif re.fullmatch(r"-?\d+", context_part.strip()) and int(context_part) >= 0:
                context = args[int(context_part)][1]
            else:
                context = None
            used = set(order) | ({int(context_part)} if context not in (None, "game") else set())
            returns = next((a[1] for i, a in enumerate(args) if a[2] and i not in used), None)
            entry = {
                "name": name,
                "kind": kind,
                "context": context,
                "args": [args[i][0] for i in order if 0 <= i < len(args)],
                "returns": returns,
                "description": description,
            }
            functions.append(entry)
            if secondary and "secondary_name_is_deprecated" not in flags:
                functions.append({**entry, "name": secondary})
        elif maker in ("getter", "setter"):
            name = parts[0].strip('"')
            if name and parts[1].strip().isdigit():
                properties.append((args[int(parts[1])][1], name, "number"))
    return functions, properties


def generate(engine: Path = ENGINE) -> dict:
    """The vocabulary, read from ``engine`` (the megalo component folder of the vendored engine)."""
    functions: list[dict] = []
    properties: dict[str, dict[str, str]] = {}
    for kind, file, opener in (("action", "actions.cpp", "ActionFunction"), ("condition", "conditions.cpp", "ConditionFunction")):
        found, props = _opcodes(kind, (engine / file).read_text(encoding="utf-8", errors="replace"), opener)
        functions += found
        for owner, name, value in props:
            properties.setdefault(owner, {}).setdefault(name, value)
    for file in _VARIABLE_FILES:
        text = (engine / "opcode_arg_types" / "variables" / f"{file}.cpp").read_text(encoding="utf-8", errors="replace")
        for name, value in _PROPERTY.findall(text):
            properties.setdefault(file, {})[name] = _type(value)
    namespaces: dict[str, dict[str, str]] = {}
    text = (engine / "compiler" / "namespaces.cpp").read_text(encoding="utf-8", errors="replace")
    marks = [(m.start(), m.group(1)) for m in _NAMESPACE.finditer(text)] + [(len(text), None)]
    for (start, name), (end, _next) in zip(marks, marks[1:]):
        if name in ("", "game"):
            members = namespaces.setdefault(name, {})
            for member, value in _MEMBER.findall(text[start:end]):
                members.setdefault(member, _type(value))
    unique: dict[tuple, dict] = {}
    for entry in functions:
        unique.setdefault((entry["context"], entry["name"], entry["kind"]), entry)
    return {
        "source": "native/engine (ReachVariantTool), read by native/vocabulary.py",
        "functions": sorted(unique.values(), key=lambda e: (str(e["context"]), e["name"], e["kind"])),
        "properties": {owner: dict(sorted(props.items())) for owner, props in sorted(properties.items())},
        "namespaces": {name: dict(sorted(members.items())) for name, members in sorted(namespaces.items())},
    }


def render(vocabulary: dict) -> str:
    return json.dumps(vocabulary, indent=1, ensure_ascii=False) + "\n"


def main() -> int:
    OUTPUT.write_text(render(generate()), encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
