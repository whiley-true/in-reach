"""The engine-bound half of :mod:`in_reach.app.rvt.megalo_ast` (see this package's ``__init__.py``):
pydantic models built directly from ``_reachvarianttool``'s real, compiled Megalo Trigger/Opcode/
Condition/Action/OpcodeArgValue object graph -- not text, and not the from-scratch grammar over
decompiled text that ``nodes.py``/``parser.py`` implement.

Ported from a prior prototype (``D:\\whileyRepos\\sort\\mega-ide``, PROMPT.md: "we want a fromm
scratch compiler then") -- its own ``AST.md`` has the full design rationale/validation history this
docstring summarizes, including everything confirmed by direct testing (not read-and-assumed) against
the real ``juggernaut``/``infection``/``invasion`` fixtures: 192 of 325 real arguments across
``juggernaut.bin`` resolve as structured variables once unwrapped through ``AnyVariable``/
``PlayerOrGroupVariable``'s own ``.variable`` field; the nested-tree reconstruction below matches the
independent, from-scratch text grammar's own if/for-each counts exactly for ``juggernaut``/
``infection``, and ~1.5% higher for ``invasion`` (expected -- the text grammar collapses chained
``altif`` into one ``IfStatement``, this tree deliberately doesn't).

Deliberately a different, sibling shape from ``nodes.py``'s ``Script``/``Statement`` tree, not a
drop-in replacement: the engine's own model is genuinely flatter than decompiled text suggests --
each Trigger holds one flat, program-order list of Condition/Action opcodes (``Condition.or_group``/
``.action`` gate which downstream action(s) run, rather than owning a nested body). Two things build
on top of that flat list here, both engine-verified rather than guessed:

1. ``EngineTrigger.body``/``EngineArgument.inline_scope`` -- a nested if/do/for-each statement tree,
   reconstructed in pure Python by ``_build_statements()``, a direct port of the real decompiler's
   own block-reconstruction algorithm (``CodeBlock::decompile()``/``Trigger::decompile()``,
   ``game_variants/components/megalo/{code_block,trigger}.cpp`` in the vendored ReachVariantTool
   source -- read in full before writing this, not guessed from decompiled-text examples). The key
   fact that algorithm reveals: nesting is purely positional. A run of consecutive Condition opcodes
   opens one if-level; everything after it in the SAME flat opcode list -- not just up to the next
   condition run -- becomes that if's body, recursively, so multiple condition runs in one trigger
   nest inside each other, not sideways as siblings. The only other block constructs are "Run Nested
   Trigger" (branches to a separate Trigger, inlined as a do/for-each/spliced-if block when that
   trigger is only ever reached from here, or rendered as an opaque ``EngineTriggerCallStatement``
   when it's a real, multiply-called subroutine) and "Run Inline Trigger" (an argument-embedded
   CodeBlock, ``MegaloScopeArgument.data``, inlined the same way). Whether a nested-trigger target
   counts as "a real subroutine" is itself engine state (``Trigger.decompile_state.is_function``)
   that only exists transiently inside ``Decompiler::decompile()`` and is cleared again before
   control returns to Python (confirmed by reading ``decompiler.cpp`` end to end) -- so
   ``_compute_is_function_flags()`` is a from-scratch Python port of
   ``TriggerDecompileState::setup_callees()``/``check_if_is_function()`` (``trigger.cpp``), not a
   binding of anything readable off a loaded Trigger directly. This same non-configurable
   inline-vs-nested decision is the root cause behind :mod:`in_reach.app.rvt.megalo_compiler`
   existing at all -- see that module's own docstring.
2. ``EngineArgument``'s family-specific optional fields (``raw_value``/``vector``/``index_ref``/
   ``resolved_name``/``player_set``/``shape``/``waypoint_icon``/``meter``/``object_timer_variable``/
   ``object_player_variable``/``format_string``/``inline_scope``) -- structured access to every
   argument family the native binding exposes beyond the plain ``Variable`` case. A type with
   nothing more specific to say than "it's an OpcodeArgValue of this concrete class" still gets
   ``argument_type`` set and every other family field left ``None`` -- ``.text``/``.description``
   are always correct regardless (inherited from the engine's own virtual ``to_string()``/
   ``decompile()``), this is purely about which extra structured fields are populated.

Every opcode/argument exposes both ``.text`` (the real Megalo syntax, via the engine's own
Decompiler-based rendering -- ``OpcodeArgValue.decompile()``/``Opcode.decompile()``) and
``.description`` (a human-readable English sentence matching RVT's own GUI trigger-list panel --
``to_string()``). Only ``.text`` is meant to be Megalo source; ``.description`` is a UI-facing gloss,
not compileable.

``EngineArgument.is_variable``/``scope_format``/``which``/``index`` resolve THROUGH the "any of
several variable kinds" wrapper types real scripts mostly actually use for these slots
(``AnyVariable``/``PlayerOrGroupVariable`` -- e.g. the "Compare" condition's operands, "Send
Incident"'s player arguments) via their own ``.variable`` field, not just the plain ``Variable``
case -- confirmed against ``juggernaut.bin``: without unwrapping through ``.variable``, only 0 of
that fixture's 325 arguments came back structured; with it, 192 do (the rest are genuinely non-
variable: enum/flag identifiers, opcode operator tokens, string literals). pybind11's polymorphic
downcasting matches the exact concrete C++ type, not the nearest registered ancestor, which is why
the 5 concrete ``Variable`` leaf classes (``opcode_arg_types/variables/{number,object,player,team,
timer}.h``) need registering by name for ``isinstance()`` to ever match them at all. ``argument_type``
(and every other family-specific field below) is read off the OUTER, not-yet-unwrapped argument --
e.g. an ``AnyVariable`` wrapping a ``ScalarVariable`` reports ``argument_type="AnyVariable"``, with
``is_variable``/``scope_format``/``which``/``index`` describing the wrapped ``ScalarVariable``
underneath, same asymmetry as before this pass.

``.text`` reads "nop" for any opcode whose mapping type is ``none`` (e.g. Run Nested/Inline
Trigger) -- see ``EngineOpcode``'s docstring, this is the engine's own documented behavior, not a
gap here.
"""
from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, Field


class IndexReferenceDetails(BaseModel):
    """TriggerArgument/RequisitionPaletteArgument (both subclass BaseIndexArgument)."""

    name: str
    max: int
    quirk: str  # IndexQuirk enum member name
    value: int


class ObjectTimerVariableDetails(BaseModel):
    base_scope: int
    base_type: int
    index: int  # -1 = none
    is_none: bool


class ObjectPlayerVariableDetails(BaseModel):
    object: "EngineArgument"
    player_index: int  # -1 = none


class PlayerSetDetails(BaseModel):
    set_type: str  # PlayerSetType enum member name
    player: "EngineArgument"
    add_or_remove: "EngineArgument"


class ShapeDetails(BaseModel):
    shape_type: str  # ShapeType enum member name
    radius: "EngineArgument"  # also used as "width"
    length: "EngineArgument"
    top: "EngineArgument"
    bottom: "EngineArgument"


class WaypointIconDetails(BaseModel):
    icon: int
    number: "EngineArgument"


class MeterDetails(BaseModel):
    type: str  # MeterType enum member name
    timer: "EngineArgument"
    numerator: "EngineArgument"
    denominator: "EngineArgument"


class FormatStringTokenDetails(BaseModel):
    type: str  # OpcodeStringTokenType enum member name
    value: "EngineArgument | None" = None  # None if this token slot is unused


class FormatStringDetails(BaseModel):
    persistent: bool
    string_text: str | None = None  # resolved text of the referenced ReachString, if any
    token_count: int
    tokens: list[FormatStringTokenDetails] = Field(default_factory=list)


class EngineArgument(BaseModel):
    text: str  # real Megalo syntax, e.g. "global.number[0]", "current_player", "\"some string\""
    description: str  # human-readable English gloss, e.g. "the global number at index 0"
    variable_type: str  # VariableType enum member name -- "not_a_variable" if this isn't a variable reference
    is_variable: bool  # True if this argument is a Variable (current_player, global.number[0], ...)
    scope_format: str | None = None  # Variable.scope.format template (e.g. "%w.timer[%i]") -- only set when is_variable
    which: int | None = None  # Variable.which -- only set when is_variable
    index: int | None = None  # Variable.index -- only set when is_variable

    argument_type: str
    """The concrete native class name (e.g. "ScalarVariable", "ShapeArgument",
    "ConstBoolArgument") -- always set, regardless of which family field below (if any) is
    populated. Family -> field mapping: ConstBool/ConstSInt8/TimerRate/FireteamList/Incident/
    ObjectType/Sound/VariantStringID/*EnumArgument/*FlagsArgument/*IconArgument -> `raw_value`;
    Vector3Argument -> `vector`; TriggerArgument/RequisitionPaletteArgument -> `index_ref`;
    ForgeLabelArgument/PlayerTraitsArgument -> `resolved_name` (WidgetArgument also reaches this
    branch but has no name field on HUDWidgetDeclaration to resolve, so stays None);
    PlayerSetArgument -> `player_set`; ShapeArgument -> `shape`; WaypointIconArgument ->
    `waypoint_icon`; MeterParametersArgument -> `meter`; ObjectTimerVariableArgument ->
    `object_timer_variable`; ObjectPlayerVariableArgument -> `object_player_variable`;
    FormatString(Persistent)Argument -> `format_string`; MegaloScopeArgument -> `inline_scope`
    (the embedded CodeBlock's own nested statement tree, built the same way as EngineTrigger.body).
    A `Variable`-shaped argument (or one of AnyVariable/PlayerOrGroupVariable's plain, non-variable
    case) populates none of these -- `is_variable`/`scope_format`/`which`/`index` above already
    cover it."""

    raw_value: int | bool | None = None
    vector: tuple[int, int, int] | None = None
    index_ref: IndexReferenceDetails | None = None
    resolved_name: str | None = None
    player_set: PlayerSetDetails | None = None
    shape: ShapeDetails | None = None
    waypoint_icon: WaypointIconDetails | None = None
    meter: MeterDetails | None = None
    object_timer_variable: ObjectTimerVariableDetails | None = None
    object_player_variable: ObjectPlayerVariableDetails | None = None
    format_string: FormatStringDetails | None = None
    inline_scope: "list[EngineStatement] | None" = None


class EngineOpcode(BaseModel):
    """One Condition or Action, straight from the engine. See this module's docstring for the
    nested reconstruction (`EngineTrigger.body`) built on top of the flat list this type appears
    in -- `gated_action_index` is the engine's own raw index, kept here as ground truth even though
    the nested tree no longer needs it to reconstruct structure."""

    kind: Literal["condition", "action"]
    function_name: str  # e.g. "Run Nested Trigger", "Compare", "Set Player Loadout Palette"
    function_desc: str
    mapping_type: str  # OpcodeMappingType enum member name: none/assign/compare/function/property_get/property_set
    text: str  # real Megalo syntax for this one opcode (no surrounding if/then/end -- see module docstring)
    description: str  # human-readable English gloss (RVT's own GUI trigger-list wording)
    inverted: bool | None = None  # Condition only: True for "not <condition>"
    or_group: int | None = None  # Condition only: conditions sharing an or_group are OR-linked; see nodes there
    gated_action_index: int | None = None  # Condition only: index of the action this condition gates
    arguments: list[EngineArgument] = Field(default_factory=list)


class EngineActionStatement(BaseModel):
    """A single, ordinary Condition/Action leaf in the nested tree -- everything that isn't one of
    the block-forming constructs below."""

    node: Literal["action"] = "action"
    opcode: EngineOpcode


class EngineIfStatement(BaseModel):
    """`conditions` is the whole AND/OR-linked run that opened this if-level (inspect each
    EngineOpcode's own `or_group` to see which of them are OR-linked vs. AND-linked to their
    neighbor). `body` is everything from here to the end of the SAME flat opcode list this if-run
    was found in -- not just up to the next condition run -- because that's what the real
    decompiler's block-reconstruction algorithm actually does (see module docstring)."""

    node: Literal["if"] = "if"
    conditions: list[EngineOpcode] = Field(default_factory=list)
    body: "list[EngineStatement]" = Field(default_factory=list)


class EngineDoBlock(BaseModel):
    """A "Run Nested Trigger" action whose target is inlined here (not a real, multiply-called
    subroutine -- see `EngineTriggerCallStatement`) and whose own block_type is `normal`."""

    node: Literal["do"] = "do"
    body: "list[EngineStatement]" = Field(default_factory=list)


class EngineInlineBlock(BaseModel):
    """A "Run Inline Trigger" action's embedded MegaloScopeArgument body, inlined here. MCC-only;
    not used by any real fixture this project has seen."""

    node: Literal["inline"] = "inline"
    body: "list[EngineStatement]" = Field(default_factory=list)


class EngineForEachBlock(BaseModel):
    """A "Run Nested Trigger" action whose target is inlined here and whose own block_type is one
    of the for_each_* loop kinds -- the one genuine looping construct in Megalo script."""

    node: Literal["for_each"] = "for_each"
    block_type: str  # TriggerBlockType enum member name, e.g. "for_each_player"
    forge_label_name: str | None = None  # only set for for_each_object_with_label
    body: "list[EngineStatement]" = Field(default_factory=list)


class EngineTriggerCallStatement(BaseModel):
    """A "Run Nested Trigger" action whose target is a real, multiply-called (or unused, dead)
    subroutine -- rendered by the real decompiler as a `trigger_N()` call rather than inlined.
    `trigger_index` indexes the same list `extract_triggers()` returns."""

    node: Literal["call"] = "call"
    trigger_index: int


class EngineRawStatement(BaseModel):
    """A defensive fallback for a malformed opcode graph (an out-of-range/wrongly-typed "Run
    (Inline) Nested Trigger" argument) -- mirrors the comment text CodeBlock::decompile() itself
    emits for the same cases. Never expected against a real, engine-loaded variant."""

    node: Literal["raw"] = "raw"
    text: str


EngineStatement = Union[
    EngineActionStatement,
    EngineIfStatement,
    EngineDoBlock,
    EngineInlineBlock,
    EngineForEachBlock,
    EngineTriggerCallStatement,
    EngineRawStatement,
]


class EngineTrigger(BaseModel):
    """One compiled Trigger. `block_type`/`entry_type` are TriggerBlockType/TriggerEntryType enum
    member names -- `entry_type` marks whether this runs every tick (`normal`), on a specific
    event (`on_init`/`on_local_init`/`on_host_migration`/`on_object_death`/`local`/`pregame`), or
    only when called via a "Run Nested Trigger" action elsewhere (`subroutine`). `is_function`
    marks whether THIS trigger, if referenced by some other trigger's "Run Nested Trigger" action,
    would be inlined there (False) or left as an opaque `EngineTriggerCallStatement` (True) --
    True for triggers called from more than one place, and for `subroutine`-entry-typed triggers
    nothing calls at all (see module docstring). `opcodes` is the flat, engine-native ground truth,
    unchanged from before this reconstruction existed; `body` is the nested if/do/for-each/call
    tree built from it -- both describe the same trigger, at two levels of structure."""

    index: int
    block_type: str
    entry_type: str
    is_function: bool = False
    opcodes: list[EngineOpcode] = Field(default_factory=list)
    body: "list[EngineStatement]" = Field(default_factory=list)


class EngineAst(BaseModel):
    """Just a named wrapper around ``extract_triggers()``'s own ``list[EngineTrigger]``, so it
    round-trips through ``model_dump_json()``/``model_validate_json()`` the same single-object way
    ``megalo_ast.nodes.Script`` does, rather than needing a bare-list JSON root."""

    triggers: list[EngineTrigger] = Field(default_factory=list)


for _cls in (
    EngineArgument,
    ObjectPlayerVariableDetails,
    PlayerSetDetails,
    ShapeDetails,
    WaypointIconDetails,
    MeterDetails,
    FormatStringTokenDetails,
    EngineIfStatement,
    EngineDoBlock,
    EngineInlineBlock,
    EngineForEachBlock,
    EngineTrigger,
):
    _cls.model_rebuild()


class _Ctx:
    """Threaded through every _extract_*/_build_* call below: the owning GameVariant (needed for
    .decompile()), the loaded _reachvarianttool module (so isinstance checks don't re-import it on
    every single argument), the full native Trigger list and each one's precomputed `is_function`
    flag (see _compute_is_function_flags), and `visiting` -- a plain mutable set used as a DFS
    "currently being inlined" guard so a malformed/cyclic opcode graph can't recurse forever (see
    EngineTriggerCallStatement's docstring; check_if_is_function() is designed so real scripts never
    hit this, this is defensive insurance, not expected to ever trigger against a real fixture)."""

    __slots__ = ("variant", "rvt", "triggers", "is_function", "visiting")

    def __init__(self, variant, rvt, triggers: list, is_function: list[bool]):
        self.variant = variant
        self.rvt = rvt
        self.triggers = triggers
        self.is_function = is_function
        self.visiting: set[int] = set()


def _extract_argument(ctx: _Ctx, arg) -> EngineArgument:
    rvt = ctx.rvt
    # AnyVariable/PlayerOrGroupVariable are "argument can be any of several variable kinds" wrapper
    # types (e.g. the "Compare" condition's operands, "Send Incident"'s player args) -- very common
    # in real scripts -- that hold the actually-resolved Variable on their own `.variable` field
    # rather than being a Variable themselves (confirmed directly: pybind11's polymorphic
    # downcasting matches the exact concrete C++ type, and these two genuinely derive from
    # OpcodeArgValue, not Variable).
    resolved = arg.variable if hasattr(arg, "variable") and arg.variable is not None else arg
    is_variable = isinstance(resolved, rvt.Variable)
    scope_format = which = index = None
    if is_variable:
        scope = resolved.scope
        scope_format = scope.format if scope is not None else None
        which = resolved.which
        index = resolved.index

    raw_value = None
    vector = None
    index_ref = None
    resolved_name = None
    player_set = None
    shape = None
    waypoint_icon = None
    meter = None
    object_timer_variable = None
    object_player_variable = None
    format_string = None
    inline_scope = None

    if isinstance(
        arg,
        (
            rvt.ConstBoolArgument,
            rvt.ConstSInt8Argument,
            rvt.TimerRateArgument,
            rvt.FireteamListArgument,
            rvt.IncidentArgument,
            rvt.ObjectTypeArgument,
            rvt.SoundArgument,
            rvt.VariantStringIDArgument,
            rvt.EnumArgument,
            rvt.FlagsArgument,
            rvt.IconArgument,
        ),
    ):
        raw_value = arg.value
    elif isinstance(arg, rvt.Vector3Argument):
        vector = (arg.x, arg.y, arg.z)
    elif isinstance(arg, rvt.BaseIndexArgument):  # TriggerArgument / RequisitionPaletteArgument
        index_ref = IndexReferenceDetails(name=arg.name, max=arg.max, quirk=arg.quirk.name, value=arg.value)
    elif isinstance(arg, rvt.ForgeLabelArgument):
        label = arg.value
        resolved_name = label.name.text if label is not None and label.name is not None else None
    elif isinstance(arg, rvt.PlayerTraitsArgument):
        traits = arg.value
        resolved_name = traits.name.text if traits is not None and traits.name is not None else None
    elif isinstance(arg, rvt.PlayerSetArgument):
        player_set = PlayerSetDetails(
            set_type=arg.set_type.name,
            player=_extract_argument(ctx, arg.player),
            add_or_remove=_extract_argument(ctx, arg.add_or_remove),
        )
    elif isinstance(arg, rvt.ShapeArgument):
        shape = ShapeDetails(
            shape_type=arg.shape_type.name,
            radius=_extract_argument(ctx, arg.radius),
            length=_extract_argument(ctx, arg.length),
            top=_extract_argument(ctx, arg.top),
            bottom=_extract_argument(ctx, arg.bottom),
        )
    elif isinstance(arg, rvt.WaypointIconArgument):
        waypoint_icon = WaypointIconDetails(icon=arg.icon, number=_extract_argument(ctx, arg.number))
    elif isinstance(arg, rvt.MeterParametersArgument):
        meter = MeterDetails(
            type=arg.type.name,
            timer=_extract_argument(ctx, arg.timer),
            numerator=_extract_argument(ctx, arg.numerator),
            denominator=_extract_argument(ctx, arg.denominator),
        )
    elif isinstance(arg, rvt.ObjectTimerVariableArgument):
        object_timer_variable = ObjectTimerVariableDetails(
            base_scope=int(arg.base_scope),
            base_type=int(arg.base_type),
            index=arg.index,
            is_none=arg.is_none(),
        )
    elif isinstance(arg, rvt.ObjectPlayerVariableArgument):
        object_player_variable = ObjectPlayerVariableDetails(
            object=_extract_argument(ctx, arg.object),
            player_index=arg.player_index,
        )
    elif isinstance(arg, rvt.FormatStringArgument):  # also covers FormatStringPersistentArgument
        tokens = []
        for i in range(arg.token_count):
            token = arg.token(i)
            tokens.append(
                FormatStringTokenDetails(
                    type=token.type.name,
                    value=_extract_argument(ctx, token.value) if token.value is not None else None,
                )
            )
        string = arg.string
        format_string = FormatStringDetails(
            persistent=arg.persistent,
            string_text=string.text if string is not None else None,
            token_count=arg.token_count,
            tokens=tokens,
        )
    elif isinstance(arg, rvt.MegaloScopeArgument):
        block = arg.data
        opcodes_native = [block.opcode(k) for k in range(block.opcode_count)]
        inline_scope = _build_statements(ctx, opcodes_native, 0, len(opcodes_native))

    return EngineArgument(
        text=arg.decompile(ctx.variant),
        description=arg.to_string(),
        variable_type=arg.get_variable_type().name,
        is_variable=is_variable,
        scope_format=scope_format,
        which=which,
        index=index,
        argument_type=type(arg).__name__,
        raw_value=raw_value,
        vector=vector,
        index_ref=index_ref,
        resolved_name=resolved_name,
        player_set=player_set,
        shape=shape,
        waypoint_icon=waypoint_icon,
        meter=meter,
        object_timer_variable=object_timer_variable,
        object_player_variable=object_player_variable,
        format_string=format_string,
        inline_scope=inline_scope,
    )


def _extract_opcode(ctx: _Ctx, op) -> EngineOpcode:
    rvt = ctx.rvt
    is_condition = isinstance(op, rvt.Condition)
    function = op.function
    return EngineOpcode(
        kind="condition" if is_condition else "action",
        function_name=function.name if function is not None else "",
        function_desc=function.desc if function is not None else "",
        mapping_type=function.mapping.type.name if function is not None else "none",
        text=op.decompile(ctx.variant),
        description=op.to_string(),
        inverted=op.inverted if is_condition else None,
        or_group=op.or_group if is_condition else None,
        gated_action_index=op.action if is_condition else None,
        arguments=[_extract_argument(ctx, op.argument(i)) for i in range(op.argument_count)],
    )


def _build_statements(ctx: _Ctx, opcodes_native: list, start: int, end: int) -> list[EngineStatement]:
    """Direct port of CodeBlock::decompile()'s block-reconstruction walk (code_block.cpp) -- see
    module docstring for the key, easy-to-get-wrong fact this encodes: once a condition run opens
    an if-level, EVERYTHING remaining in opcodes_native[start:end] becomes that if's body,
    recursively -- not just the opcodes up to the next condition run."""
    rvt = ctx.rvt
    statements: list[EngineStatement] = []
    i = start
    while i < end:
        op = opcodes_native[i]
        if isinstance(op, rvt.Condition):
            run = [op]
            j = i + 1
            while j < end and isinstance(opcodes_native[j], rvt.Condition):
                run.append(opcodes_native[j])
                j += 1
            body = _build_statements(ctx, opcodes_native, j, end)
            statements.append(
                EngineIfStatement(conditions=[_extract_opcode(ctx, c) for c in run], body=body)
            )
            return statements
        statements.extend(_build_action_statements(ctx, op))
        i += 1
    return statements


def _build_action_statements(ctx: _Ctx, op) -> list[EngineStatement]:
    """Handles the two block-forming action kinds (Run Nested Trigger / Run Inline Nested Trigger);
    everything else is a plain EngineActionStatement leaf. Returns a LIST, not a single statement,
    because an inlined target whose own first opcode is a Condition is SPLICED directly into the
    caller with no do/for-each wrapper (Trigger::decompile()'s `trigger_is_if_block` handling,
    code_block.cpp's `is_if_statement` for the inline-trigger case) -- the caller's while-loop
    extends by whatever this returns."""
    rvt = ctx.rvt
    function = op.function
    fn_name = function.name if function is not None else None

    if fn_name == "Run Nested Trigger":
        if op.argument_count == 0:
            return [EngineRawStatement(text='invalid "Run Nested Trigger" opcode (no argument)')]
        idx_arg = op.argument(0)
        if not isinstance(idx_arg, rvt.TriggerArgument):
            return [EngineRawStatement(text='invalid "Run Nested Trigger" opcode (unexpected argument type)')]
        target_index = idx_arg.value
        if not (0 <= target_index < len(ctx.triggers)):
            return [EngineRawStatement(text=f"execute nested trigger with invalid index {target_index}")]
        if ctx.is_function[target_index] or target_index in ctx.visiting:
            return [EngineTriggerCallStatement(trigger_index=target_index)]
        target = ctx.triggers[target_index]
        count = target.opcode_count
        ctx.visiting.add(target_index)
        try:
            body = _build_statements(ctx, [target.opcode(k) for k in range(count)], 0, count)
        finally:
            ctx.visiting.discard(target_index)
        block_type = target.block_type.name
        if block_type == "normal":
            if count > 0 and isinstance(target.opcode(0), rvt.Condition):
                return body  # spliced directly, no wrapper
            return [EngineDoBlock(body=body)]
        label_name = None
        if block_type == "for_each_object_with_label":
            label = target.forge_label
            if label is not None and label.name is not None:
                label_name = label.name.text
        return [EngineForEachBlock(block_type=block_type, forge_label_name=label_name, body=body)]

    if fn_name == "Run Inline Nested Trigger":
        if op.argument_count == 0:
            return [EngineRawStatement(text='invalid "Run Inline Nested Trigger" opcode (no argument)')]
        scope = op.argument(0)
        if not isinstance(scope, rvt.MegaloScopeArgument):
            return [EngineRawStatement(text='invalid "Run Inline Nested Trigger" opcode (unexpected argument type)')]
        block = scope.data
        count = block.opcode_count
        body = _build_statements(ctx, [block.opcode(k) for k in range(count)], 0, count)
        if count > 0 and isinstance(block.opcode(0), rvt.Condition):
            return body  # spliced directly, no wrapper
        return [EngineInlineBlock(body=body)]

    return [EngineActionStatement(opcode=_extract_opcode(ctx, op))]


def _iter_run_nested_trigger_targets(rvt, codeblock):
    """Port of TriggerDecompileState::setup_callees's recursive walk (trigger.cpp) -- yields the
    target trigger index of every "Run Nested Trigger" action reachable from codeblock, including
    ones nested inside "Run Inline Trigger" (MegaloScope) argument bodies (setup_callees recurses
    into those too, so a trigger reached only through an inline scope still counts as a real
    callee/caller relationship for is_function purposes)."""
    for i in range(codeblock.opcode_count):
        op = codeblock.opcode(i)
        if not isinstance(op, rvt.Action):
            continue
        function = op.function
        fn_name = function.name if function is not None else None
        if fn_name == "Run Inline Nested Trigger":
            if op.argument_count:
                scope = op.argument(0)
                if isinstance(scope, rvt.MegaloScopeArgument):
                    yield from _iter_run_nested_trigger_targets(rvt, scope.data)
            continue
        if fn_name != "Run Nested Trigger" or not op.argument_count:
            continue
        idx_arg = op.argument(0)
        if isinstance(idx_arg, rvt.TriggerArgument):
            yield idx_arg.value


def _compute_is_function_flags(rvt, triggers: list) -> list[bool]:
    """Python port of TriggerDecompileState::setup_callees()/check_if_is_function() (trigger.cpp) --
    needed because the engine only computes this transiently inside Decompiler::decompile() and
    clears it again before returning (confirmed by reading decompiler.cpp's Decompiler::decompile()
    end to end -- the very last thing it does is call triggers[i].decompile_state.clear() for every
    trigger), so it can't just be read off an already-loaded Trigger from Python. Mirrors the C++
    exactly, including running trigger-by-trigger in index order so later triggers' `any_func`
    checks see earlier triggers' already-computed flags, same as the C++'s single shared array."""
    n = len(triggers)
    callers: list[list[int]] = [[] for _ in range(n)]
    callees: list[list[int]] = [[] for _ in range(n)]
    for i, trig in enumerate(triggers):
        for target in _iter_run_nested_trigger_targets(rvt, trig):
            if 0 <= target < n:
                callees[i].append(target)
                callers[target].append(i)

    def full_callee_stack(root: int) -> tuple[set[int], set[int]]:
        entries: set[int] = set()
        recursing: set[int] = set()

        def visit(node: int, stack: tuple[int, ...]) -> None:
            if node in stack:
                recursing.add(node)
                return
            if node in entries:
                return
            entries.add(node)
            stack = stack + (node,)
            for callee in callees[node]:
                visit(callee, stack)

        visit(root, ())
        return entries, recursing

    is_function = [False] * n
    for i, trig in enumerate(triggers):
        if not callers[i]:
            # Never called from anywhere: normal for a top-level trigger, but an unused
            # user-defined subroutine still gets flagged so it doesn't silently vanish.
            if trig.entry_type == rvt.TriggerEntryType.subroutine:
                is_function[i] = True
            continue
        if len(callers[i]) > 1:
            is_function[i] = True
            continue
        entries, recursing = full_callee_stack(i)
        if recursing:
            all_solo = all(len(callers[s]) <= 1 for s in entries)
            any_func = any(is_function[s] for s in entries)
            if all_solo and not any_func:
                is_function[i] = True
    return is_function


def _extract_trigger(ctx: _Ctx, index: int, trigger) -> EngineTrigger:
    ctx.visiting.clear()
    ctx.visiting.add(index)
    opcodes_native = [trigger.opcode(j) for j in range(trigger.opcode_count)]
    return EngineTrigger(
        index=index,
        block_type=trigger.block_type.name,
        entry_type=trigger.entry_type.name,
        is_function=ctx.is_function[index],
        opcodes=[_extract_opcode(ctx, op) for op in opcodes_native],
        body=_build_statements(ctx, opcodes_native, 0, len(opcodes_native)),
    )


def extract_triggers(variant) -> list[EngineTrigger]:
    """Builds the real, engine-verified trigger/opcode/argument graph from an already-loaded
    ``_reachvarianttool.GameVariant`` -- see this module's own docstring. ``variant.multiplayer``
    must not be ``None`` (raises ``AttributeError`` otherwise -- a Firefight variant has no Megalo
    script content to extract here)."""
    from .. import rvt_bridge

    rvt = rvt_bridge.get_rvt()
    mp = variant.multiplayer
    triggers_native = [mp.trigger(i) for i in range(mp.trigger_count)]
    is_function = _compute_is_function_flags(rvt, triggers_native)
    ctx = _Ctx(variant, rvt, triggers_native, is_function)
    return [_extract_trigger(ctx, i, trig) for i, trig in enumerate(triggers_native)]
