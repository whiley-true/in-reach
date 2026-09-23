"""``script/project.toml`` and ``script/modules/<name>/module.toml``: their models, and reading them.

The shapes come from ``TO_IMPLEMENT`` §5, minus what ``next_steps.md`` decision 1 dropped: a module's storage
needs are *inferred from its ``@`` annotations*, so there is no ``[requires]`` (and no ``[provides]``) table.
A manifest keeps only what code can't say -- the module's name and version, its ``[order]``, its ``[params]``,
the resources it shares with other modules, and tags.

:func:`read_manifest` never raises. A file that isn't valid TOML, a value of the wrong type, and a key nothing
reads each become a :class:`~in_reach.app.script_project.diagnostics.ProjectDiagnostic` with the line it is on.
Unknown keys are warnings, not errors, so a manifest written for a newer version still loads.
"""

from __future__ import annotations

import re
import tomllib
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .diagnostics import ProjectDiagnostic
from .toml_positions import locate, positions

_ModelT = TypeVar("_ModelT", bound=BaseModel)

Scalar = int | str


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


# -- project.toml ---------------------------------------------------------------------------------------


class ProjectSection(_Model):
    name: str | None = None
    dialect: Literal["mgl/1"] = "mgl/1"
    env: str | None = None  # the default env; script/env/active_env.txt (the IDE's switcher) wins
    profile: str | None = None  # what `env` was called before in-reach 0.4: still read, with a warning
    bit_impl: Literal["and", "divmod"] = "and"


class BlocksSection(_Model):
    order: list[str] = Field(default_factory=list)


class ModuleRef(_Model):
    """A ``[[modules]]`` entry: which module to import, and the values it is imported with."""

    name: str
    params: dict[str, Scalar] = Field(default_factory=dict)
    #: Where the module came from (``path:../shared/hill_score`` or ``git+https://host/repo.git@rev``), written by
    #: ``in-reach module add``; the files themselves are vendored into ``script/modules/<name>/`` (see :mod:`.packages`).
    source: str | None = None
    #: ``enabled = false`` keeps the module in the project without building it (see :mod:`.edit`).
    enabled: bool = True


class KindSpec(_Model):
    """How a kind of object is reached: ``["p_carrier", "label:weap_spawn", "biped"]``."""

    reached_by: list[str] = Field(default_factory=list)


class ProjectManifest(_Model):
    project: ProjectSection = Field(default_factory=ProjectSection)
    blocks: BlocksSection = Field(default_factory=BlocksSection)
    constants: dict[str, Scalar] = Field(default_factory=dict)
    pins: dict[str, str] = Field(default_factory=dict)
    modules: list[ModuleRef] = Field(default_factory=list)
    kinds: dict[str, KindSpec] = Field(default_factory=dict)
    caps: dict[str, int] = Field(default_factory=dict)


# -- module.toml ----------------------------------------------------------------------------------------


class ModuleSection(_Model):
    name: str
    version: str = "0.0.0"
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    # What a shared module says about itself (nothing here changes how it links).
    description: str = ""
    license: str = ""
    authors: list[str] = Field(default_factory=list)
    min_in_reach: str = ""  # the oldest in-reach that can build it, "0.3.0"


class OrderSection(_Model):
    """Where this module's blocks go relative to other blocks (``TO_IMPLEMENT`` §6.1): each ``after`` block comes
    before, and each ``before`` block after, every block the module contributes fragments to. ``phase`` is
    recorded and not otherwise interpreted yet."""

    after: list[str] = Field(default_factory=list)
    before: list[str] = Field(default_factory=list)
    phase: str | None = None


class ParamSpec(_Model):
    """A value an importer can set, used in the module's source as ``${name}``. ``default`` may itself be a
    ``"${CONSTANT}"``."""

    type: Literal["number", "percent", "name", "string"] = "number"
    doc: str = ""
    default: Scalar | None = None


class SharedSection(_Model):
    """Resources this module reuses if the project (another module) already provides them, by name."""

    traits: list[str] = Field(default_factory=list)
    options: list[str] = Field(default_factory=list)
    widgets: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)


class ModuleManifest(_Model):
    module: ModuleSection
    order: OrderSection = Field(default_factory=OrderSection)
    params: dict[str, ParamSpec] = Field(default_factory=dict)
    shared: SharedSection = Field(default_factory=SharedSection)
    kinds: dict[str, KindSpec] = Field(default_factory=dict)


# -- reading --------------------------------------------------------------------------------------------

# What each top-level key of a manifest may contain, for warning about anything else. A shape is
# ("any",)                 -- free-form keys (a table of constants, say);
# ("table", {keys})        -- a table with exactly these keys;
# ("array", {keys})        -- an array of tables ([[modules]]) with these keys;
# ("named", {keys})        -- a table of tables ([kinds.hill], [params.speed]), each with these keys.
_PROJECT_SCHEMA: dict[str, tuple] = {
    "project": ("table", {"name", "dialect", "env", "profile", "bit_impl"}),
    "blocks": ("table", {"order"}),
    "constants": ("any",),
    "pins": ("any",),
    "modules": ("array", {"name", "params", "source", "enabled"}),
    "kinds": ("named", {"reached_by"}),
    "caps": ("any",),
}
_MODULE_SCHEMA: dict[str, tuple] = {
    "module": ("table", {"name", "version", "summary", "tags", "features", "description", "license", "authors", "min_in_reach"}),
    "order": ("table", {"after", "before", "phase"}),
    "params": ("named", {"type", "doc", "default"}),
    "shared": ("table", {"traits", "options", "widgets", "labels"}),
    "kinds": ("named", {"reached_by"}),
}
#: Tables of the design a manifest may still carry, with why they are not read.
_DROPPED = {
    "requires": "a module's storage needs are inferred from its `@` annotations, so [requires] is no longer read",
    "provides": "what a module provides is inferred from its `@` annotations and fragments, so [provides] is no longer read",
}
_TOML_ERROR_POSITION = re.compile(r"\(at line (\d+), column (\d+)\)")


def _unknown_keys(raw: dict[str, Any], schema: dict[str, tuple]) -> list[tuple[tuple[str | int, ...], str]]:
    """Keys in ``raw`` that ``schema`` doesn't know, as ``(path to the table holding it, key)``."""
    found: list[tuple[tuple[str | int, ...], str]] = []
    for key, value in raw.items():
        shape = schema.get(key)
        if shape is None:
            found.append(((), key))
            continue
        kind = shape[0]
        if kind == "table" and isinstance(value, dict):
            found.extend(((key,), name) for name in value if name not in shape[1])
        elif kind == "array" and isinstance(value, list):
            for index, entry in enumerate(value):
                if isinstance(entry, dict):
                    found.extend(((key, index), name) for name in entry if name not in shape[1])
        elif kind == "named" and isinstance(value, dict):
            for entry_name, entry in value.items():
                if isinstance(entry, dict):
                    found.extend(((key, entry_name), name) for name in entry if name not in shape[1])
    return found


def read_manifest(
    text: str, model: type[_ModelT], file: str
) -> tuple[_ModelT | None, list[ProjectDiagnostic]]:
    """Parses ``text`` (the content of ``file``) as a ``model`` manifest.

    Returns ``(manifest, diagnostics)``; the manifest is ``None`` if the file couldn't be used at all."""
    diagnostics: list[ProjectDiagnostic] = []

    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        match = _TOML_ERROR_POSITION.search(str(exc))
        line, col = (int(match[1]), int(match[2]) - 1) if match else (0, 0)
        message = _TOML_ERROR_POSITION.sub("", str(exc)).strip()
        return None, [ProjectDiagnostic(severity="error", code="toml-syntax", message=message, file=file, line=line, col=col)]

    where = positions(text)
    schema = _PROJECT_SCHEMA if model is ProjectManifest else _MODULE_SCHEMA

    for path, key in _unknown_keys(raw, schema):
        line, col = locate(where, (*path, key))
        if not path and key in _DROPPED and model is ModuleManifest:
            message, code = _DROPPED[key], "manifest-dropped-table"
        else:
            where_text = ".".join(str(p) for p in path if isinstance(p, str))
            message, code = f"unknown key {key!r}{f' in [{where_text}]' if where_text else ''} (ignored)", "manifest-unknown-key"
        diagnostics.append(ProjectDiagnostic(severity="warning", code=code, message=message, file=file, line=line, col=col))

    try:
        manifest = model.model_validate(raw)
    except ValidationError as exc:
        for error in exc.errors():
            loc = tuple(part for part in error["loc"] if isinstance(part, (str, int)))
            line, col = locate(where, loc)
            name = ".".join(str(p) for p in loc) or "the file"
            missing = error["type"] == "missing"
            diagnostics.append(
                ProjectDiagnostic(
                    severity="error",
                    code="manifest-missing-key" if missing else "manifest-invalid-value",
                    message=f"{name}: {'is required' if missing else error['msg']}",
                    file=file,
                    line=line,
                    col=col,
                )
            )
        return None, diagnostics
    return manifest, diagnostics
