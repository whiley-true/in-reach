"""Engine resources declared in code: trait sets, options and widgets (``TO_IMPLEMENT`` §4.4, §6 step 5).

``-- @trait t_freeze { movement_speed = "..." }`` in a module becomes an entry in ``settings/script_settings.json`` and
an alias (``alias t_freeze = script_traits[0]``) in the built script. Decision 2 in ``next_steps.md`` governs how:

* **Modules write their own resources, and hand-made entries are never moved.** An entry you added in RVT (or by
  hand) keeps its index; declared resources are appended after everything already there.
* **Your edits win.** A resource keeps the index it was given, and its entry is refreshed from the module only
  while it is still exactly what the linker last wrote (a digest of it is recorded in ``link_map.json``); once you
  have changed it, it is left alone.
* **Nothing is dropped.** A resource whose declaration is deleted leaves its entry where it was.

Forge labels are not written here: a label is created when the compiler first meets its name, and
:mod:`in_reach.app.rvt.settings_writer` records it afterwards. ``@label`` only supplies the name to substitute.

``name`` and ``desc`` (of a trait set, and of an option) are what the game shows. They live in the variant's strings table,
not in the settings entry, so :mod:`in_reach.app.rvt.resource_text` writes them there (and into ``settings/strings.json``)
at compile time -- with no ``name`` a trait set is called by its alias and a toggle's values "Off" and "On". The copy in
``script_settings.json`` is only a mirror, which a round trip through the ``.bin`` rewrites, so it is left out of the digest
that decides whether an entry was edited, and a refresh from the module keeps whatever is there.

Field names: an ``@trait``'s keys are ``<category>_<field>`` (``movement_speed``, ``defense_damage_resist``), the
categories and fields of :class:`~in_reach.app.rvt.models.traits.PlayerTraits`; ``name`` and ``desc`` are the entry's
own. An ``@option`` is ``type = "toggle"`` (``default`` 0 or 1) or ``type = "range"`` (``min``, ``max``, ``default``).
A ``@widget`` takes ``position``, a number 0-11 -- the engine has no names for them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError

from in_reach.app.rvt.megalo_ast.annotations import LabelAnnotation, OptionAnnotation, TraitAnnotation, WidgetAnnotation
from in_reach.app.rvt.megalo_compiler import _SCRIPT_TABLES
from in_reach.app.rvt.models.script_settings import (
    ScriptedHUDWidget,
    ScriptedOption,
    ScriptedOptionValue,
    ScriptedPlayerTraits,
    ScriptSettings,
)
from in_reach.app.rvt.models.traits import PlayerTraits

from .diagnostics import ProjectDiagnostic
from .model import Declared

_TRAIT_CATEGORIES = ("defense", "offense", "movement", "appearance", "sensors")
#: kind -> (ScriptSettings list field, alias prefix, the compiler's table name for its capacity)
_KINDS = {
    "trait": ("scripted_player_traits", "script_traits", "script_traits"),
    "option": ("scripted_options", "script_option", "script_option"),
    "widget": ("scripted_hud_widgets", "script_widget", "script_widget"),
}


@dataclass(frozen=True)
class ResourceInfo:
    kind: str
    index: int
    owner: str
    digest: str
    # The text the declaration asked for, which the compile writes into the variant's strings table (``resource_text``):
    # ``label``/``note`` are an explicit ``name``/``desc``; ``values`` the names of an option's enum values.
    label: str | None = None
    note: str | None = None
    values: tuple[str, ...] = ()

    @property
    def alias_value(self) -> str:
        return f"{_KINDS[self.kind][1]}[{self.index}]"


@dataclass
class ResourcePlan:
    settings: ScriptSettings
    resources: dict[str, ResourceInfo] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)  # alias name -> the label's text
    changed: bool = False
    diagnostics: list[ProjectDiagnostic] = field(default_factory=list)


class _Invalid(Exception):
    pass


DIGEST_VERSION = "2:"


def _without_text(value):
    """``value`` with every ``name`` and ``desc`` key removed, at any depth."""
    if isinstance(value, dict):
        return {k: _without_text(v) for k, v in value.items() if k not in ("name", "desc")}
    if isinstance(value, list):
        return [_without_text(v) for v in value]
    return value


def _keeping_text(fresh: BaseModel, current: BaseModel) -> BaseModel:
    """``fresh`` (built from the declaration) but with ``current``'s display text: it is the game's, or the user's, to
    change, not the module's to reset -- and a name blanked by a round trip through the ``.bin`` stays as it was."""
    keep = {field: getattr(current, field) for field in ("name", "desc") if hasattr(current, field)}
    return fresh.model_copy(update=keep)


def digest(entry: BaseModel) -> str:
    """A fingerprint of what a settings entry does in the game variant. The display text (``name``, ``desc``) is left
    out: the compiler never writes it (it is looked up from the strings table when settings are extracted, and comes
    back blank for an entry the linker made), so a round trip through the ``.bin`` -- Launch RVT, a resync -- changes
    it without anyone having edited the entry, and counting it would make every such entry look hand-edited."""
    dumped = _without_text(entry.model_dump(mode="json"))
    if dumped.get("is_range"):
        dumped.pop("values", None)  # a range option's enum values mean nothing: a saved-and-reloaded one has none
    text = json.dumps(dumped, sort_keys=True)
    return DIGEST_VERSION + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# -- annotation fields -> settings entries --------------------------------------------------------------


def _split(fields: dict) -> tuple[dict, str | None, str]:
    rest = dict(fields)
    name = rest.pop("name", None)
    desc = rest.pop("desc", "")
    return rest, (str(name) if name is not None else None), str(desc)


def _trait_field(key: str) -> tuple[str, str]:
    """``movement_speed`` or plain ``speed`` (when only one category has a field of that name) -> ``("movement", "speed")``."""
    category, _, attribute = key.partition("_")
    if category in _TRAIT_CATEGORIES and attribute in _category_fields(category):
        return category, attribute
    owners = [c for c in _TRAIT_CATEGORIES if key in _category_fields(c)]
    if len(owners) == 1:
        return owners[0], key
    if len(owners) > 1:
        raise _Invalid(f"{key!r} is a field of more than one category ({', '.join(owners)}); write <category>_{key}")
    raise _Invalid(f"{key!r} isn't a trait field; write <category>_<field>, like movement_speed (categories: {', '.join(_TRAIT_CATEGORIES)})")


def _category_fields(category: str) -> set[str]:
    return set(PlayerTraits.model_fields[category].annotation.model_fields)


def _trait_entry(name: str, fields: dict) -> ScriptedPlayerTraits:
    rest, title, desc = _split(fields)
    nested: dict[str, dict] = {}
    for key, value in rest.items():
        category, attribute = _trait_field(key)
        nested.setdefault(category, {})[attribute] = value
    try:
        traits = PlayerTraits.model_validate(nested)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise _Invalid(f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}") from None
    return ScriptedPlayerTraits(name=title or name, desc=desc, traits=traits)


def _option_entry(name: str, fields: dict) -> ScriptedOption:
    rest, title, desc = _split(fields)
    kind = rest.pop("type", None)
    label = title or name
    try:
        if kind == "toggle":
            default = int(rest.pop("default", 0))
            _no_extras(rest, "toggle")
            if default not in (0, 1):
                raise _Invalid("a toggle's default is 0 or 1")
            return ScriptedOption(
                name=label, desc=desc, is_range=False,
                values=[ScriptedOptionValue(name="Off", value=0), ScriptedOptionValue(name="On", value=1)],
                default_value_index=default, current_value_index=default,
            )
        if kind == "range":
            try:
                low, high, default = int(rest.pop("min")), int(rest.pop("max")), int(rest.pop("default"))
            except KeyError as exc:
                raise _Invalid(f"a range option needs min, max and default (missing {exc.args[0]})") from None
            _no_extras(rest, "range")
            if not low <= default <= high:
                raise _Invalid(f"the default {default} isn't between min {low} and max {high}")
            return ScriptedOption(
                name=label, desc=desc, is_range=True, values=[ScriptedOptionValue(value=0)],  # a range option keeps one value
                range_min=ScriptedOptionValue(value=low), range_max=ScriptedOptionValue(value=high),
                range_default=ScriptedOptionValue(value=default), range_current=default,
            )
    except (ValueError, TypeError, ValidationError) as exc:
        raise _Invalid(f"invalid option value: {exc}") from None
    raise _Invalid(f"an option's type is toggle or range, not {kind!r}")


def _widget_entry(name: str, fields: dict) -> ScriptedHUDWidget:
    rest, _, _ = _split(fields)
    position = rest.pop("position", 0)
    _no_extras(rest, "widget")
    if isinstance(position, bool) or not isinstance(position, int) or not 0 <= position <= 11:
        raise _Invalid(f"a widget's position is a number from 0 to 11 (the engine has no names for them), not {position!r}")
    return ScriptedHUDWidget(position=position)


def _no_extras(rest: dict, what: str) -> None:
    if rest:
        raise _Invalid(f"unknown field {next(iter(rest))!r} for a {what}")


_BUILDERS = {"trait": _trait_entry, "option": _option_entry, "widget": _widget_entry}


# -- planning -------------------------------------------------------------------------------------------


def plan_resources(
    declared: list[Declared], current: ScriptSettings, previous: dict[str, dict]
) -> ResourcePlan:
    """Works out ``settings/script_settings.json``'s new contents and every resource's index.

    ``current`` is the settings as they are on disk; ``previous`` is the ``resources`` table of the last link's
    ``link_map.json`` (``{}`` for a first link), which says which entries the linker wrote and what they looked
    like when it did."""
    lists: dict[str, list] = {kind: list(getattr(current, attr)) for kind, (attr, _, _) in _KINDS.items()}
    plan = ResourcePlan(settings=current)
    seen: set[str] = set()

    for item in declared:
        annotation = item.annotation
        if isinstance(annotation, LabelAnnotation):
            plan.labels.setdefault(annotation.name, annotation.text)
            continue
        if not isinstance(annotation, (TraitAnnotation, OptionAnnotation, WidgetAnnotation)) or annotation.name in seen:
            continue  # a duplicate name is IR006's to report
        seen.add(annotation.name)
        kind = annotation.kind
        line = annotation.span.start_line
        try:
            entry = _BUILDERS[kind](annotation.name, dict(annotation.fields))
        except _Invalid as exc:
            plan.diagnostics.append(
                ProjectDiagnostic(severity="error", code="resource-invalid", message=f"{annotation.name}: {exc}", file=item.file, line=line)
            )
            continue

        entries = lists[kind]
        before = previous.get(annotation.name)
        if before and before.get("kind") == kind and 0 <= before.get("index", -1) < len(entries):
            index = before["index"]
            recorded_before = before.get("digest", "")
            # A digest without the version prefix was written before display text was left out of it: it can't be
            # compared with today's, so that entry is adopted (refreshed from its declaration) once, and recorded in
            # the new form from then on.
            untouched = not recorded_before.startswith(DIGEST_VERSION) or digest(entries[index]) == recorded_before
            if untouched:
                entry = _keeping_text(entry, entries[index])
                entries[index] = entry
                recorded = digest(entry)
            else:
                # Edited since the linker wrote it: the edit wins. What is recorded stays *what the linker wrote*,
                # not the edit -- otherwise the edit would look like the linker's own output next time and be
                # overwritten by the module's version.
                entry = entries[index]
                recorded = before["digest"]
        else:
            capacity = _SCRIPT_TABLES[_KINDS[kind][2]][2]
            if len(entries) >= capacity:
                plan.diagnostics.append(
                    ProjectDiagnostic(
                        severity="error", code="resource-full",
                        message=f"a variant has at most {capacity} {kind}s and {annotation.name} would be number {len(entries) + 1}",
                        file=item.file, line=line,
                    )
                )
                continue
            entries.append(entry)
            index = len(entries) - 1
            recorded = digest(entry)
        _, label, note = _split(dict(annotation.fields))
        value_names = tuple(v.name for v in entry.values) if kind == "option" and not entry.is_range else ()
        plan.resources[annotation.name] = ResourceInfo(
            kind=kind, index=index, owner=item.owner, digest=recorded, label=label, note=note or None, values=value_names
        )

    updates = {attr: lists[kind] for kind, (attr, _, _) in _KINDS.items() if lists[kind] != list(getattr(current, attr))}
    if updates:
        plan.settings = current.model_copy(update=updates)
        plan.changed = True
    return plan
