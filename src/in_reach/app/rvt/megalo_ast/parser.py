"""Recursive-descent parser: Megalo script text (``script/output.txt``, or the richer hand-
authorable dialect -- see ``nodes.py``'s module docstring) -> ``nodes.Script``.

Ported verbatim from a prior prototype (``D:\\whileyRepos\\sort\\mega-ide``, PROMPT.md: "we want a
fromm scratch compiler then") -- see ``nodes.py``'s own module docstring for the full port note.
That prototype's own ``AST.md`` documents this grammar's coverage in detail: checked directly
against every fixture it had (including a real ``a and b or c`` mixed-precedence case, and a real
``%=`` compound assignment), and against every real MCC-shipped built-in game/hopper variant
(474/475 ``.bin``s -- the one exclusion fails at the engine's own loader, unrelated to this grammar)
with zero grammar changes needed on that final sweep.

Grammar (informal; see ``nodes.py`` for the node shapes this produces), lowest to highest binding
power for expressions. ``alias_decl``/the ``altif``/``alt`` clauses of ``if_stmt`` are the richer
dialect (confirmed directly via ``compile_script()``, not present in anything
``decompile_script()`` emits); comments are stripped before this grammar ever sees them (see
``lexer.py``/``parse()`` below) and so aren't part of it at all::

    script      := (declaration | alias_decl | function_decl | statement)*
    declaration := "declare" IDENT "." IDENT "[" INT "]"
                   ("with" "network" "priority" IDENT)? ("=" or_expr)?
    alias_decl  := "alias" IDENT "=" or_expr
    function_decl := "function" IDENT "(" ")" block "end"   -- top level only, never nested
    statement   := for_each | do_block | if_stmt | on_trigger | declaration | alias_decl | simple_stmt
    for_each    := "for" "each" IDENT (("with" "label" label_val) | "randomly")* "do" block "end"
    do_block    := "do" block "end"
    if_stmt     := "if" or_expr "then" block ("altif" or_expr "then" block)* ("alt" block)? "end"
    on_trigger  := "on" IDENT+ ":" statement
    simple_stmt := or_expr (("=" | "+=" | "-=" | "*=" | "/=" | "%=") or_expr)?
    block       := statement*

    or_expr     := and_expr ("or" and_expr)*
    and_expr    := not_expr ("and" not_expr)*
    not_expr    := "not" not_expr | compare_expr
    compare_expr:= flag_expr (("==" | "!=" | "<" | ">" | "<=" | ">=") flag_expr)?
    flag_expr   := postfix ("|" postfix)*
    postfix     := primary ("." IDENT | "[" or_expr "]" | "(" (or_expr ("," or_expr)*)? ")")*
    primary     := INT | PERCENT | STRING | IDENT | "(" or_expr ")"
"""
from __future__ import annotations

from .lexer import Token, tokenize
from .nodes import (
    AliasDeclaration, Assignment, BinaryOp, Call, Comment, DoBlock, ElseIfClause, EventTrigger,
    Expression, ExprStatement, ForEach, FunctionDeclaration, Identifier, IfStatement, Index,
    IntLiteral, Member, PercentLiteral, Script, SourceSpan, Statement, StringLiteral, UnaryOp,
    VariableDeclaration,
)

_ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%="}
_COMPARE_OPS = {"==", "!=", "<", ">", "<=", ">="}
_IF_STOP_WORDS = frozenset({"altif", "alt", "end"})

# Every word Compiler::is_keyword() (compiler.cpp) reserves that this grammar does NOT implement a
# production for. Every other reserved word (alias/alt/altif/and/declare/do/end/for/function/if/
# not/on/or/then) IS handled, contextually, by the grammar above. Checked here -- rather than just
# falling through to _parse_primary()'s default "unknown identifier -> Identifier" case -- so that a
# real keyword this grammar doesn't cover yet raises a clear MegaloParseError instead of silently
# being misparsed as a bare identifier/call expression (confirmed this was a real risk, not
# hypothetical, before "function" itself got a real production below: a top-level function
# declaration used to parse as unrelated statements with no error at all). "else"/"elseif" are
# reserved but not actually functional in this compiler build either (see nodes.py's module
# docstring) -- included here for the same "don't silently misinterpret a real keyword" reason, even
# though they'll never have a real production to add.
_UNIMPLEMENTED_RESERVED_WORDS = frozenset({"else", "elseif", "enum", "inline"})


class MegaloParseError(Exception):
    def __init__(self, message: str, token: Token):
        super().__init__(f"{message} at line {token.start_line}, col {token.start_col} (got {token.kind} {token.text!r})")
        self.token = token


def _span(start: Token, end: Token) -> SourceSpan:
    return SourceSpan(start_line=start.start_line, start_col=start.start_col, end_line=end.end_line, end_col=end.end_col)


class _Parser:
    def __init__(self, tokens: list[Token]):
        self._tokens = tokens
        self._pos = 0

    def _peek(self) -> Token:
        return self._tokens[self._pos]

    def _advance(self) -> Token:
        tok = self._tokens[self._pos]
        if tok.kind != "eof":
            self._pos += 1
        return tok

    def _at_ident(self, text: str) -> bool:
        tok = self._peek()
        return tok.kind == "ident" and tok.text == text

    def _at_punct(self, text: str) -> bool:
        tok = self._peek()
        return tok.kind == "punct" and tok.text == text

    def _expect_ident(self, text: str | None = None) -> Token:
        tok = self._peek()
        if tok.kind != "ident" or (text is not None and tok.text != text):
            raise MegaloParseError(f"expected {'identifier' if text is None else text!r}", tok)
        return self._advance()

    def _expect_punct(self, text: str) -> Token:
        tok = self._peek()
        if tok.kind != "punct" or tok.text != text:
            raise MegaloParseError(f"expected {text!r}", tok)
        return self._advance()

    # ---- top level --------------------------------------------------------------------------

    def parse_script(self) -> Script:
        body: list[Statement] = []
        while self._peek().kind != "eof":
            body.append(self._parse_top_level_item())
        return Script(body=body)

    def _parse_top_level_item(self) -> Statement:
        if self._at_ident("declare"):
            return self._parse_declaration()
        if self._at_ident("alias"):
            return self._parse_alias()
        if self._at_ident("function"):
            return self._parse_function_declaration()
        return self._parse_statement()

    def _parse_function_declaration(self) -> FunctionDeclaration:
        # Only ever appears at the top level (never called from _parse_statement()) -- real Megalo
        # has no local/nested functions, see FunctionDeclaration's own docstring.
        start = self._expect_ident("function")
        name = self._expect_ident().text
        self._expect_punct("(")
        self._expect_punct(")")
        body = self._parse_block()
        end_tok = self._expect_ident("end")
        return FunctionDeclaration(name=name, body=body, span=_span(start, end_tok))

    # ---- statements --------------------------------------------------------------------------

    def _parse_declaration(self) -> VariableDeclaration:
        start = self._expect_ident("declare")
        scope = self._expect_ident().text
        self._expect_punct(".")
        vtype = self._expect_ident().text
        self._expect_punct("[")
        index = self._expect_int()
        self._expect_punct("]")
        priority = None
        end_tok = self._tokens[self._pos - 1]
        if self._at_ident("with"):
            self._advance()
            self._expect_ident("network")
            self._expect_ident("priority")
            priority = self._expect_ident().text
            end_tok = self._tokens[self._pos - 1]
        value = None
        if self._at_punct("="):
            self._advance()
            value = self._parse_or_expr()
            end_tok = self._tokens[self._pos - 1]
        return VariableDeclaration(scope=scope, type=vtype, index=index, priority=priority, value=value, span=_span(start, end_tok))

    def _expect_int(self) -> int:
        tok = self._peek()
        if tok.kind != "int":
            raise MegaloParseError("expected an integer", tok)
        self._advance()
        return tok.value

    def _parse_statement(self) -> Statement:
        if self._at_ident("for"):
            return self._parse_for_each()
        if self._at_ident("do"):
            return self._parse_do_block()
        if self._at_ident("if"):
            return self._parse_if()
        if self._at_ident("on"):
            return self._parse_on_trigger()
        if self._at_ident("declare"):
            return self._parse_declaration()
        if self._at_ident("alias"):
            return self._parse_alias()
        return self._parse_simple_statement()

    def _parse_alias(self) -> AliasDeclaration:
        start = self._expect_ident("alias")
        name = self._expect_ident().text
        self._expect_punct("=")
        value = self._parse_or_expr()
        return AliasDeclaration(name=name, value=value, span=_span(start, self._tokens[self._pos - 1]))

    def _parse_block(self, stop_words: frozenset[str] = frozenset({"end"})) -> list[Statement]:
        body: list[Statement] = []
        while self._peek().kind != "eof" and not (self._peek().kind == "ident" and self._peek().text in stop_words):
            body.append(self._parse_statement())
        return body

    def _parse_for_each(self) -> ForEach:
        start = self._expect_ident("for")
        self._expect_ident("each")
        selector = self._expect_ident().text
        label: Expression | None = None
        randomly = False
        while True:
            if self._at_ident("with"):
                self._advance()
                self._expect_ident("label")
                label = self._parse_label_value()
            elif self._at_ident("randomly"):
                self._advance()
                randomly = True
            else:
                break
        self._expect_ident("do")
        body = self._parse_block()
        end_tok = self._expect_ident("end")
        return ForEach(selector=selector, label=label, randomly=randomly, body=body, span=_span(start, end_tok))

    def _parse_label_value(self) -> Expression:
        tok = self._peek()
        if tok.kind == "int":
            self._advance()
            return IntLiteral(value=tok.value, span=_span(tok, tok))
        if tok.kind == "string":
            self._advance()
            return StringLiteral(value=tok.value, span=_span(tok, tok))
        raise MegaloParseError("expected a label value (int or string)", tok)

    def _parse_do_block(self) -> DoBlock:
        start = self._expect_ident("do")
        body = self._parse_block()
        end_tok = self._expect_ident("end")
        return DoBlock(body=body, span=_span(start, end_tok))

    def _parse_if(self) -> IfStatement:
        start = self._expect_ident("if")
        condition = self._parse_or_expr()
        self._expect_ident("then")
        body = self._parse_block(_IF_STOP_WORDS)
        altif_clauses: list[ElseIfClause] = []
        while self._at_ident("altif"):
            altif_start = self._advance()
            altif_cond = self._parse_or_expr()
            self._expect_ident("then")
            altif_body = self._parse_block(_IF_STOP_WORDS)
            altif_clauses.append(ElseIfClause(condition=altif_cond, body=altif_body, span=_span(altif_start, self._tokens[self._pos - 1])))
        alt_body: list[Statement] | None = None
        if self._at_ident("alt"):
            self._advance()
            alt_body = self._parse_block()  # only "end" can follow -- the compiler itself forbids another altif/alt after "alt"
        end_tok = self._expect_ident("end")
        return IfStatement(condition=condition, body=body, altif_clauses=altif_clauses, alt_body=alt_body, span=_span(start, end_tok))

    def _parse_on_trigger(self) -> EventTrigger:
        start = self._expect_ident("on")
        words = []
        while self._peek().kind == "ident":
            words.append(self._advance().text)
        if not words:
            raise MegaloParseError("expected an event name after 'on'", self._peek())
        self._expect_punct(":")
        body = self._parse_statement()
        return EventTrigger(event=" ".join(words), body=body, span=_span(start, self._tokens[self._pos - 1]))

    def _parse_simple_statement(self) -> Statement:
        start = self._peek()
        expr = self._parse_or_expr()
        tok = self._peek()
        if tok.kind == "punct" and tok.text in _ASSIGN_OPS:
            op = self._advance().text
            value = self._parse_or_expr()
            return Assignment(op=op, target=expr, value=value, span=_span(start, self._tokens[self._pos - 1]))
        return ExprStatement(expr=expr, span=_span(start, self._tokens[self._pos - 1]))

    # ---- expressions -------------------------------------------------------------------------

    def _parse_or_expr(self) -> Expression:
        start = self._peek()
        left = self._parse_and_expr()
        while self._at_ident("or"):
            self._advance()
            right = self._parse_and_expr()
            left = BinaryOp(op="or", left=left, right=right, span=_span(start, self._tokens[self._pos - 1]))
        return left

    def _parse_and_expr(self) -> Expression:
        start = self._peek()
        left = self._parse_not_expr()
        while self._at_ident("and"):
            self._advance()
            right = self._parse_not_expr()
            left = BinaryOp(op="and", left=left, right=right, span=_span(start, self._tokens[self._pos - 1]))
        return left

    def _parse_not_expr(self) -> Expression:
        if self._at_ident("not"):
            start = self._advance()
            operand = self._parse_not_expr()
            return UnaryOp(op="not", operand=operand, span=_span(start, self._tokens[self._pos - 1]))
        return self._parse_compare_expr()

    def _parse_compare_expr(self) -> Expression:
        start = self._peek()
        left = self._parse_flag_expr()
        tok = self._peek()
        if tok.kind == "punct" and tok.text in _COMPARE_OPS:
            op = self._advance().text
            right = self._parse_flag_expr()
            return BinaryOp(op=op, left=left, right=right, span=_span(start, self._tokens[self._pos - 1]))
        return left

    def _parse_flag_expr(self) -> Expression:
        start = self._peek()
        left = self._parse_postfix()
        while self._at_punct("|"):
            self._advance()
            right = self._parse_postfix()
            left = BinaryOp(op="|", left=left, right=right, span=_span(start, self._tokens[self._pos - 1]))
        return left

    def _parse_postfix(self) -> Expression:
        start = self._peek()
        expr = self._parse_primary()
        while True:
            if self._at_punct("."):
                self._advance()
                name = self._expect_ident().text
                expr = Member(target=expr, name=name, span=_span(start, self._tokens[self._pos - 1]))
            elif self._at_punct("["):
                self._advance()
                idx = self._parse_or_expr()
                self._expect_punct("]")
                expr = Index(target=expr, index=idx, span=_span(start, self._tokens[self._pos - 1]))
            elif self._at_punct("("):
                self._advance()
                args: list[Expression] = []
                if not self._at_punct(")"):
                    args.append(self._parse_or_expr())
                    while self._at_punct(","):
                        self._advance()
                        args.append(self._parse_or_expr())
                self._expect_punct(")")
                expr = Call(target=expr, args=args, span=_span(start, self._tokens[self._pos - 1]))
            else:
                break
        return expr

    def _parse_primary(self) -> Expression:
        tok = self._peek()
        if tok.kind == "int":
            self._advance()
            return IntLiteral(value=tok.value, span=_span(tok, tok))
        if tok.kind == "percent":
            self._advance()
            return PercentLiteral(value=tok.value, span=_span(tok, tok))
        if tok.kind == "string":
            self._advance()
            return StringLiteral(value=tok.value, span=_span(tok, tok))
        if tok.kind == "ident":
            if tok.text in _UNIMPLEMENTED_RESERVED_WORDS:
                raise MegaloParseError(
                    f"{tok.text!r} is a real Megalo keyword this grammar doesn't implement yet (confirmed reserved via "
                    "Compiler::is_keyword() and compile_script()) -- not a plain identifier",
                    tok,
                )
            self._advance()
            return Identifier(name=tok.text, span=_span(tok, tok))
        if tok.kind == "punct" and tok.text == "(":
            self._advance()
            expr = self._parse_or_expr()
            self._expect_punct(")")
            return expr
        raise MegaloParseError("expected an expression", tok)


def parse(source: str) -> Script:
    """Parses Megalo script text (``script/output.txt``, or the richer hand-authorable dialect)
    into a ``Script`` AST. Raises ``MegaloLexError``/``MegaloParseError`` on malformed input -- see
    this module's grammar comment and ``nodes.py``'s docstring for the grammar this covers.

    Comment tokens are stripped out of the token stream before the grammar above ever runs (the
    parser has no comment-skipping logic anywhere in it) and collected into ``Script.comments``
    instead -- see ``nodes.Comment``'s own docstring for why comments are a flat list rather than
    woven into the statement tree."""
    tokens = tokenize(source)
    code_tokens = [t for t in tokens if t.kind != "comment"]
    comments = [Comment(text=t.text, span=_span(t, t)) for t in tokens if t.kind == "comment"]
    script = _Parser(code_tokens).parse_script()
    script.comments = comments
    return script
