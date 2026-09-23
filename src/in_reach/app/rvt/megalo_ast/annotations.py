"""``-- @name ...`` annotation comments: the syntax module authors use to say what a script needs, and
how its pieces fit together, in a form a linker and a budget panel can read.

Annotations are ordinary Megalo comments, so a script that uses them still compiles unchanged anywhere; this
module is the second, small parser that reads them (``TO_IMPLEMENT`` §4). It works line by line on the raw
text rather than on :attr:`Script.comments`, so annotations are read even when the rest of the script has a
syntax error, and it only *parses*: whether a name is declared twice, whether the pools have room, which slot
something lands in are the linter's and linker's questions, not this module's.

Shape of a line
---------------

::

    -- @name  arg  arg  key=value  {inline, braces}  "quoted text"  -- a note

An annotation is a comment that *starts its line* (after indentation) with ``@`` -- ``x = 1 -- @doc`` is an
ordinary comment. Arguments are separated by whitespace; a ``"quoted string"`` or a ``{braced group}`` is one
argument even with spaces inside. A second ``--`` starts a free-text **note** for the reader, kept on the
annotation and otherwise ignored. (``TO_IMPLEMENT`` §4's examples put such prose straight after the arguments;
here it needs the ``--``.) ``@if`` / ``@else`` / ``@end`` are not annotations -- they are env
directives (:mod:`in_reach.app.script_preprocess`) and are skipped.

What each one means
-------------------

Storage -- a name the linker will give a slot (``declare`` + ``alias``):

- ``@number|@object|@player|@team|@timer NAME`` -- global storage.
- ``@pnumber|@pobject|@pplayer|@pteam|@ptimer NAME`` -- per-player storage (``player.number[N]`` ...).
- ``@onumber|@oobject|@oplayer|@oteam|@otimer KIND.NAME`` -- per-object storage, for a *kind* of object.
- ``@tnumber|@tobject|@tplayer|@tteam|@ttimer TEAM.NAME`` -- per-team storage.

  Options: ``priority=local|low|high`` (not on a timer); ``default=<value>`` (not on a player or object
  variable); ``owns_default=true|false`` (object storage only: this kind's declared default may be the one the
  shared slot is declared with).
- ``@bitfield KIND.NAME { flag, flag, ... }`` -- flags packed into one object number.

Engine resources -- declared in code, allocated by the linker, written into ``settings/``:

- ``@trait NAME { field = value, ... }``, ``@option NAME { ... }``, ``@widget NAME { ... }`` -- values are
  numbers, ``"strings"``, ``true``/``false`` or bare words. Which fields exist is the catalog's business.
- ``@label NAME = "text"``.

Fragments -- a loop body that the linker may merge with its neighbours (``TO_IMPLEMENT`` §4.6, §7):

- ``@block NAME`` (top of a block file), ``@fragment BLOCK.NAME``, ``@loop player|object|team``, ``@gate <condition>``, ``@guard <condition>``,
  ``@traits layer=NAME``, ``@fusion auto|never|subroutine|force:GROUP``.
- ``@preamble NAME`` names a shared prologue -- to require it (in a fragment's header) or to define it (above
  its code); ``@provides name:type ...`` lists what it leaves behind and ``@guard-end`` marks where fragments
  are inserted. ``subroutine`` asks for the shared logic to be a called subroutine rather than fused inline.

Documentation:

- ``@doc text ...`` (the whole rest of the line is text), ``@see TAG``, ``@assumes BLOCK``.
- ``@tags a, b`` -- what the file is about (commas or spaces between tags; the same vocabulary as ``module.toml``'s
  ``tags``).

Errors
------

:func:`parse_annotations` never raises: a malformed annotation is left out of :attr:`Annotations.items` and
reported in :attr:`Annotations.diagnostics` with its line and column (the first problem in each), so an editor
can list every problem at once. An unknown ``@name`` is one of them, with a suggestion if it's close to a real one.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from .aliases import RESERVED_NAMES
from .lexer import MegaloLexError
from .nodes import ASTNode, Expression, SourceSpan
from .parser import MegaloParseError, parse_expression

_LINE = re.compile(r"^(?P<indent>[ \t]*)--[ \t]*@(?P<name>[A-Za-z][A-Za-z0-9_-]*)(?P<rest>.*)$")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_INT = re.compile(r"-?\d+")

#: Env directives, handled by ``script_preprocess`` -- not annotations.
_DIRECTIVES = frozenset({"if", "else", "end"})
#: Words that can't be the name of something declared here, because it becomes an ``alias``.
_KEYWORDS = RESERVED_NAMES | frozenset(
    {"if", "then", "else", "elseif", "alt", "altif", "end", "do", "for", "each", "on", "declare", "alias",
     "and", "or", "not", "function", "enum", "inline", "with", "label", "randomly"}
)

_TYPES = ("number", "object", "player", "team", "timer")
_SCOPE_PREFIXES = {"": "global", "p": "player", "o": "object", "t": "team"}
#: ``pnumber`` -> ``("player", "number")`` and so on, for all twenty.
_STORAGE_NAMES = {f"{prefix}{type_}": (scope, type_) for prefix, scope in _SCOPE_PREFIXES.items() for type_ in _TYPES}
_PRIORITIES = ("local", "low", "high")
_LOOP_SELECTORS = ("player", "object", "team")
_FUSION_MODES = ("auto", "never", "subroutine")

FieldValue = Union[bool, int, str]


# -- results ----------------------------------------------------------------------------------------------


class _Annotation(ASTNode):
    note: str | None = None  # the free text after a second `--`, if any


class StorageAnnotation(_Annotation):
    """``@pnumber p_hud_count priority=high`` and its nineteen siblings. ``owner`` is the kind (object storage)
    or team (team storage) before the dot in ``KIND.NAME``, ``None`` for global and player storage."""

    kind: Literal["storage"] = "storage"
    scope: Literal["global", "player", "object", "team"]
    type: Literal["number", "object", "player", "team", "timer"]
    name: str
    owner: str | None = None
    priority: Literal["local", "low", "high"] | None = None
    default: Expression | None = None
    owns_default: bool = False


class BitfieldAnnotation(_Annotation):
    kind: Literal["bitfield"] = "bitfield"
    owner: str
    name: str
    flags: list[str]


class _ResourceAnnotation(_Annotation):
    name: str
    fields: dict[str, FieldValue] = Field(default_factory=dict)


class TraitAnnotation(_ResourceAnnotation):
    kind: Literal["trait"] = "trait"


class OptionAnnotation(_ResourceAnnotation):
    kind: Literal["option"] = "option"


class WidgetAnnotation(_ResourceAnnotation):
    kind: Literal["widget"] = "widget"


class LabelAnnotation(_Annotation):
    kind: Literal["label"] = "label"
    name: str
    text: str


class BlockAnnotation(_Annotation):
    """``@block SETUP`` at the top of a block file: which block it is. Optional -- a block file's name is its
    file stem upper-cased -- but if given it must agree (the loader checks)."""

    kind: Literal["block"] = "block"
    name: str


class FragmentAnnotation(_Annotation):
    kind: Literal["fragment"] = "fragment"
    block: str
    name: str


class LoopAnnotation(_Annotation):
    kind: Literal["loop"] = "loop"
    selector: Literal["player", "object", "team"]


class GateAnnotation(_Annotation):
    kind: Literal["gate"] = "gate"
    condition: Expression


class GuardAnnotation(_Annotation):
    kind: Literal["guard"] = "guard"
    condition: Expression


class GuardEndAnnotation(_Annotation):
    kind: Literal["guard_end"] = "guard_end"


class PreambleAnnotation(_Annotation):
    kind: Literal["preamble"] = "preamble"
    name: str


class ProvidedVariable(BaseModel):
    name: str
    type: Literal["number", "object", "player", "team", "timer"]


class ProvidesAnnotation(_Annotation):
    kind: Literal["provides"] = "provides"
    variables: list[ProvidedVariable]


class TraitsAnnotation(_Annotation):
    kind: Literal["traits"] = "traits"
    layer: str


class FusionAnnotation(_Annotation):
    kind: Literal["fusion"] = "fusion"
    mode: Literal["auto", "never", "subroutine", "force"]
    group: str | None = None  # the GROUP of `force:GROUP`


class DocAnnotation(_Annotation):
    kind: Literal["doc"] = "doc"
    text: str


class SeeAnnotation(_Annotation):
    kind: Literal["see"] = "see"
    tag: str


class AssumesAnnotation(_Annotation):
    kind: Literal["assumes"] = "assumes"
    block: str


class TagsAnnotation(_Annotation):
    """``@tags scoring, hud`` -- what the file is about, for finding, grouping and (later) checking it."""

    kind: Literal["tags"] = "tags"
    tags: list[str]


Annotation = Annotated[
    Union[
        StorageAnnotation, BitfieldAnnotation, TraitAnnotation, OptionAnnotation, WidgetAnnotation, LabelAnnotation,
        BlockAnnotation, FragmentAnnotation, LoopAnnotation, GateAnnotation, GuardAnnotation, GuardEndAnnotation,
        PreambleAnnotation, ProvidesAnnotation, TraitsAnnotation, FusionAnnotation,
        DocAnnotation, SeeAnnotation, AssumesAnnotation, TagsAnnotation,
    ],
    Field(discriminator="kind"),
]


class AnnotationDiagnostic(ASTNode):
    """One malformed annotation. ``span`` covers the offending argument (or the whole line)."""

    message: str


class Annotations(BaseModel):
    """What :func:`parse_annotations` found: every well-formed annotation in source order, and one diagnostic
    for each malformed one."""

    items: list[Annotation] = Field(default_factory=list)
    diagnostics: list[AnnotationDiagnostic] = Field(default_factory=list)


# -- reading a line --------------------------------------------------------------------------------------


class _Problem(Exception):
    """A malformed annotation: ``message``, and where (``col``..``end``, 0-based columns in the line)."""

    def __init__(self, message: str, col: int, end: int) -> None:
        super().__init__(message)
        self.message = message
        self.col = col
        self.end = end


@dataclass(frozen=True)
class _Token:
    kind: Literal["word", "string", "braces"]
    text: str  # a string keeps its quotes, a braced group its braces
    col: int
    end: int


@dataclass
class _Line:
    number: int  # 1-based
    name: str
    name_col: int  # where the `@` is
    line_end: int
    body: str  # everything after the name, minus any note
    body_col: int
    note: str | None
    tokens: list[_Token]

    def span(self, col: int, end: int) -> SourceSpan:
        return SourceSpan(start_line=self.number, start_col=col, end_line=self.number, end_col=end)

    def problem(self, message: str, token: _Token | None = None) -> _Problem:
        if token is None:
            return _Problem(message, self.name_col, self.line_end)
        return _Problem(message, token.col, token.end)


def _scan_string(text: str, start: int) -> int:
    """The index just past the closing quote of the string opening at ``start``; raises if it never closes."""
    i = start + 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
        elif text[i] == '"':
            return i + 1
        else:
            i += 1
    raise ValueError("unterminated string")


def _split_note(rest: str) -> tuple[str, str | None]:
    """``rest`` split at the first ``--`` that isn't inside a string: (the arguments, the note)."""
    i = 0
    while i < len(rest):
        if rest[i] == '"':
            try:
                i = _scan_string(rest, i)
            except ValueError:
                return rest, None  # tokenizing will report the open string
        elif rest.startswith("--", i):
            return rest[:i], rest[i + 2:].strip() or None
        else:
            i += 1
    return rest, None


def _tokenize(body: str, base_col: int, line: _Line) -> list[_Token]:
    tokens: list[_Token] = []
    i = 0
    while i < len(body):
        if body[i].isspace():
            i += 1
            continue
        start = i
        if body[i] == '"':
            try:
                i = _scan_string(body, i)
            except ValueError:
                raise _Problem("this string is never closed", base_col + start, base_col + len(body)) from None
            tokens.append(_Token("string", body[start:i], base_col + start, base_col + i))
        elif body[i] == "{":
            depth = 0
            while i < len(body):
                if body[i] == '"':
                    try:
                        i = _scan_string(body, i)
                    except ValueError:
                        raise _Problem("this string is never closed", base_col + i, base_col + len(body)) from None
                    continue
                depth += body[i] == "{"
                depth -= body[i] == "}"
                i += 1
                if depth == 0:
                    break
            if depth != 0:
                raise _Problem("this { is never closed with }", base_col + start, base_col + len(body))
            tokens.append(_Token("braces", body[start:i], base_col + start, base_col + i))
        else:
            while i < len(body) and not body[i].isspace():
                if body[i] == '"':
                    try:
                        i = _scan_string(body, i)
                    except ValueError:
                        raise _Problem("this string is never closed", base_col + i, base_col + len(body)) from None
                else:
                    i += 1
            tokens.append(_Token("word", body[start:i], base_col + start, base_col + i))
    return tokens


def _unquote(text: str) -> str:
    return re.sub(r"\\(.)", r"\1", text[1:-1])


# -- argument helpers ------------------------------------------------------------------------------------


def _ident(line: _Line, token: _Token, what: str) -> str:
    if token.kind != "word" or not _IDENT.fullmatch(token.text):
        raise line.problem(f"{what} must be a plain name (letters, digits and underscores), not {token.text!r}", token)
    return token.text


def _declared_name(line: _Line, token: _Token, what: str = "a name") -> str:
    name = _ident(line, token, what)
    if name in _KEYWORDS:
        raise line.problem(f"{name!r} can't be used as a name: it's a Megalo keyword or a built-in value", token)
    return name


def _dotted(line: _Line, token: _Token, left: str, right: str) -> tuple[str, str]:
    """``KIND.NAME`` -> ``("KIND", "NAME")``."""
    parts = token.text.split(".")
    if token.kind != "word" or len(parts) != 2 or not all(_IDENT.fullmatch(p) for p in parts):
        raise line.problem(f"expected {left}.{right}, not {token.text!r}", token)
    if parts[1] in _KEYWORDS:
        raise line.problem(f"{parts[1]!r} can't be used as a name: it's a Megalo keyword or a built-in value", token)
    return parts[0], parts[1]


def _exactly(line: _Line, count: int, usage: str) -> None:
    if len(line.tokens) < count:
        raise line.problem(f"@{line.name} needs {usage}")
    if len(line.tokens) > count:
        extra = line.tokens[count]
        if count == 0:
            raise line.problem(f"@{line.name} takes no arguments (put a note after a second '--')", extra)
        raise line.problem(f"unexpected {extra.text!r} after {usage} (put a note after a second '--')", extra)


def _expression(line: _Line) -> Expression:
    text = line.body.strip()
    if not text:
        raise line.problem(f"@{line.name} needs a condition")
    col = line.body_col + (len(line.body) - len(line.body.lstrip()))
    try:
        return parse_expression(text, line=line.number, col=col)
    except (MegaloLexError, MegaloParseError) as exc:
        token = getattr(exc, "token", None)
        at = getattr(token, "start_col", col)
        raise _Problem(str(exc).split(" at line")[0], at, max(at + 1, line.line_end)) from None


def _keyword_args(line: _Line, tokens: list[_Token], allowed: tuple[str, ...]) -> dict[str, tuple[str, _Token]]:
    """``key=value`` arguments: ``{key: (value text, its token)}``. Unknown keys and repeats are problems."""
    found: dict[str, tuple[str, _Token]] = {}
    for token in tokens:
        key, sep, value = token.text.partition("=")
        if token.kind != "word" or not sep or not _IDENT.fullmatch(key):
            raise line.problem(f"expected key=value (one of {', '.join(allowed)}), not {token.text!r}", token)
        if key not in allowed:
            raise line.problem(f"unknown option {key!r} for @{line.name} (expected {', '.join(allowed)})", token)
        if key in found:
            raise line.problem(f"{key} is given twice", token)
        if not value:
            raise line.problem(f"{key}= needs a value", token)
        found[key] = (value, token)
    return found


def _bool(line: _Line, value: str, token: _Token, key: str) -> bool:
    if value not in ("true", "false"):
        raise line.problem(f"{key} must be true or false, not {value!r}", token)
    return value == "true"


def _field_value(text: str) -> FieldValue | None:
    """A braced group's ``value``: a number, a ``"string"``, ``true``/``false`` or a bare word; ``None`` if it
    is none of those."""
    text = text.strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return _unquote(text)
    if _INT.fullmatch(text):
        return int(text)
    if text in ("true", "false"):
        return text == "true"
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", text):
        return text
    return None


def _split_commas(content: str, offset: int) -> list[tuple[str, int]]:
    """``content`` split at top-level commas, each piece with its offset in the line."""
    pieces: list[tuple[str, int]] = []
    start = 0
    i = 0
    while i < len(content):
        if content[i] == '"':
            try:
                i = _scan_string(content, i)
            except ValueError:
                i = len(content)
            continue
        if content[i] == ",":
            pieces.append((content[start:i], offset + start))
            start = i + 1
        i += 1
    pieces.append((content[start:], offset + start))
    return [(text, at) for text, at in pieces if text.strip()]


def _braced(line: _Line, token: _Token) -> tuple[str, int]:
    if token.kind != "braces":
        raise line.problem(f"expected a {{ ... }} group, not {token.text!r}", token)
    return token.text[1:-1], token.col + 1


def _fields(line: _Line, token: _Token) -> dict[str, FieldValue]:
    content, offset = _braced(line, token)
    fields: dict[str, FieldValue] = {}
    for piece, at in _split_commas(content, offset):
        key, sep, raw = piece.partition("=")
        key_col = at + (len(piece) - len(piece.lstrip()))
        here = _Token("word", piece.strip(), key_col, key_col + len(piece.strip()))
        if not sep or not _IDENT.fullmatch(key.strip()):
            raise line.problem(f"expected name = value, not {piece.strip()!r}", here)
        value = _field_value(raw)
        if value is None:
            raise line.problem(f"{raw.strip()!r} isn't a number, a \"string\", true/false or a plain word", here)
        if key.strip() in fields:
            raise line.problem(f"{key.strip()} is given twice", here)
        fields[key.strip()] = value
    return fields


# -- one interpreter per annotation ----------------------------------------------------------------------


def _storage(line: _Line) -> StorageAnnotation:
    scope, type_ = _STORAGE_NAMES[line.name]
    if not line.tokens:
        raise line.problem(f"@{line.name} needs a name")
    target, options = line.tokens[0], line.tokens[1:]

    owner: str | None = None
    if scope in ("global", "player"):
        name = _declared_name(line, target)
    else:
        left = "KIND" if scope == "object" else "TEAM"
        owner, name = _dotted(line, target, left, "NAME")

    allowed = ("priority", "default") + (("owns_default",) if scope == "object" else ())
    given = _keyword_args(line, options, allowed)
    priority = default = None
    owns_default = False
    if "priority" in given:
        value, token = given["priority"]
        if type_ == "timer":
            raise line.problem("a timer has no network priority", token)
        if value not in _PRIORITIES:
            raise line.problem(f"priority must be one of {', '.join(_PRIORITIES)}, not {value!r}", token)
        priority = value
    if "default" in given:
        value, token = given["default"]
        if type_ in ("player", "object"):
            article = "an" if type_ == "object" else "a"
            raise line.problem(f"{article} {type_} variable has no initial value", token)
        try:
            default = parse_expression(value, line=line.number, col=token.col + len("default="))
        except (MegaloLexError, MegaloParseError):
            raise line.problem(f"{value!r} isn't a valid value", token) from None
    if "owns_default" in given:
        value, token = given["owns_default"]
        owns_default = _bool(line, value, token, "owns_default")
    return StorageAnnotation(
        span=line.span(line.name_col, line.line_end), note=line.note, scope=scope, type=type_, name=name,
        owner=owner, priority=priority, default=default, owns_default=owns_default,
    )


def _bitfield(line: _Line) -> BitfieldAnnotation:
    if len(line.tokens) < 2:
        raise line.problem("@bitfield needs KIND.NAME and a { flag, flag } group")
    owner, name = _dotted(line, line.tokens[0], "KIND", "NAME")
    content, offset = _braced(line, line.tokens[1])  # before _exactly: the group being wrong is the first problem
    _exactly(line, 2, "KIND.NAME and a { ... } group")
    flags: list[str] = []
    for piece, at in _split_commas(content, offset):
        flag = piece.strip()
        here = _Token("word", flag, at + (len(piece) - len(piece.lstrip())), at + len(piece.rstrip()))
        if not _IDENT.fullmatch(flag):
            raise line.problem(f"{flag!r} isn't a valid flag name", here)
        if flag in flags:
            raise line.problem(f"flag {flag} is listed twice", here)
        flags.append(flag)
    if not flags:
        raise line.problem("a bitfield needs at least one flag", line.tokens[1])
    return BitfieldAnnotation(span=line.span(line.name_col, line.line_end), note=line.note, owner=owner, name=name, flags=flags)


def _resource(line: _Line, model: type[_ResourceAnnotation]) -> _ResourceAnnotation:
    if not line.tokens:
        raise line.problem(f"@{line.name} needs a name")
    name = _declared_name(line, line.tokens[0])
    if len(line.tokens) >= 2:
        _braced(line, line.tokens[1])  # the second argument must be the group; say so before complaining about the rest
    if len(line.tokens) > 2:
        raise line.problem(f"unexpected {line.tokens[2].text!r} (put a note after a second '--')", line.tokens[2])
    fields = _fields(line, line.tokens[1]) if len(line.tokens) == 2 else {}
    return model(span=line.span(line.name_col, line.line_end), note=line.note, name=name, fields=fields)


def _label(line: _Line) -> LabelAnnotation:
    if len(line.tokens) < 3:
        raise line.problem('@label needs NAME = "text"')
    _exactly(line, 3, 'NAME = "text"')
    name = _declared_name(line, line.tokens[0])
    if line.tokens[1].text != "=":
        raise line.problem(f"expected '=' after the name, not {line.tokens[1].text!r}", line.tokens[1])
    if line.tokens[2].kind != "string":
        raise line.problem(f'the label\'s text must be a "quoted string", not {line.tokens[2].text!r}', line.tokens[2])
    return LabelAnnotation(span=line.span(line.name_col, line.line_end), note=line.note, name=name, text=_unquote(line.tokens[2].text))


def _block(line: _Line) -> BlockAnnotation:
    _exactly(line, 1, "a block name")
    token = line.tokens[0]
    if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", token.text):
        raise line.problem(f"a block name is UPPER_CASE letters, digits and underscores, not {token.text!r}", token)
    return BlockAnnotation(span=line.span(line.name_col, line.line_end), note=line.note, name=token.text)


def _fragment(line: _Line) -> FragmentAnnotation:
    _exactly(line, 1, "BLOCK.NAME")
    block, name = _dotted(line, line.tokens[0], "BLOCK", "NAME")
    return FragmentAnnotation(span=line.span(line.name_col, line.line_end), note=line.note, block=block, name=name)


def _loop(line: _Line) -> LoopAnnotation:
    _exactly(line, 1, "player, object or team")
    token = line.tokens[0]
    if token.text not in _LOOP_SELECTORS:
        raise line.problem(f"expected one of {', '.join(_LOOP_SELECTORS)}, not {token.text!r}", token)
    return LoopAnnotation(span=line.span(line.name_col, line.line_end), note=line.note, selector=token.text)


def _gate(line: _Line) -> GateAnnotation:
    return GateAnnotation(span=line.span(line.name_col, line.line_end), note=line.note, condition=_expression(line))


def _guard(line: _Line) -> GuardAnnotation:
    return GuardAnnotation(span=line.span(line.name_col, line.line_end), note=line.note, condition=_expression(line))


def _guard_end(line: _Line) -> GuardEndAnnotation:
    _exactly(line, 0, "nothing")
    return GuardEndAnnotation(span=line.span(line.name_col, line.line_end), note=line.note)


def _preamble(line: _Line) -> PreambleAnnotation:
    _exactly(line, 1, "a name")
    return PreambleAnnotation(
        span=line.span(line.name_col, line.line_end), note=line.note, name=_declared_name(line, line.tokens[0])
    )


def _provides(line: _Line) -> ProvidesAnnotation:
    if not line.tokens:
        raise line.problem("@provides needs name:type pairs, like cx:object role:number")
    variables: list[ProvidedVariable] = []
    for token in line.tokens:
        name, sep, type_ = token.text.partition(":")
        if token.kind != "word" or not sep or not _IDENT.fullmatch(name):
            raise line.problem(f"expected name:type, not {token.text!r}", token)
        if type_ not in _TYPES:
            raise line.problem(f"{type_!r} isn't a type (expected {', '.join(_TYPES)})", token)
        if any(v.name == name for v in variables):
            raise line.problem(f"{name} is listed twice", token)
        variables.append(ProvidedVariable(name=_declared_name(line, _Token("word", name, token.col, token.end)), type=type_))
    return ProvidesAnnotation(span=line.span(line.name_col, line.line_end), note=line.note, variables=variables)


def _traits(line: _Line) -> TraitsAnnotation:
    if not line.tokens:
        raise line.problem("@traits needs layer=NAME")
    given = _keyword_args(line, line.tokens, ("layer",))
    if "layer" not in given:
        raise line.problem("@traits needs layer=NAME")
    value, token = given["layer"]
    if not _IDENT.fullmatch(value):
        raise line.problem(f"the layer must be a plain name, not {value!r}", token)
    return TraitsAnnotation(span=line.span(line.name_col, line.line_end), note=line.note, layer=value)


def _fusion(line: _Line) -> FusionAnnotation:
    _exactly(line, 1, "auto, never, subroutine or force:GROUP")
    token = line.tokens[0]
    mode, sep, group = token.text.partition(":")
    if mode == "force":
        if not sep or not _IDENT.fullmatch(group):
            raise line.problem("force needs a group: force:GROUP", token)
        return FusionAnnotation(span=line.span(line.name_col, line.line_end), note=line.note, mode="force", group=group)
    if sep or mode not in _FUSION_MODES:
        raise line.problem(f"expected auto, never, subroutine or force:GROUP, not {token.text!r}", token)
    return FusionAnnotation(span=line.span(line.name_col, line.line_end), note=line.note, mode=mode)


def _doc(line: _Line) -> DocAnnotation:
    text = line.body.strip()
    if not text:
        raise line.problem("@doc needs some text")
    return DocAnnotation(span=line.span(line.name_col, line.line_end), text=text)


_SEE_TARGET = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")


def _see(line: _Line) -> SeeAnnotation:
    """``@see TARGET``: a tag, a block, a module, a fragment (``module.name``) or a declared name."""
    _exactly(line, 1, "a tag, block, module, fragment or name")
    token = line.tokens[0]
    if token.kind != "word" or not _SEE_TARGET.fullmatch(token.text):
        raise line.problem(f"{token.text!r} isn't something @see can point at", token)
    return SeeAnnotation(span=line.span(line.name_col, line.line_end), note=line.note, tag=token.text)


def _assumes(line: _Line) -> AssumesAnnotation:
    _exactly(line, 1, "a block name")
    return AssumesAnnotation(
        span=line.span(line.name_col, line.line_end), note=line.note, block=_ident(line, line.tokens[0], "a block name")
    )


_TAG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]*")


def _tags(line: _Line) -> TagsAnnotation:
    tags: list[str] = []
    for token in line.tokens:
        for part in token.text.split(","):
            part = part.strip()
            if not part:
                continue
            if token.kind != "word" or not _TAG.fullmatch(part):
                raise line.problem(f"{part!r} isn't a tag (letters, digits, '_' and '-')", token)
            if part not in tags:
                tags.append(part)
    if not tags:
        raise line.problem("@tags needs at least one tag: @tags scoring, hud")
    return TagsAnnotation(span=line.span(line.name_col, line.line_end), note=line.note, tags=tags)


_INTERPRETERS = {
    **{name: _storage for name in _STORAGE_NAMES},
    "bitfield": _bitfield,
    "trait": lambda line: _resource(line, TraitAnnotation),
    "option": lambda line: _resource(line, OptionAnnotation),
    "widget": lambda line: _resource(line, WidgetAnnotation),
    "label": _label,
    "block": _block,
    "fragment": _fragment,
    "loop": _loop,
    "gate": _gate,
    "guard": _guard,
    "guard-end": _guard_end,
    "preamble": _preamble,
    "provides": _provides,
    "traits": _traits,
    "fusion": _fusion,
    "doc": _doc,
    "see": _see,
    "assumes": _assumes,
    "tags": _tags,
}

#: Names whose whole remainder is prose or an expression, so ``--`` inside isn't a note delimiter.
_WHOLE_LINE = frozenset({"doc"})


def parse_annotations(text: str) -> Annotations:
    """Reads every ``-- @name ...`` annotation in ``text`` (a script, or any text with such comment lines).

    Never raises; see the module docstring for what is accepted and how problems are reported."""
    result = Annotations()
    for number, raw in enumerate(text.splitlines(), start=1):
        match = _LINE.match(raw)
        if match is None or match["name"] in _DIRECTIVES:
            continue
        name = match["name"]
        name_col = match.end("indent") + raw[match.end("indent"):].index("@")
        line_end = len(raw.rstrip())
        rest = match["rest"]
        rest_col = match.start("rest")
        if name in _WHOLE_LINE:
            body, note = rest, None
        else:
            body, note = _split_note(rest)
        line = _Line(number=number, name=name, name_col=name_col, line_end=line_end, body=body,
                     body_col=rest_col, note=note, tokens=[])

        interpreter = _INTERPRETERS.get(name)
        try:
            if interpreter is None:
                close = difflib.get_close_matches(name, list(_INTERPRETERS), n=1)
                hint = f" -- did you mean @{close[0]}?" if close else ""
                raise _Problem(f"unknown annotation @{name}{hint}", name_col, name_col + 1 + len(name))
            if name not in _WHOLE_LINE and name not in ("gate", "guard"):
                line.tokens = _tokenize(body, rest_col, line)
            result.items.append(interpreter(line))
        except _Problem as problem:
            result.diagnostics.append(
                AnnotationDiagnostic(span=line.span(problem.col, problem.end), message=problem.message)
            )
    return result
