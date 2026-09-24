"""What to offer as a Megalo script is typed: :func:`complete` takes the line up to the cursor and returns the words that
could come next, from ReachVariantTool's own vocabulary (:mod:`in_reach.app.rvt.megalo_ast.vocabulary` -- functions,
properties, the ``game`` and unnamed namespace members), the language's keywords, the annotations, and the script's own
names (declared storage names and ``alias`` lines, plus any other word already in the file).

After ``alias NAME =`` it offers only what an alias can stand for: a slot (``global.``, or ``player.``/``object.``/
``team.`` -- the looped-over one's own -- then ``number[`` and the other slot families), an indexed table (``team[``,
``script_option[``, ``script_traits[``, ``script_widget[``, ``script_stat[``), a member of the unnamed namespace
(``current_player``, ``no_object``), or another of the script's names -- never a keyword or a function (a number, the
other thing an alias can be, is just typed).

After a ``.`` it offers what the thing before the dot has: ``game.`` its members and functions, ``current_player.`` a
player's functions, properties and slots, ``global.`` the slot families. The type is worked out from the text alone --
the unnamed namespace (``current_object`` is an object), slots (``global.player[0]``), properties (``.biped`` is an
object) and a declared name or alias's slot. Anything it can't place gets every member of every type.

Framework-free: the IDE's editor asks it on each keystroke and draws the list itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping

from in_reach.app.rvt.megalo_ast.annotations import ANNOTATION_NAMES
from in_reach.app.rvt.megalo_ast.vocabulary import VARIABLE_TYPES, Vocabulary, load

KEYWORDS = (
    "if", "then", "altif", "alt", "do", "end", "for", "each", "player", "object", "team", "on", "function", "alias",
    "declare", "and", "or", "not", "inline", "with", "network", "priority", "local", "low", "high", "label", "randomly",
)
#: The namespaces a bare word can start with, beside the unnamed one's members.
NAMESPACES = ("global", "game", "temporaries", "enums")
#: A single file's annotations: documentation. Everything else is a script project's.
SINGLE_FILE_ANNOTATIONS = ("doc", "tags", "see")
ENV_DIRECTIVES = ("if", "else", "end")

_IDENT_TAIL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")
_CHAIN_TAIL = re.compile(r"((?:[A-Za-z_][A-Za-z0-9_]*(?:\[[^\[\]]*\])?\.)+)$")
_ANNOTATION_TAIL = re.compile(r"--\s*@([A-Za-z_-]*)$")
_SEGMENT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)(\[[^\[\]]*\])?")
_ALIAS = re.compile(r"^\s*alias\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([A-Za-z_][A-Za-z0-9_.\[\]]*|-?\d+%?)", re.MULTILINE)
_WORDS = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_ALIAS_TARGET = re.compile(r"^\s*alias\s+[A-Za-z_][A-Za-z0-9_]*\s*=\s*(?P<target>.*)$")
#: What starts an alias's slot: a namespace, or the looped-over player/object/team's own.
ALIAS_SCOPES = ("global", "temporaries", "player", "object", "team")
#: The tables an alias can index straight into.
ALIAS_TABLES = ("team", "script_option", "script_traits", "script_widget", "script_stat")
_ORDER = {"name": 0, "property": 1, "function": 2, "variable": 3, "member": 4, "keyword": 5, "namespace": 6,
          "annotation": 7, "word": 8}


@dataclass(frozen=True)
class Completion:
    #: What replaces the word being typed.
    text: str
    #: ``function`` | ``property`` | ``variable`` (a slot family, ``number[``) | ``member`` (a namespace member) |
    #: ``keyword`` | ``namespace`` | ``annotation`` | ``name`` (the script's own) | ``word`` (elsewhere in the file).
    kind: str
    #: One line beside it: a signature, a type, a slot.
    detail: str = ""
    #: The longer help (a function's description), for a tooltip.
    description: str = ""


def script_names(text: str, declared: Mapping[str, str] | None = None) -> dict[str, str]:
    """Name -> what it stands for: ``declared`` (a storage name -> its slot, as the documentation lists them) and every
    ``alias NAME = target`` line in ``text``."""
    names = dict(declared or {})
    for name, target in _ALIAS.findall(text):
        names.setdefault(name, target)
    return names


def _in_string_or_comment(line: str) -> str | None:
    """``"string"`` or ``"comment"`` if ``line``'s end is inside one, else ``None``."""
    in_string = False
    index = 0
    while index < len(line):
        char = line[index]
        if in_string:
            if char == "\\":
                index += 1
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif line.startswith("--", index):
            return "comment"
        index += 1
    return "string" if in_string else None


def type_of(chain: str, names: Mapping[str, str] | None = None, vocabulary: Vocabulary | None = None, _depth: int = 0) -> str | None:
    """The type of ``chain`` (``current_player.biped``, ``global.object[2]``), or ``"game"``/``"global"``/
    ``"temporaries"`` for a namespace; ``None`` if the text can't say."""
    vocabulary = vocabulary or load()
    names = names or {}
    segments = _SEGMENT.findall(chain)
    if not segments or _depth > 4:
        return None
    first = segments[0][0]
    if first in ("global", "temporaries", "game"):
        current: str | None = first
    elif first in vocabulary.namespaces.get("", {}):
        current = vocabulary.namespaces[""][first]
    elif first in names:
        current = type_of(names[first], names, vocabulary, _depth + 1)
    else:
        return None
    for name, index in segments[1:]:
        if current in ("global", "temporaries") or (current in ("object", "player", "team") and index):
            current = name if name in VARIABLE_TYPES else None
        elif current == "game":
            current = vocabulary.namespaces.get("game", {}).get(name)
        elif current is not None:
            current = vocabulary.properties.get(current, {}).get(name)
        if current is None:
            return None
    return current


def _members(of: str | None, vocabulary: Vocabulary) -> list[Completion]:
    out: list[Completion] = []
    if of in ("global", "temporaries"):
        return [Completion(f"{t}[", "variable", f"{of}.{t}[N]") for t in VARIABLE_TYPES]
    if of == "game":
        out += [Completion(name, "member", type_) for name, type_ in vocabulary.namespaces.get("game", {}).items()]
        out += [Completion(f.name, "function", f.signature, f.description) for f in vocabulary.functions_on("game")]
        return out
    types = [of] if of is not None else sorted({f.context for f in vocabulary.functions if f.context not in (None, "game")})
    for type_ in types:
        out += [Completion(name, "property", value) for name, value in vocabulary.properties.get(type_, {}).items()]
        out += [Completion(f.name, "function", f"{type_}.{f.signature}", f.description) for f in vocabulary.functions_on(type_)]
        if type_ in ("object", "player", "team"):
            out += [Completion(f"{t}[", "variable", f"{type_}.{t}[N]") for t in VARIABLE_TYPES]
    return out


def _bare(names: Mapping[str, str], words: Iterable[str], vocabulary: Vocabulary) -> list[Completion]:
    out = [Completion(name, "name", target) for name, target in names.items()]
    out += [Completion(word, "keyword") for word in KEYWORDS]
    out += [Completion(name, "namespace") for name in NAMESPACES]
    out += [Completion(name, "member", type_) for name, type_ in vocabulary.namespaces.get("", {}).items()]
    out += [Completion(f.name, "function", f.signature, f.description) for f in vocabulary.functions_on(None)]
    out += [Completion(word, "word") for word in words]
    return out


def _alias_targets(target: str, names: Mapping[str, str], vocabulary: Vocabulary) -> list[Completion] | None:
    """What can come next in an alias's target, ``target`` being what is typed of it so far before the current word --
    ``None`` when ``target`` isn't somewhere a name goes (a number, inside brackets)."""
    if not target:
        out = [Completion(f"{scope}.", "namespace", "a slot: " + (f"{scope}.number[N]" if scope != "temporaries" else "temporaries.number[N]"))
               for scope in ALIAS_SCOPES]
        out += [Completion(f"{table}[", "variable", f"{table}[N]") for table in ALIAS_TABLES]
        members = vocabulary.namespaces.get("", {}).items()
        out += [Completion(name, "member", type_) for name, type_ in members if name not in ALIAS_TABLES]
        out += [Completion(name, "name", value) for name, value in names.items()]
        return out
    chain = _CHAIN_TAIL.search(target)
    if chain is None or chain.end() != len(target) or chain.start() != 0:
        return None
    base = chain.group(1)[:-1]
    if base in ALIAS_SCOPES:
        return [Completion(f"{t}[", "variable", f"{base}.{t}[N]") for t in VARIABLE_TYPES]
    of = type_of(base, names, vocabulary)
    if of is None:
        return []
    out = [Completion(name, "property", value) for name, value in vocabulary.properties.get(of, {}).items()]
    if of in ("object", "player", "team"):
        out += [Completion(f"{t}[", "variable", f"{of}.{t}[N]") for t in VARIABLE_TYPES]
    return out


def complete(
    line: str,
    *,
    text: str = "",
    declared: Mapping[str, str] | None = None,
    single_file: bool = True,
    vocabulary: Vocabulary | None = None,
) -> tuple[int, list[Completion]]:
    """What could finish the word at the end of ``line`` (the current line up to the cursor): ``(start, completions)``,
    ``start`` being the column the word being typed begins at (what a chosen completion replaces). ``text`` is the whole
    file (its aliases and words are offered), ``declared`` the storage names the documentation lists (name -> slot).
    In a string nothing is offered; in a comment only an annotation name after ``-- @`` (a single file's own, unless
    ``single_file`` is false)."""
    vocabulary = vocabulary or load()
    where = _in_string_or_comment(line)
    if where == "string":
        return len(line), []
    if where == "comment":
        match = _ANNOTATION_TAIL.search(line)
        if match is None:
            return len(line), []
        names = SINGLE_FILE_ANNOTATIONS if single_file else ANNOTATION_NAMES
        prefix = match.group(1)
        found = [Completion(n, "annotation") for n in (*names, *ENV_DIRECTIVES) if n.startswith(prefix.lower())]
        return match.start(1), _ranked(found, prefix)
    word = _IDENT_TAIL.search(line)
    prefix = word.group() if word else ""
    start = len(line) - len(prefix)
    before = line[:start]
    names = script_names(text, declared)
    alias = _ALIAS_TARGET.match(before)
    chain = _CHAIN_TAIL.search(before)
    if alias is not None:
        candidates = _alias_targets(alias.group("target").strip(), names, vocabulary)
        if candidates is None:
            return start, []
    elif chain is not None:
        candidates = _members(type_of(chain.group(1)[:-1], names, vocabulary), vocabulary)
    elif before.endswith(".") or not prefix:
        return start, []  # a number's decimal point, or nothing typed yet: nothing to finish
    else:
        own = set(names) | set(KEYWORDS) | set(NAMESPACES)
        words = sorted({w for w in _WORDS.findall(text) if w not in own and w != prefix})
        candidates = _bare(names, words, vocabulary)
    lowered = prefix.lower()
    found = [c for c in candidates if c.text.lower().startswith(lowered) and c.text != prefix]
    return start, _ranked(found, prefix)


def _ranked(found: list[Completion], prefix: str) -> list[Completion]:
    unique: dict[str, Completion] = {}
    for completion in sorted(found, key=lambda c: (not c.text.startswith(prefix), _ORDER.get(c.kind, 9), c.text)):
        unique.setdefault(completion.text, completion)
    return list(unique.values())
