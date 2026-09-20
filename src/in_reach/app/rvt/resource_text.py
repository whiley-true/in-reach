"""Display text for the trait sets and options a script project declares.

The game reads the name and description of a scripted trait set or option from the variant's *script strings* table, by
index. A trait set or option the compiler creates (``add_scripted_player_traits()``, ``add_scripted_option()``) starts out
pointing at the table's one shared empty string -- so a declared ``@trait t_fast`` would show as a blank name in game, and
setting text on that string would rename every other entry too. This gives each declared entry strings of its own.

The code owns that text: ``@trait t_fast { name = "Fast" }`` says the name is "Fast", and with no ``name`` a trait set is
called by its alias (``t_fast``) and an option's toggle values are "Off" and "On". Every build writes it, into the variant
and into ``settings/strings.json`` (see :func:`~in_reach.app.rvt.strings_writer.own_text`), overwriting what is there --
the strings of a declared entry are found by position, and a position moves when something is declared before it, so
text kept from a previous build could land on the wrong entry. To call something something else, say so in the
declaration.

Only an entry whose string is still empty is touched: a name the variant already has is never replaced. The compile always
starts from the project's frozen base variant, so every entry a project declares starts empty on every build -- which is
what makes the result the same each time.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ResourceText:
    kind: str  # "trait" | "option"
    index: int
    alias: str
    name: str | None = None  # explicit
    desc: str | None = None  # explicit
    values: tuple[str, ...] = ()  # an option's enum value names (defaults)


@dataclass
class TextAssignment:
    owned: dict[int, str] = field(default_factory=dict)  # script_strings index -> the text the code gave it


def texts_from_link_map(resources: dict) -> list[ResourceText]:
    """The declared entries of a ``link_map.json``'s ``resources`` table that have a table entry to name."""
    found = []
    for alias, entry in resources.items():
        if entry.get("kind") not in ("trait", "option"):
            continue
        text = entry.get("text", {})
        found.append(
            ResourceText(
                kind=entry["kind"], index=entry["index"], alias=alias, name=text.get("name"), desc=text.get("desc"),
                values=tuple(text.get("values", ())),
            )
        )
    return found


def _needs_string(current) -> bool:
    return current is None or current.empty()


def _give(table, owner, attribute: str, text: str, out: TextAssignment) -> None:
    if not _needs_string(getattr(owner, attribute)):
        return
    string = table.add_new()
    if string is None:
        raise ValueError(f"the variant's script strings table is full ({table.capacity}); can't name {text!r}")
    string.text = text
    setattr(owner, attribute, string)
    out.owned[len(table) - 1] = text


def assign_resource_text(mp, items: list[ResourceText]) -> TextAssignment:
    """Gives each declared trait set / option in ``items`` (already present in ``mp``) strings of its own and fills them in.

    Raises:
        ValueError: The script strings table has no room left."""
    out = TextAssignment()
    table = mp.script_strings
    for item in items:
        if item.kind == "trait":
            if item.index >= mp.scripted_player_trait_count:
                continue
            owner = mp.scripted_player_trait(item.index)
        else:
            if item.index >= mp.scripted_option_count:
                continue
            owner = mp.scripted_option(item.index)
            for position, value_name in enumerate(item.values):
                if position < owner.value_count:
                    _give(table, owner.value(position), "name", value_name, out)
        _give(table, owner, "name", item.name or item.alias, out)
        if item.desc:
            _give(table, owner, "desc", item.desc, out)
    return out
