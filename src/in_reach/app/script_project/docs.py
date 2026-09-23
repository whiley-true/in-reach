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
    """One run of ``@doc`` lines. ``kind`` is what it documents: ``"file"``, ``"name"`` (``subject`` is the names,
    comma-separated), ``"fragment"``, ``"preamble"`` or ``"code"`` (``subject`` is that line of code)."""

    text: str
    file: str
    line: int
    kind: str
    subject: str
    names: list[str] = field(default_factory=list)


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
    tags: dict[str, list[str]] = field(default_factory=dict)  # tag -> "block SETUP" / "module x" / "file output.txt"
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
        for name, texts in declared:
            if texts:
                docs.notes.append(Note("\n".join(a.text for a in texts), file.path, texts[0].span.start_line, "name", name, [name]))
        if not unclaimed:
            continue
        text = "\n".join(a.text for a in unclaimed)
        line = unclaimed[0].span.start_line
        fragment = next((a for a in found if isinstance(a, FragmentAnnotation)), None)
        preamble = next((a for a in found if isinstance(a, PreambleAnnotation)), None)
        if fragment is not None:
            subject = f"{module}.{fragment.name}" if module else f"{fragment.block}.{fragment.name}"
            docs.notes.append(Note(text, file.path, line, "fragment", subject))
        elif preamble is not None:
            docs.notes.append(Note(text, file.path, line, "preamble", preamble.name))
        else:
            following = lines[last] if last < len(lines) else ""
            if following.strip():
                docs.notes.append(Note(text, file.path, line, "code", following.strip()))
            else:
                docs.notes.append(Note(text, file.path, line, "file", file.path))
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
    _index_tags(docs)
    return docs


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
    out = []
    for note in notes:
        where = f"`{note.file}:{note.line}`"
        if note.kind == "file":
            out.append(f"- {_paragraph(note.text)} ({where})")
        elif note.kind == "code":
            out.append(f"- `{note.subject}` -- {_paragraph(note.text)} ({where})")
        else:
            out.append(f"- **{note.subject}** -- {_paragraph(note.text)} ({where})")
    return out


def render_markdown(docs: Docs) -> str:
    """The overview as Markdown."""
    out: list[str] = [f"# {docs.name}", ""]
    kind = "Single-file script" if docs.mode == "single" else "Script project"
    env = f"env `{docs.env}`" + (f" ({', '.join(docs.flags)})" if docs.flags else "") if docs.env else "no env"
    out += [f"{kind} -- {env}." + ("" if docs.linked else " **The script doesn't link right now**; slots and budget are from the last link."), ""]
    if docs.tags:
        out += ["Tags: " + " ".join(f"`{tag}`" for tag in docs.tags), ""]
    out += _readme_section(docs.readme, "#")

    file_notes = [n for n in docs.notes if n.kind == "file"]
    if file_notes:
        out += ["## About", "", *[_paragraph(n.text) + "\n" for n in file_notes]]

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
    return "\n".join(out).rstrip("\n") + "\n"


def docs_dir(folder: Path) -> Path:
    return Path(folder) / new_project.BUILD_DIRNAME / DOCS_DIRNAME


def write_docs(folder: Path, docs: Docs) -> list[Path]:
    """Writes ``build/docs/overview.md`` and ``overview.json``; returns the files whose content changed."""
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
