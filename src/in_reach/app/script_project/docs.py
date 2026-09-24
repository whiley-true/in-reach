"""A script's documentation, generated from the script itself -- the same for a single file and a script project.

What it is made of:

* **notes** -- ``-- @doc`` lines, attached to what they document: the declaration just above them in their run of
  annotation lines (``-- @number g_score`` then ``-- @doc ...``; a ``@doc`` before any declaration in the run belongs to
  the first one below it), else the fragment or preamble whose header they are in, else the line of code right below
  the run, or -- when a blank line or the end of the file follows it -- the file as a whole;
* **tags** -- ``-- @tags a, b`` in a file, and a module's ``module.toml`` ``tags``; indexed, so a tag lists every
  block, module and file that carries it;
* **READMEs** -- ``script/README.md`` (the script, or the project), ``blocks/<name>.md`` beside a block file, and
  ``modules/<name>/README.md``;
* what the linker decided -- each storage name's slot, each resource's table entry, the budget, the block order and
  what fusion merged -- from the link (or, if the script doesn't link right now, the last link map written).

:func:`build_docs` gathers all of it into a :class:`Docs`; :func:`render_markdown` turns that into the overview a
person reads, and :meth:`Docs.to_dict` into the JSON a tool (or a language model) reads. :func:`write_docs` writes both
to ``build/docs/`` -- ``overview.md`` and ``overview.json`` -- touching neither when nothing changed.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from in_reach.app import new_project
from in_reach.app.rvt.megalo_ast.annotations import (
    BitfieldAnnotation,
    DocAnnotation,
    FragmentAnnotation,
    LabelAnnotation,
    OptionAnnotation,
    PreambleAnnotation,
    SeeAnnotation,
    StorageAnnotation,
    TagsAnnotation,
    TraitAnnotation,
    WidgetAnnotation,
)

from .linker import LinkResult, link, read_link_map
from .lint import see_targets
from .model import SemanticModel, build_model
from .manifests import ModuleManifest, read_manifest
from .project import BLOCKS_DIRNAME, MODULE_FILENAME, MODULES_DIRNAME, ScriptProject, SourceFile, is_linked, script_dir

DOCS_DIRNAME = "docs"
OVERVIEW_MD = "overview.md"
OVERVIEW_JSON = "overview.json"
README_FILENAME = "README.md"
#: The shape of ``overview.json``; raised when a consumer would break.
DOCS_SCHEMA = 1

_ANNOTATION_LINE = re.compile(r"^\s*--\s*@([A-Za-z][A-Za-z0-9_-]*)")
_DIRECTIVES = frozenset({"if", "else", "end"})
_DECLARING = (StorageAnnotation, BitfieldAnnotation, TraitAnnotation, OptionAnnotation, WidgetAnnotation, LabelAnnotation)


@dataclass
class Note:
    """One run of ``@doc`` lines -- an *entry*. ``kind`` is what it documents: ``"file"``, ``"name"`` (``subject`` is the
    names, comma-separated), ``"fragment"``, ``"preamble"`` or ``"code"`` (``subject`` is that line of code). ``text`` is
    Markdown, one line per ``@doc`` line (a bare ``-- @doc`` is a blank line); ``lines`` are those lines' 1-based numbers
    in ``file``, which :func:`rewrite_entry` replaces. ``details`` is the docstring's longer text, Markdown too -- kept in
    ``script/DOCSTRINGS.md`` (:data:`DOCSTRINGS_FILENAME`), not in the script, under the docstring's title."""

    text: str
    file: str
    line: int
    kind: str
    subject: str
    names: list[str] = field(default_factory=list)
    lines: list[int] = field(default_factory=list)
    details: str = ""


@dataclass
class Reference:
    """A ``@see``: what it names, where it is, and what that turned out to be (``None``: nothing in the script)."""

    target: str
    file: str
    line: int
    resolves_to: str | None


@dataclass
class FileDocs:
    path: str  # relative to script/
    owner: str  # "block:SETUP" or "module:hill_score"
    tags: list[str] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)
    see: list[Reference] = field(default_factory=list)


@dataclass
class Readme:
    path: str  # relative to script/
    text: str


@dataclass
class BlockDocs:
    name: str
    file: str | None  # None: only fragments make it
    readme: Readme | None = None
    tags: list[str] = field(default_factory=list)
    contributors: list[str] = field(default_factory=list)
    fragments: list[dict] = field(default_factory=list)  # {id, loop, file, line, doc}


@dataclass
class ModuleDocs:
    name: str
    enabled: bool
    version: str = ""
    summary: str = ""
    description: str = ""
    license: str = ""
    authors: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    readme: Readme | None = None
    blocks: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)


@dataclass
class Docs:
    mode: str  # "single" | "project"
    name: str
    env: str | None
    flags: list[str]
    linked: bool  # whether the script links right now (if not, storage/budget come from the last link)
    readme: Readme | None = None
    description: str = ""  # the documentation's own description (script/docs.json) -- not the gametype's in-game one
    #: DOCSTRINGS.md texts whose docstring is gone or was reworded: ``{note, text}`` (``note``: the title it had).
    detached: list[dict] = field(default_factory=list)
    tags: dict[str, list[str]] = field(default_factory=dict)  # tag -> "block SETUP" / "module x" / "file output.mgl"
    files: list[FileDocs] = field(default_factory=list)
    blocks: list[BlockDocs] = field(default_factory=list)
    modules: list[ModuleDocs] = field(default_factory=list)
    storage: list[dict] = field(default_factory=list)  # {name, slot, owner, kind?, doc}
    resources: list[dict] = field(default_factory=list)  # {name, kind, index, owner, text?, doc}
    budget: dict = field(default_factory=dict)
    fusion: dict = field(default_factory=dict)

    @property
    def notes(self) -> list[Note]:
        return [note for file in self.files for note in file.notes]

    def to_dict(self) -> dict:
        return {"docs_schema": DOCS_SCHEMA, **asdict(self)}


# -- gathering -------------------------------------------------------------------------------------------------


def _runs(file: SourceFile) -> list[tuple[int, int]]:
    """``(first, last)`` 1-based line ranges of consecutive annotation lines (env directives break a run)."""
    lines = (file.processed if file.processed is not None else file.text).split("\n")
    runs: list[tuple[int, int]] = []
    start = None
    for number, text in enumerate(lines, start=1):
        match = _ANNOTATION_LINE.match(text)
        if match and match[1] not in _DIRECTIVES:
            start = number if start is None else start
        else:
            if start is not None:
                runs.append((start, number - 1))
            start = None
    if start is not None:
        runs.append((start, len(lines)))
    return runs


def _file_docs(file: SourceFile, targets: dict[str, str], module: str | None) -> FileDocs:
    docs = FileDocs(path=file.path, owner=file.owner)
    lines = (file.processed if file.processed is not None else file.text).split("\n")
    by_line: dict[int, list] = {}
    for annotation in file.annotations.items:
        by_line.setdefault(annotation.span.start_line, []).append(annotation)
        if isinstance(annotation, TagsAnnotation):
            docs.tags += [tag for tag in annotation.tags if tag not in docs.tags]
        elif isinstance(annotation, SeeAnnotation):
            docs.see.append(Reference(annotation.tag, file.path, annotation.span.start_line, targets.get(annotation.tag)))

    for first, last in _runs(file):
        found = [a for number in range(first, last + 1) for a in by_line.get(number, [])]
        if not any(isinstance(a, DocAnnotation) for a in found):
            continue
        # A @doc belongs to the declaration above it in the run -- or, before any declaration, to the first one below.
        declared: list[tuple[str, list[DocAnnotation]]] = []
        unclaimed: list[DocAnnotation] = []
        for annotation in found:
            if isinstance(annotation, _DECLARING):
                declared.append((annotation.name, unclaimed if not declared else []))
                if len(declared) == 1:
                    unclaimed = []
            elif isinstance(annotation, DocAnnotation):
                (declared[-1][1] if declared else unclaimed).append(annotation)
        def add(texts: list[DocAnnotation], kind: str, subject: str, names: list[str] | None = None) -> None:
            text = "\n".join(a.text for a in texts).strip("\n")
            if text.strip():  # bare `-- @doc` lines alone document nothing
                numbers = [a.span.start_line for a in texts]
                docs.notes.append(Note(text, file.path, numbers[0], kind, subject, names or [], numbers))

        for name, texts in declared:
            if texts:
                add(texts, "name", name, [name])
        if not unclaimed:
            continue
        fragment = next((a for a in found if isinstance(a, FragmentAnnotation)), None)
        preamble = next((a for a in found if isinstance(a, PreambleAnnotation)), None)
        if fragment is not None:
            add(unclaimed, "fragment", f"{module}.{fragment.name}" if module else f"{fragment.block}.{fragment.name}")
        elif preamble is not None:
            add(unclaimed, "preamble", preamble.name)
        else:
            following = lines[last] if last < len(lines) else ""
            if following.strip():
                add(unclaimed, "code", following.strip())
            else:
                add(unclaimed, "file", file.path)
    docs.notes.sort(key=lambda note: note.line)
    return docs


def _readme(scripts: Path, relative: str) -> Readme | None:
    try:
        return Readme(relative, (scripts / relative).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None


def _index_tags(docs: Docs) -> None:
    index: dict[str, list[str]] = {}

    def add(tags: list[str], where: str) -> None:
        for tag in tags:
            if where not in index.setdefault(tag, []):
                index[tag].append(where)

    for module in docs.modules:
        add(module.tags, f"module {module.name}")
    for block in docs.blocks:
        add(block.tags, f"block {block.name}")
    for file in docs.files:
        add(file.tags, f"file {file.path}")
    docs.tags = dict(sorted(index.items()))


def build_docs(folder: Path, linked: LinkResult | None = None) -> Docs:
    """The documentation of ``folder``'s script. ``linked`` is a link already made (``write=False`` is fine) to reuse;
    otherwise one is made, writing nothing."""
    folder = Path(folder)
    linked = linked if linked is not None else link(folder, write=False)
    project: ScriptProject = linked.project
    model: SemanticModel = linked.model if linked.model is not None else build_model(project)
    link_map = linked.link_map if linked.ok else read_link_map(folder)
    scripts = script_dir(folder)
    single = not is_linked(folder)
    env = project.env
    name = (project.manifest.project.name if project.manifest else None) or new_project.read_project_title(folder) or folder.name
    docs = Docs(
        mode="single" if single else "project", name=name, env=env.name if env else None,
        flags=sorted(env.flags) if env else [], linked=linked.ok, readme=_readme(scripts, README_FILENAME),
        description=read_store(folder)["description"],
    )

    targets = see_targets(model)
    for block in project.blocks.values():
        if block.file is not None:
            docs.files.append(_file_docs(block.file, targets, None))
    for module in project.modules:
        for file in module.files:
            docs.files.append(_file_docs(file, targets, module.name))
    tags_of = {file.path: file.tags for file in docs.files}
    notes_by_subject = {(note.kind, name): note.text for note in docs.notes for name in (note.names or [note.subject])}

    if not single:
        for name_ in project.order:
            block = project.blocks.get(name_)
            if block is None:
                continue
            file = block.file.path if block.file is not None else None
            readme = _readme(scripts, f"{BLOCKS_DIRNAME}/{Path(file).stem}.md") if file else None
            fragments = [
                {
                    "id": f.id, "loop": f.loop, "file": f.file, "line": f.line,
                    "doc": "\n".join(f.doc) or notes_by_subject.get(("fragment", f.id), ""),
                }
                for f in model.fragments_of(name_)
            ]
            docs.blocks.append(BlockDocs(
                name=name_, file=file, readme=readme, tags=list(tags_of.get(file, [])) if file else [],
                contributors=list(block.contributors), fragments=fragments,
            ))
        for module in project.modules:
            section = module.manifest.module
            files = [file.path for file in module.files]
            tags = list(section.tags)
            for path in files:
                tags += [tag for tag in tags_of.get(path, []) if tag not in tags]
            docs.modules.append(ModuleDocs(
                name=module.name, enabled=True, version=section.version, summary=section.summary,
                description=section.description, license=section.license, authors=list(section.authors), tags=tags,
                features=list(section.features), readme=_readme(scripts, f"{MODULES_DIRNAME}/{module.name}/{README_FILENAME}"),
                blocks=list(module.blocks), files=files,
            ))
        for name_ in project.disabled_modules:
            entry = ModuleDocs(name=name_, enabled=False, readme=_readme(scripts, f"{MODULES_DIRNAME}/{name_}/{README_FILENAME}"))
            manifest_file = f"{MODULES_DIRNAME}/{name_}/{MODULE_FILENAME}"
            try:
                manifest, _ = read_manifest((scripts / manifest_file).read_text(encoding="utf-8"), ModuleManifest, manifest_file)
            except (OSError, UnicodeDecodeError):
                manifest = None
            if manifest is not None:
                section = manifest.module
                entry.version, entry.summary, entry.description = section.version, section.summary, section.description
                entry.license, entry.authors = section.license, list(section.authors)
                entry.tags, entry.features = list(section.tags), list(section.features)
            docs.modules.append(entry)

    for name_, entry in (link_map.get("storage") or {}).items():
        docs.storage.append({**entry, "name": name_, "doc": notes_by_subject.get(("name", name_), "")})
    for name_, entry in (link_map.get("resources") or {}).items():
        entry = {key: value for key, value in entry.items() if key != "digest"}
        docs.resources.append({**entry, "name": name_, "doc": notes_by_subject.get(("name", name_), "")})
    docs.budget = link_map.get("budget") or {}
    docs.fusion = link_map.get("fusion") or {}
    _attach_details(folder, docs)
    _index_tags(docs)
    return docs


# -- editing entries ---------------------------------------------------------------------------------------------

_DOC_LINE = re.compile(r"^(\s*)--\s*@doc\b")

#: ``script/docs.json``: the documentation's own description -- plain text the overview opens with (not the gametype's
#: in-game description). (Before DOCSTRINGS.md it held docstring texts too, as ``entries``; :func:`read_docstrings`
#: still reads them, and :func:`sync_docstrings` moves them over.)
STORE_FILENAME = "docs.json"
#: ``script/DOCSTRINGS.md``: every docstring in the script by its title (the ``-- @doc`` line's own text) with a longer
#: text under it, written by a person -- kept in step with the script by :func:`sync_docstrings`.
DOCSTRINGS_FILENAME = "DOCSTRINGS.md"
_DETACHED_HEADING = "# No longer in the script"
_LOCATION = re.compile(r"^<!--\s*(.*?)\s*-->$")
_DOCSTRINGS_INTRO = (
    "# Docstrings\n\n"
    "Every `-- @doc` docstring in the script, by its title (what its `-- @doc` line says), with a longer text under it.\n"
    "Write the text under a title; the titles, their order and the `<!-- where -->` lines follow the script (a docstring\n"
    "taken out of the script keeps its text, under \"No longer in the script\" at the end). The documentation shows each\n"
    "text under its docstring.\n"
)


def store_path(folder: Path) -> Path:
    return script_dir(folder) / STORE_FILENAME


def docstrings_path(folder: Path) -> Path:
    return script_dir(folder) / DOCSTRINGS_FILENAME


def read_store(folder: Path) -> dict:
    """``script/docs.json`` as ``{"description": str, "entries": [...]}`` (``entries``: the old home of docstring texts)
    -- empty when there is none, or it can't be read."""
    try:
        data = json.loads(store_path(folder).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    entries = [
        {"file": str(e.get("file", "")), "note": str(e.get("note", "")), "text": str(e.get("text", ""))}
        for e in data.get("entries", []) if isinstance(e, dict)
    ]
    return {"description": str(data.get("description", "") or ""), "entries": entries}


def write_store(folder: Path, store: dict) -> Path:
    """Writes ``store`` to ``script/docs.json`` -- or, when it holds nothing, removes the file."""
    path = store_path(folder)
    store = {key: value for key, value in store.items() if value}
    if not store:
        path.unlink(missing_ok=True)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def set_description(folder: Path, text: str) -> None:
    """The documentation's own description, plain text (the overview's Description section)."""
    store = read_store(folder)
    store["description"] = text.strip("\n")
    write_store(folder, store)


def docstring_title(note: Note) -> str:
    """A docstring's title in DOCSTRINGS.md: the first line of its ``-- @doc`` text."""
    return next((line.strip() for line in note.text.splitlines() if line.strip()), "")


def read_docstrings(folder: Path) -> dict[str, str]:
    """Title -> text for every section of ``script/DOCSTRINGS.md`` (the first of any repeated title), then any older
    ``docs.json`` entries not already there."""
    texts: dict[str, str] = {}
    try:
        lines = docstrings_path(folder).read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
    except OSError:
        lines = []
    title, body = None, []

    def close() -> None:
        if title is not None:
            while body and (not body[0].strip() or _LOCATION.match(body[0].strip())):
                body.pop(0)
            texts.setdefault(title, "\n".join(body).strip("\n"))

    for line in lines:
        if line.startswith("## "):
            close()
            title, body = line[3:].strip(), []
        elif line.startswith("# "):
            close()
            title, body = None, []
        elif title is not None:
            body.append(line)
    close()
    for entry in read_store(folder)["entries"]:
        if entry["note"] and not texts.get(docstring_title(Note(entry["note"], entry["file"], 0, "code", ""))):
            texts[docstring_title(Note(entry["note"], entry["file"], 0, "code", ""))] = entry["text"]
    return texts


def render_docstrings(notes: list[Note], texts: dict[str, str]) -> str:
    """DOCSTRINGS.md for ``notes`` (in script order) with ``texts`` under their titles; texts whose title no docstring
    has any more go at the end, under "No longer in the script"."""
    out = [_DOCSTRINGS_INTRO]
    seen: set[str] = set()
    for note in notes:
        title = docstring_title(note)
        if not title or title in seen:
            continue
        seen.add(title)
        text = texts.get(title, "").strip("\n")
        out += [f"## {title}", f"<!-- {note.file}:{note.line} -->", ""] + ([text, ""] if text else [])
    detached = [(title, text) for title, text in texts.items() if title not in seen and text.strip()]
    if detached:
        out += [_DETACHED_HEADING, ""]
        for title, text in detached:
            out += [f"## {title}", "", text.strip("\n"), ""]
    return "\n".join(out).rstrip("\n") + "\n"


def _write_docstrings(folder: Path, notes: list[Note], texts: dict[str, str]) -> Path:
    path = docstrings_path(folder)
    if not notes and not any(texts.values()):
        return path
    content = render_docstrings(notes, texts)
    current = path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.is_file() else None
    if current != content:
        path.write_text(content, encoding="utf-8")
    store = read_store(folder)
    if store["entries"]:  # moved over: docs.json keeps only the description
        write_store(folder, {"description": store["description"]})
    return path


def sync_docstrings(folder: Path, docs: Docs) -> Path:
    """Brings ``script/DOCSTRINGS.md`` in step with ``docs``' docstrings -- a section for each, texts kept -- and moves
    any older ``docs.json`` texts into it. Writes only when something changed; with no docstrings and no texts, writes
    nothing."""
    return _write_docstrings(folder, docs.notes, read_docstrings(folder))


def refresh_docstrings(folder: Path, docs: Docs) -> bool:
    """:func:`sync_docstrings`, but only for a project that has a ``script/DOCSTRINGS.md`` already -- after the script is
    saved, so each where-line says where its docstring is now. ``True`` if the file changed."""
    path = docstrings_path(folder)
    if not path.is_file():
        return False
    before = path.read_text(encoding="utf-8")
    sync_docstrings(folder, docs)
    return path.read_text(encoding="utf-8") != before


def docstring_line(folder: Path, title: str) -> int:
    """The 1-based line in ``script/DOCSTRINGS.md`` where ``title``'s text starts (under its heading and where-line), or
    0 if it has no section."""
    try:
        lines = docstrings_path(folder).read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
    except OSError:
        return 0
    for number, line in enumerate(lines, start=1):
        if line.startswith("## ") and line[3:].strip() == title:
            below = number + 1
            if below <= len(lines) and _LOCATION.match(lines[below - 1].strip()):
                below += 1
            if below <= len(lines) and not lines[below - 1].strip():
                following = lines[below] if below < len(lines) else ""
                if following.strip() and not following.startswith("#"):
                    return below + 1  # the text's first line
            return below  # the blank line to start the text on
    return 0


def set_docstring_text(folder: Path, title: str, new_title: str | None, text: str | None = None) -> None:
    """Moves a docstring's text from ``title`` to ``new_title`` (``None``: the docstring is gone, and so is its text),
    replacing it with ``text`` unless that is ``None``, and rewrites DOCSTRINGS.md for the script as it is now (call it
    after the ``-- @doc`` lines themselves have changed)."""
    texts = read_docstrings(folder)
    kept = texts.pop(title, "")
    if new_title:
        texts[new_title] = text if text is not None else kept
    _write_docstrings(folder, build_docs(folder).notes, texts)


def _attach_details(folder: Path, docs: Docs) -> None:
    texts = read_docstrings(folder)
    used = set()
    for note in docs.notes:
        title = docstring_title(note)
        if title in texts:
            note.details = texts[title]
            used.add(title)
    docs.detached = [{"note": title, "text": text} for title, text in texts.items() if title not in used and text.strip()]


def rewrite_entry(folder: Path, file: str, lines: list[int], text: str | None) -> Path:
    """Replaces an entry's ``-- @doc`` lines (``lines``, 1-based, in ``script/<file>``) with ``text`` -- one ``-- @doc``
    line per line of it, at the first line's indent, a blank line as a bare ``-- @doc`` -- or, for ``None`` or blank
    text, removes them. Every other line, and the file's line endings, stay as they are. Returns the file.

    Raises:
        ValueError: One of ``lines`` is no longer a ``@doc`` line (the file changed since the entry was read)."""
    path = script_dir(folder) / file
    raw = path.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    source = raw.replace("\r\n", "\n").split("\n")
    wanted = sorted(set(lines))
    for number in wanted:
        if not (1 <= number <= len(source) and _DOC_LINE.match(source[number - 1])):
            raise ValueError(f"{file}:{number} isn't a @doc line any more -- the file has changed")
    indent = _DOC_LINE.match(source[wanted[0] - 1])[1]
    replacement = []
    if text is not None and text.strip():
        replacement = [f"{indent}-- @doc {line}".rstrip() if line.strip() else f"{indent}-- @doc" for line in text.strip("\n").split("\n")]
    gone = set(wanted)
    out: list[str] = []
    for number, line in enumerate(source, start=1):
        if number == wanted[0]:
            out += replacement
        elif number not in gone:
            out.append(line)
    written = "\n".join(out)
    path.write_bytes((written.replace("\n", "\r\n") if crlf else written).encode("utf-8"))
    return path


# -- views of it -----------------------------------------------------------------------------------------------


def filter_docs(docs: Docs, tag: str) -> Docs:
    """``docs`` narrowed to what carries ``tag``: those blocks and modules, the files that carry it or belong to one of
    them, those files' notes, and the storage and resources they own. The README, budget and fusion go (they describe
    the whole script)."""
    blocks = [b for b in docs.blocks if tag in b.tags]
    modules = [m for m in docs.modules if tag in m.tags]
    paths = {f.path for f in docs.files if tag in f.tags}
    paths |= {b.file for b in blocks if b.file} | {path for m in modules for path in m.files}
    owners = paths | {f"module {m.name}" for m in modules}
    return Docs(
        mode=docs.mode, name=f"{docs.name} -- {tag}", env=docs.env, flags=docs.flags, linked=docs.linked,
        tags={tag: docs.tags.get(tag, [])}, files=[f for f in docs.files if f.path in paths],
        blocks=blocks, modules=modules,
        storage=[s for s in docs.storage if s.get("owner") in owners],
        resources=[r for r in docs.resources if r.get("owner") in owners],
    )


def hover_texts(docs: Docs) -> dict[str, str]:
    """What an editor shows when the pointer rests on a name: each storage name (its slot and note), resource (its
    table entry, in-game text and note), fragment, block, module and tag."""
    texts: dict[str, str] = {}
    for tag, where in docs.tags.items():
        texts[tag] = f"tag {tag}: {', '.join(where)}"
    for module in docs.modules:
        texts[module.name] = "\n".join(filter(None, [
            f"module {module.name} {module.version}".rstrip() + ("" if module.enabled else " (disabled)"),
            module.summary, module.description,
        ]))
    for block in docs.blocks:
        texts[block.name] = f"block {block.name}" + (f" ({block.file})" if block.file else " (fragments only)")
        for fragment in block.fragments:
            texts[fragment["id"]] = "\n".join(filter(None, [
                f"fragment {fragment['id']}: for each {fragment['loop']} in {block.name}", _paragraph(fragment["doc"]),
            ]))
    for entry in docs.storage:
        texts[entry["name"]] = "\n".join(filter(None, [
            f"{entry['name']} = {entry['slot']}  ({entry['owner']})", _paragraph(entry.get("doc", "")),
        ]))
    for entry in docs.resources:
        text = entry.get("text", {})
        shown = " -- ".join(str(text[k]) for k in ("name", "desc") if text.get(k))
        texts[entry["name"]] = "\n".join(filter(None, [
            f"{entry['name']}: {entry['kind']} {entry['index']}  ({entry['owner']})", shown, _paragraph(entry.get("doc", "")),
        ]))
    return texts


# -- rendering -------------------------------------------------------------------------------------------------


def _paragraph(text: str) -> str:
    return " ".join(line.strip() for line in text.splitlines() if line.strip())


def _cell(text: str) -> str:
    return _paragraph(str(text)).replace("|", "\\|")


def _readme_section(readme: Readme | None, level: str) -> list[str]:
    if readme is None:
        return []
    body = readme.text.strip()
    # A README's own headings sit below the section they are shown in.
    body = re.sub(r"^(#+)", lambda m: level + m[1], body, flags=re.MULTILINE)
    return [body, ""]


def _notes(notes: list[Note]) -> list[str]:
    """Each entry as a Markdown list item: its first line beside what it documents and where, any further lines (a
    longer entry is Markdown too) indented under it."""
    out = []
    for note in notes:
        where = f"`{note.file}:{note.line}`"
        first, *rest = note.text.split(chr(10))
        if note.kind == "file":
            out.append(f"- {first} ({where})")
        elif note.kind == "code":
            out.append(f"- `{note.subject}` -- {first} ({where})")
        else:
            out.append(f"- **{note.subject}** -- {first} ({where})")
        if note.details.strip():
            rest += ["", *note.details.strip(chr(10)).split(chr(10))]
        out += [f"  {line}" if line.strip() else "" for line in rest]
    return out


def render_markdown(docs: Docs) -> str:
    """The overview as Markdown."""
    out: list[str] = [f"# {docs.name}", ""]
    kind = "Single-file script" if docs.mode == "single" else "Script project"
    env = f"env `{docs.env}`" + (f" ({', '.join(docs.flags)})" if docs.flags else "") if docs.env else "no env"
    out += [f"{kind} -- {env}." + ("" if docs.linked else " **The script doesn't link right now**; slots and budget are from the last link."), ""]
    if docs.tags:
        out += ["Tags: " + " ".join(f"`{tag}`" for tag in docs.tags), ""]
    out += ["## Description", "", docs.description.strip() or "*No description yet.*", ""]
    out += _readme_section(docs.readme, "#")

    file_notes = [n for n in docs.notes if n.kind == "file"]
    if file_notes:
        # Markdown as written
        out += ["## About", "", *[n.text + ("\n\n" + n.details.strip() if n.details.strip() else "") + "\n" for n in file_notes]]

    for block in docs.blocks:
        out += [f"## Block {block.name}" + (f" (`{block.file}`)" if block.file else " (fragments only)"), ""]
        if block.tags:
            out += ["Tags: " + " ".join(f"`{t}`" for t in block.tags), ""]
        out += _readme_section(block.readme, "##")
        notes = [n for n in docs.notes if n.file == block.file and n.kind != "file"]
        if notes:
            out += [*_notes(notes), ""]
        if block.fragments:
            out += ["| Fragment | Loop | Source | Notes |", "|---|---|---|---|"]
            out += [
                f"| `{f['id']}` | {f['loop'] or ''} | `{f['file']}:{f['line']}` | {_cell(f['doc'])} |" for f in block.fragments
            ]
            out.append("")

    for module in docs.modules:
        title = f"## Module {module.name}" + (f" {module.version}" if module.version else "") + ("" if module.enabled else " (disabled)")
        out += [title, ""]
        if module.summary:
            out += [module.summary, ""]
        if module.description:
            out += [module.description, ""]
        facts = []
        if module.blocks:
            facts.append("adds to " + ", ".join(module.blocks))
        if module.tags:
            facts.append("tags " + " ".join(f"`{t}`" for t in module.tags))
        if module.features:
            facts.append("features " + ", ".join(module.features))
        if module.authors:
            facts.append("by " + ", ".join(module.authors))
        if module.license:
            facts.append(f"license {module.license}")
        if facts:
            sentence = "; ".join(facts)
            out += [sentence[0].upper() + sentence[1:] + ".", ""]
        out += _readme_section(module.readme, "##")
        notes = [n for n in docs.notes if n.file in module.files and n.kind != "file"]
        if notes:
            out += [*_notes(notes), ""]

    if docs.storage:
        out += ["## Storage", "", "| Name | Slot | Owner | Notes |", "|---|---|---|---|"]
        out += [f"| `{s['name']}` | `{s['slot']}` | {s['owner']} | {_cell(s['doc'])} |" for s in docs.storage]
        out.append("")
    if docs.resources:
        out += ["## Resources", "", "| Name | Kind | Index | Owner | Text | Notes |", "|---|---|---|---|---|---|"]
        for r in docs.resources:
            text = r.get("text", {})
            shown = " -- ".join(str(text[k]) for k in ("name", "desc") if text.get(k))
            out.append(f"| `{r['name']}` | {r['kind']} | {r['index']} | {r['owner']} | {_cell(shown)} | {_cell(r['doc'])} |")
        out.append("")
    pools = {k: v for k, v in docs.budget.items() if isinstance(v, dict) and "cap" in v}
    counters = docs.budget.get("counters") or {}
    if pools or counters:
        out += ["## Budget", "", "| Pool | Used | Cap |", "|---|---|---|"]
        out += [f"| {k} | {v['used']} | {v['cap']} |" for k, v in {**pools, **counters}.items() if "cap" in v]
        out.append("")
    groups = docs.fusion.get("groups") or []
    declined = docs.fusion.get("declined") or []
    if groups or declined:
        out += ["## Fusion", ""]
        out += [f"- {g['trigger']}: {' + '.join(g['fragments'])}" for g in groups]
        out += [f"- kept apart: {' | '.join(d['fragments'])} -- {d['reason']}" for d in declined]
        out.append("")

    code_notes = [n for n in docs.notes if n.kind != "file"] if docs.mode == "single" else []
    if code_notes:
        out += ["## Notes in the code", "", *_notes(code_notes), ""]
    if docs.tags:
        out += ["## Tags", ""]
        out += [f"- `{tag}`: {', '.join(where)}" for tag, where in docs.tags.items()]
        out.append("")
    if docs.detached:
        out += [
            "## Docstring texts no longer in the script", "",
            f"In `script/{DOCSTRINGS_FILENAME}`: their `-- @doc` line was removed or reworded.", "",
        ]
        for entry in docs.detached:
            out += [f"- {entry['note']}", *[f"  {line}" if line.strip() else "" for line in entry["text"].split("\n")]]
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def docs_dir(folder: Path) -> Path:
    return Path(folder) / new_project.BUILD_DIRNAME / DOCS_DIRNAME


def write_docs(folder: Path, docs: Docs) -> list[Path]:
    """Writes ``build/docs/overview.md`` and ``overview.json`` -- and brings ``script/DOCSTRINGS.md`` in step with the
    script (:func:`sync_docstrings`); returns the ``build/docs`` files whose content changed."""
    sync_docstrings(folder, docs)
    directory = docs_dir(folder)
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name, content in (
        (OVERVIEW_MD, render_markdown(docs)),
        (OVERVIEW_JSON, json.dumps(docs.to_dict(), indent=2) + "\n"),
    ):
        path = directory / name
        if not path.is_file() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")
            written.append(path)
    return written


__all__ = ["Docs", "Note", "build_docs", "render_markdown", "write_docs"]
