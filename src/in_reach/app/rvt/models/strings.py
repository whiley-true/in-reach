"""Pydantic schema for a project's edit/settings/strings.json -- the shape
strings_io.extract_strings() already produces, formalized here so it has something to validate
against before strings_writer.apply_strings() applies an edit onto a real variant (compile.py's
pipeline), and so a real JSON Schema can be generated for it (schema_io.dump_json_schema()) for
VS Code's built-in JSON validation.

Ported from refactor/mide/models/strings.py near-verbatim. That version's docstring noted it
wasn't used by the read/extraction path, only the write/apply path, of a project (mide) that never
actually applied an edited strings.json back onto a real .bin -- inreach's strings_writer.py does
exactly that (see its own module docstring), so this model backs both directions here: extraction
still returns a plain dict (extract_strings() is unchanged), and strings_writer.apply_strings()
still consumes that same plain dict shape by key rather than a model instance (see its own
docstring for why) -- this model only validates an on-disk strings.json before that dict is handed
off, and generates the JSON Schema.

Per-language values are `None` when that language isn't saved at all, `""` when it's saved as a
deliberately empty string -- see strings_io.py's module docstring for the full explanation
(ReachString.has_content() vs get_content()).

LocalizedText also accepts a bare string as shorthand for {"english": <that string>} -- the same
"English is the convenience default" convention bindings.cpp's own ReachString.text/TeamData.name
properties use. Without this, a hand-editor has no way to know a team/meta name field wants a
per-language dict rather than a plain string -- most edits only care about English and shouldn't
need to learn the full per-language shape just to set one string.
"""
from typing import Annotated

from pydantic import BaseModel, BeforeValidator


def _coerce_localized_text(value):
    if isinstance(value, str):
        return {"english": value}
    return value


LocalizedText = Annotated[dict[str, str | None], BeforeValidator(_coerce_localized_text)]


class StringTableEntry(BaseModel):
    index: int
    text: LocalizedText


class TeamNameEntry(BaseModel):
    index: int
    name: LocalizedText | None


class StringsMeta(BaseModel):
    name: list[StringTableEntry]
    description: list[StringTableEntry]
    category: list[StringTableEntry]


class StringsDocument(BaseModel):
    meta: StringsMeta
    teams: list[TeamNameEntry]
    script_strings: list[StringTableEntry]
