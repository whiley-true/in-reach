"""The constants a script file sees: ``${NAME}`` values, and where they come from.

A file's ``${...}`` placeholders are filled from, in order of precedence (``TO_IMPLEMENT`` §4.5):

1. a **module parameter**, in that module's own files: the value the importing ``[[modules]]`` entry gives, or
   the parameter's ``default``;
2. the **active env** (``script/env/<name>.env``);
3. ``project.toml``'s ``[constants]``.

The design's text lists ``project.toml`` before the env, but its own example has ``PHASE_TIMER = 6`` in
``project.toml`` and ``PHASE_TIMER=2`` in ``dev.env`` -- the point of an env is to change a value between a
dev and a release build, which can't work if ``project.toml`` wins. So ``[constants]`` are the *defaults*, and a
env overrides them.

Values are raw text, exactly as in an env file: ``6``, ``-100%``, ``hill_label``, ``"hill"`` (see
:func:`in_reach.app.script_preprocess.check_value`). A TOML integer is that number; a TOML string is the text
itself, and ``"${NAME}"`` means "the current value of the constant NAME".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from in_reach.app import script_preprocess

from .manifests import ParamSpec, Scalar

_WHOLE_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
#: ``[params]`` type -> the kind :func:`script_preprocess.value_kind` reports for a value of it.
_KIND_OF_PARAM = {"number": "int", "percent": "percent", "name": "name", "string": "string"}


@dataclass(frozen=True)
class ConstantProblem:
    """Something wrong with one value. ``source`` says whose value it was, so the loader can point at the right
    file: ``"importer"`` (the ``[[modules]]`` entry, or a missing one) or ``"default"`` (the module's own
    ``[params]``), ``"project"`` (``[constants]``)."""

    source: Literal["importer", "default", "project"]
    name: str
    code: str
    message: str


def _text(value: Scalar) -> str:
    return str(value) if isinstance(value, int) else value


def resolve_value(value: Scalar, known: dict[str, str]) -> str:
    """``value`` as constant text, with a ``"${NAME}"`` looked up in ``known``.

    Raises:
        KeyError: it names a constant that isn't in ``known``.
        script_preprocess.PreprocessError: it isn't an allowed constant value.
    """
    text = _text(value)
    placeholder = _WHOLE_PLACEHOLDER.fullmatch(text)
    if placeholder:
        text = known[placeholder[1]]
    return text


def _follow(name: str, raw: dict[str, str]) -> str:
    """The text of ``raw[name]``, following ``"${OTHER}"`` references through ``raw``.

    Raises:
        KeyError: a reference to a constant that isn't in ``raw``.
        RecursionError: the references go round in a circle.
    """
    seen = {name}
    text = raw[name]
    while (placeholder := _WHOLE_PLACEHOLDER.fullmatch(text)) is not None:
        target = placeholder[1]
        if target in seen:
            raise RecursionError(target)
        seen.add(target)
        text = raw[target]
    return text


def base_constants(
    project: dict[str, Scalar], env: script_preprocess.Env | None
) -> tuple[dict[str, str], list[ConstantProblem]]:
    """The constants every file sees before module parameters: ``project`` (``[constants]``) as defaults, the
    ``env``'s values over them -- and a constant defined as ``"${OTHER}"`` follows OTHER's *final* value, so a
    env that changes OTHER changes it too. Returns the constants and a problem for each ``[constants]``
    value that isn't usable (which is then left out); a bad default the env overrides is not a problem."""
    raw: dict[str, str] = {}
    problems: list[ConstantProblem] = []
    overridden = set(env.constants) if env is not None else set()
    for name, value in project.items():
        if _NAME.fullmatch(name):
            raw[name] = _text(value)
        else:
            problems.append(ConstantProblem("project", name, "constant-name", f"{name!r} isn't a valid constant name"))
    if env is not None:
        raw.update(env.constants)

    constants: dict[str, str] = {}
    for name in raw:
        try:
            text = _follow(name, raw)
            script_preprocess.check_value(name, text)
        except (KeyError, RecursionError, script_preprocess.PreprocessError) as exc:
            if name in overridden:
                continue
            if isinstance(exc, KeyError):
                problem = ConstantProblem("project", name, "constant-undefined", f"${{{exc.args[0]}}} isn't a constant")
            elif isinstance(exc, RecursionError):
                problem = ConstantProblem("project", name, "constant-cycle", f"{name} is defined in terms of itself")
            else:
                problem = ConstantProblem("project", name, "constant-value", exc.message)
            problems.append(problem)
        else:
            constants[name] = text
    return constants, problems


def module_constants(
    base: dict[str, str], specs: dict[str, ParamSpec], given: dict[str, Scalar]
) -> tuple[dict[str, str], list[ConstantProblem]]:
    """``base`` plus one constant per parameter of a module: what the importer ``given`` it, else the parameter's
    default. A parameter may refer to a base constant (``"${SCORE_INTERVAL}"``) but not to another parameter.
    Returns the constants and a problem for each parameter that is unknown, missing, or the wrong type."""
    constants = dict(base)
    problems: list[ConstantProblem] = []

    for name in given:
        if name not in specs:
            problems.append(ConstantProblem("importer", name, "param-unknown", f"this module has no parameter {name!r}"))

    for name, spec in specs.items():
        if not _NAME.fullmatch(name):
            problems.append(ConstantProblem("default", name, "param-name", f"{name!r} isn't a valid parameter name"))
            continue
        if name in given:
            source, raw = "importer", given[name]
        elif spec.default is not None:
            source, raw = "default", spec.default
        else:
            problems.append(ConstantProblem("importer", name, "param-missing", f"parameter {name!r} has no default, so it must be set"))
            continue
        try:
            text = resolve_value(raw, base)
            script_preprocess.check_value(name, text)
        except KeyError as exc:
            problems.append(ConstantProblem(source, name, "param-undefined", f"${{{exc.args[0]}}} isn't a constant of this project or env"))
            continue
        except script_preprocess.PreprocessError as exc:
            problems.append(ConstantProblem(source, name, "param-value", exc.message))
            continue
        if script_preprocess.value_kind(text) != _KIND_OF_PARAM[spec.type]:
            problems.append(ConstantProblem(source, name, "param-type", f"parameter {name!r} is a {spec.type}, but its value is {text}"))
            continue
        constants[name] = text
    return constants, problems
