"""Shareable modules: adding one from a folder or a git repository, pinning it, and checking the pin.

A module is a folder (``module.toml`` plus ``.mgl`` files). Sharing one is copying that folder; this module makes the copy
*traceable* without adding a registry:

* ``in-reach module add <source>`` fetches the module and **vendors** it -- copies its files into
  ``script/modules/<name>/`` like any hand-made module, so the project builds from what is in the project and nothing is
  fetched at build time -- and records where it came from in ``project.toml`` (``[[modules]] source = ...``).
* ``project.lock`` records, per module that has a ``source``, its version, the source it was fetched from (a git source is
  pinned to the exact commit) and a content hash of the vendored files.
* ``in-reach module verify`` recomputes the hashes, so a vendored module that was edited (or deleted) is a located problem;
  the loader reports the same as a warning on every load, since editing a vendored module locally is legitimate.
* ``in-reach module update <name>`` fetches the source again and replaces the vendored files.

Sources: ``path:<folder>`` (or just a folder that exists) and ``git+<url>[@<rev>][#subdir=<path>]`` (any URL dulwich can clone,
including ``file:///`` and local paths; ``rev`` is a branch, tag or commit; ``subdir`` is where the module is inside the
repository).

The content hash is over each file's path and text with line endings normalised, so it is the same on a checkout with CRLF
line endings as on one with LF (this repository runs ``autocrlf``).
"""

from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import tomlkit

from .diagnostics import ProjectDiagnostic
from .manifests import ModuleManifest, read_manifest

LOCK_FILENAME = "project.lock"
_PROJECT_FILENAME = "project.toml"
_MODULE_FILENAME = "module.toml"
_MODULE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SKIPPED_DIRECTORIES = {".git", "__pycache__"}
_URL_START = re.compile(r"^(?:https?://|ssh://|git://|file://|git@)")


class PackageError(ValueError):
    """Something the user can fix (a source that isn't a module, a name already taken, ...)."""


@dataclass(frozen=True)
class LockEntry:
    name: str
    version: str
    source: str
    sha256: str


@dataclass
class AddedModule:
    name: str
    version: str
    source: str
    files: list[str] = field(default_factory=list)  # relative to the project folder
    warnings: list[str] = field(default_factory=list)


# -- paths and hashing ----------------------------------------------------------------------------------------


def _scripts(folder: Path) -> Path:
    return folder / "script"


def _module_dir(folder: Path, name: str) -> Path:
    return _scripts(folder) / "modules" / name


def _files(directory: Path) -> list[Path]:
    return sorted(
        p for p in directory.rglob("*")
        if p.is_file() and not any(part in _SKIPPED_DIRECTORIES for part in p.relative_to(directory).parts)
    )


def tree_hash(directory: Path) -> str:
    """A hash of a module folder's contents: each file's relative path and content, with CRLF read as LF."""
    digest = hashlib.sha256()
    for path in _files(directory):
        digest.update(path.relative_to(directory).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return digest.hexdigest()


def _copy_tree(source: Path, destination: Path) -> list[Path]:
    destination.mkdir(parents=True)
    copied = []
    for path in _files(source):
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        copied.append(target)
    return copied


# -- the lock file ----------------------------------------------------------------------------------------------


def read_lock(folder: Path) -> dict[str, LockEntry]:
    path = _scripts(folder) / LOCK_FILENAME
    try:
        doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    except (OSError, tomlkit.exceptions.TOMLKitError):
        return {}
    entries = {}
    for table in doc.get("module", []):
        try:
            entries[str(table["name"])] = LockEntry(
                str(table["name"]), str(table.get("version", "")), str(table.get("source", "")), str(table["sha256"])
            )
        except KeyError:
            continue
    return entries


def write_lock(folder: Path, entries: dict[str, LockEntry]) -> None:
    doc = tomlkit.document()
    doc.add(tomlkit.comment("Written by `in-reach module add|lock|update`: what each shared module was fetched from."))
    aot = tomlkit.aot()
    for name in sorted(entries):
        entry = entries[name]
        table = tomlkit.table()
        table["name"], table["version"], table["source"], table["sha256"] = entry.name, entry.version, entry.source, entry.sha256
        aot.append(table)
    if entries:
        doc["module"] = aot
    (_scripts(folder) / LOCK_FILENAME).write_text(tomlkit.dumps(doc), encoding="utf-8")


# -- sources ---------------------------------------------------------------------------------------------------------


def _relative_or_absolute(path: Path, folder: Path) -> str:
    try:
        return path.resolve().relative_to(_scripts(folder).resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _fetch(source: str, folder: Path, base: Path, rev: str | None, scratch: Path) -> tuple[Path, str]:
    """The module folder for ``source`` (inside ``scratch`` for a git source) and the source string to record."""
    if source.startswith("git+") or _URL_START.match(source):
        return _fetch_git(source, rev, scratch)
    raw = source.removeprefix("path:")
    directory = Path(raw) if Path(raw).is_absolute() else (base / raw)
    if not (directory / _MODULE_FILENAME).is_file():
        # a recorded relative path is relative to script/, one typed at the prompt to where it was typed
        alternative = _scripts(folder) / raw
        if (alternative / _MODULE_FILENAME).is_file():
            directory = alternative
    if not directory.is_dir():
        raise PackageError(f"{source!r} is not a folder")
    return directory, "path:" + _relative_or_absolute(directory, folder)


def _fetch_git(source: str, rev: str | None, scratch: Path) -> tuple[Path, str]:
    from dulwich import porcelain

    text = source.removeprefix("git+")
    subdir = None
    if "#subdir=" in text:
        text, subdir = text.split("#subdir=", 1)
    if rev is None and re.search(r"@[^/@:]+$", text) and not text.startswith("git@"):
        text, rev = text.rsplit("@", 1)
    elif rev is None and text.startswith("git@") and text.count("@") > 1:
        text, rev = text.rsplit("@", 1)
    target = scratch / "clone"
    # A local repository given as a path ("C:/repos/modules") is handed to dulwich as a file:// URL: a bare Windows path would
    # be read as ssh's host:path.
    clone_from = Path(text).resolve().as_uri() if not _URL_START.match(text) and Path(text).exists() else text
    repo = None
    try:
        repo = porcelain.clone(clone_from, str(target))
        if rev:
            porcelain.reset(repo, "hard", rev)
        sha = repo.head().decode("ascii")
    except Exception as exc:  # noqa: BLE001 -- dulwich raises its own zoo (missing refs, transport errors)
        raise PackageError(f"couldn't fetch {text}{'@' + rev if rev else ''}: {exc}") from exc
    finally:
        if repo is not None:
            repo.close()  # Windows can't delete the clone's pack files while they're open
    directory = target / subdir if subdir else target
    recorded = f"git+{text}@{sha}" + (f"#subdir={subdir}" if subdir else "")
    return directory, recorded


def _read_module_manifest(directory: Path) -> ModuleManifest:
    try:
        text = (directory / _MODULE_FILENAME).read_text(encoding="utf-8")
    except OSError:
        raise PackageError(f"{directory} has no {_MODULE_FILENAME}: it isn't a module") from None
    manifest, diagnostics = read_manifest(text, ModuleManifest, _MODULE_FILENAME)
    if manifest is None:
        raise PackageError(f"{_MODULE_FILENAME} is not valid: {diagnostics[0].message if diagnostics else 'unreadable'}")
    return manifest


def _version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text)[:3])


def _min_version_warning(manifest: ModuleManifest) -> list[str]:
    required = manifest.module.min_in_reach
    if not required:
        return []
    from in_reach import __version__

    if _version_tuple(required) > _version_tuple(__version__):
        return [f"module {manifest.module.name} needs in-reach {required} or newer (this is {__version__})"]
    return []


# -- project.toml ------------------------------------------------------------------------------------------------------


def _edit_project_toml(folder: Path, name: str, source: str | None) -> None:
    """Adds ``[[modules]] name = ..., source = ...`` (or sets ``source`` on the entry that's there), keeping the rest as it is."""
    path = _scripts(folder) / _PROJECT_FILENAME
    doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    modules = doc.get("modules")
    for table in modules or []:
        if table.get("name") == name:
            if source is not None:
                table["source"] = source
            path.write_text(tomlkit.dumps(doc), encoding="utf-8")
            return
    table = tomlkit.table()
    table["name"] = name
    if source is not None:
        table["source"] = source
    if modules is None:
        aot = tomlkit.aot()
        aot.append(table)
        doc["modules"] = aot
    else:
        modules.append(table)
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")


def _sourced_modules(folder: Path) -> dict[str, str]:
    """``name -> source`` for every ``[[modules]]`` entry of ``project.toml`` that has one."""
    try:
        doc = tomlkit.parse((_scripts(folder) / _PROJECT_FILENAME).read_text(encoding="utf-8"))
    except (OSError, tomlkit.exceptions.TOMLKitError):
        return {}
    return {str(t["name"]): str(t["source"]) for t in doc.get("modules", []) if "name" in t and "source" in t}


def _require_script_project(folder: Path) -> None:
    if not (_scripts(folder) / _PROJECT_FILENAME).is_file():
        raise PackageError("this project has no script/project.toml -- create a script project first")


# -- the operations -----------------------------------------------------------------------------------------------------


def add_module(folder: Path, source: str, *, name: str | None = None, rev: str | None = None, base: Path | None = None) -> AddedModule:
    """Fetches the module at ``source`` and vendors it into ``script/modules/<name>/``, records its source in ``project.toml``
    and pins it in ``project.lock``. ``name`` defaults to the module's own name; ``base`` is what a relative path source is
    relative to (the current directory by default).

    Raises:
        PackageError: The source isn't a module, the name isn't valid, or a module of that name is already there."""
    _require_script_project(folder)
    with tempfile.TemporaryDirectory(prefix="in-reach-module-") as scratch:
        directory, recorded = _fetch(source, folder, base or Path.cwd(), rev, Path(scratch))
        manifest = _read_module_manifest(directory)
        chosen = name or manifest.module.name
        if not _MODULE_NAME.fullmatch(chosen):
            raise PackageError(f"{chosen!r} isn't a valid module name (letters, digits and underscores, not starting with a digit)")
        destination = _module_dir(folder, chosen)
        if destination.exists():
            raise PackageError(f"module {chosen} already exists in this project")
        copied = _copy_tree(directory, destination)
    _edit_project_toml(folder, chosen, recorded)
    entries = read_lock(folder)
    entries[chosen] = LockEntry(chosen, manifest.module.version, recorded, tree_hash(destination))
    write_lock(folder, entries)
    return AddedModule(
        chosen, manifest.module.version, recorded, [p.relative_to(folder).as_posix() for p in copied], _min_version_warning(manifest)
    )


def lock_modules(folder: Path) -> dict[str, LockEntry]:
    """Re-pins every module that has a ``source``: records the hash of its vendored files as they are now."""
    _require_script_project(folder)
    entries = {}
    for name, source in _sourced_modules(folder).items():
        directory = _module_dir(folder, name)
        if not directory.is_dir():
            raise PackageError(f"module {name} has a source but no folder at script/modules/{name}; run `module update {name}`")
        version = _read_module_manifest(directory).module.version
        entries[name] = LockEntry(name, version, source, tree_hash(directory))
    write_lock(folder, entries)
    return entries


def update_module(folder: Path, name: str, *, rev: str | None = None, base: Path | None = None) -> AddedModule:
    """Fetches ``name``'s source again and replaces its vendored files (local edits to them are lost)."""
    _require_script_project(folder)
    source = _sourced_modules(folder).get(name)
    if source is None:
        raise PackageError(f"module {name} has no source to update from")
    with tempfile.TemporaryDirectory(prefix="in-reach-module-") as scratch:
        # a git source is recorded pinned to a commit; updating without a rev means "the source's current head"
        fetch_from = re.sub(r"@[0-9a-f]{40}", "", source) if source.startswith("git+") and rev is None else source
        directory, recorded = _fetch(fetch_from, folder, base or Path.cwd(), rev, Path(scratch))
        manifest = _read_module_manifest(directory)
        destination = _module_dir(folder, name)
        if destination.exists():
            shutil.rmtree(destination)
        copied = _copy_tree(directory, destination)
    _edit_project_toml(folder, name, recorded)
    entries = read_lock(folder)
    entries[name] = LockEntry(name, manifest.module.version, recorded, tree_hash(destination))
    write_lock(folder, entries)
    return AddedModule(name, manifest.module.version, recorded, [p.relative_to(folder).as_posix() for p in copied], _min_version_warning(manifest))


def verify_modules(folder: Path, *, severity: str = "error") -> list[ProjectDiagnostic]:
    """Everything wrong with the pins: a locked module whose files changed or are gone, a module with a source that isn't
    locked, a lock entry for a module the project no longer lists. Located at ``project.lock`` (or ``project.toml``)."""
    found: list[ProjectDiagnostic] = []
    locked = read_lock(folder)
    sourced = _sourced_modules(folder)
    for name, entry in sorted(locked.items()):
        directory = _module_dir(folder, name)
        if not directory.is_dir():
            found.append(ProjectDiagnostic(severity=severity, code="lock-missing", message=f"module {name} is locked but script/modules/{name} is missing", file=LOCK_FILENAME, hint=f"run `in-reach module update {name}`"))
        elif tree_hash(directory) != entry.sha256:
            found.append(ProjectDiagnostic(severity=severity, code="lock-mismatch", message=f"module {name}'s files differ from what {LOCK_FILENAME} pinned (from {entry.source})", file=f"modules/{name}/{_MODULE_FILENAME}", hint="edited locally? run `in-reach module lock` to keep the edits, or `module update` to discard them"))
        if name not in sourced:
            found.append(ProjectDiagnostic(severity="warning", code="lock-orphan", message=f"{LOCK_FILENAME} pins module {name}, which project.toml has no source for", file=LOCK_FILENAME))
    for name in sorted(set(sourced) - set(locked)):
        found.append(ProjectDiagnostic(severity="warning", code="lock-unlocked", message=f"module {name} has a source but isn't in {LOCK_FILENAME}", file=_PROJECT_FILENAME, hint="run `in-reach module lock`"))
    return found
