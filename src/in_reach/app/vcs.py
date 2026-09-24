"""A per-project shadow VCS history, backed by Dulwich (PROMPT.md: "vcs panel and dulwich
implementation").

Design follows the shadow-repo shape already designed (and partially shipped) in the prior
``in-reach-v2`` prototype, per this repo's own ``TO_IMPLEMENT_(LATEST).md`` (§0.1 item 9, §2, §9.6):
a *bare* git repository with no working tree of its own -- the real "working tree" is just whatever
currently sits on disk under the project folder. A commit's own tree is always built directly from
that working tree (skipping this history store itself and anything
:func:`~in_reach.app.new_project.is_generated_file` already knows is disposable build output), so a
snapshot always reflects exactly what a user would see in the Explorer right now -- never a
separately-tracked copy of file *content* the way a real git index/working-tree checkout is.

There *is* a real staging area now (PROMPT.md, a later VSCode-style pass: "please then make it so
that changes should be staged, and then committed") -- and, unlike this module's own original design,
it now matches git's own index semantics exactly (PROMPT.md, a further pass: "when a change is
staged is essentially snapshotted"): :func:`stage` writes each staged path's *current* on-disk
content into this shadow repo's own object store as a real blob right then, and records that blob's
sha (not the path alone) in ``stage.json`` (see :func:`_read_staged_snapshot`/
:func:`_write_staged_snapshot`, persisted next to this shadow repo itself). :func:`commit` builds its
tree from that recorded snapshot, never by re-reading disk -- editing a staged file again afterward
never silently changes what's about to be committed; the edit just becomes a new, separate
uncommitted change on top of the snapshot, so the same path can appear in :func:`uncommitted_changes`
*twice* at once (a staged entry, frozen at the snapshot, and an unstaged entry for the further edit),
same as VSCode's own split "Staged Changes"/"Changes" lists. Staging an already-staged path again
simply overwrites its recorded snapshot with the current on-disk content, same as a second
``git add`` would.

PROMPT.md (a later pass): "we also want our vcs functionality to better match vscode
functionality[;] so we want to add committed changes and uncommitted changes ... committing changes
should require a commit message[;] we want to remove the autosave entries in vcs history panel" --
this superseded an earlier PROMPT.md pass's own "every change should be traceable (but not stamped
explicitly)" design (the ``record_change``/anonymous ``"autosave"``-message commit this module used
to make on every single file save, whether or not the user ever asked for a checkpoint there). That
auto-commit-on-save mechanism is gone: nothing in this module creates a commit on its own any more
except :func:`restore_snapshot` (whose own auto-generated ``"restored <sha>"`` message is real and
descriptive, not the old anonymous ``"autosave"``) -- a save now just changes what
:func:`uncommitted_changes` reports (a live diff against ``HEAD``, never itself written to the
object store as a commit), matching how git/VSCode's own working tree behaves. Two kinds of *commit*
share one history rather than two parallel mechanisms, both now requiring a real, non-empty message:

- **Commit** (:func:`commit`) -- the everyday checkpoint, VSCode's own plain "Commit" action.
- **Stamp** (:func:`stamp`, PROMPT.md: "ability for a user to stamp a release (which takes a 'commit
  message')") -- an explicit release marker on top of the same history, told apart from an ordinary
  commit by a literal ``"stamp: "`` message prefix rather than a separate sidecar status file (the
  commit log is already the one source of truth for "was this ever explicitly stamped").
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from dulwich.objects import Blob, Commit, Tree
from dulwich.repo import Repo

from in_reach.app import logging_setup
from in_reach.app.new_project import is_generated_file, is_personal_file

_logger = logging_setup.get_logger(__name__)

HISTORY_DIRNAME = ".in-reach/history"
DEFAULT_BRANCH = "main"

_AUTHOR = b"in-reach <in-reach@local>"
_STAMP_PREFIX = "stamp: "
#: PROMPT.md: "we also want to add the functionality for version numbers using major, minor, patch
#: with stamped releases" -- a stamp's own version, when it has one, rides in the commit message
#: itself (same "the commit log is already the one source of truth" reasoning this module's own
#: docstring already gives for telling a stamp apart from a plain commit), as a
#: ``"v{major}.{minor}.{patch} "`` prefix right after :data:`_STAMP_PREFIX`, ahead of the user's own
#: message. Optional -- a stamp made before version tracking existed (or, today, one :func:`stamp`
#: was called without a ``version``) simply has no version at all, see :attr:`Snapshot.version`.
_VERSION_PREFIX_RE = re.compile(r"^v(\d+\.\d+\.\d+) (.*)$", re.DOTALL)

#: PROMPT.md: "the init gametype should be get a version number of 0.0.0".
INITIAL_VERSION = "0.0.0"


@dataclass
class Snapshot:
    """One commit in a project's shadow history."""

    sha: str
    message: str
    at: float
    #: The user's own message, with the ``"stamp: "`` prefix (and, if present, its own
    #: ``"v{version}} "`` prefix -- see :attr:`version`) stripped -- ``None`` for a plain commit.
    stamp_message: str | None
    #: This stamp's own ``"{major}.{minor}.{patch}"`` version number, if it was given one when
    #: stamped (see :func:`stamp`'s own ``version`` argument) -- ``None`` for a plain commit, or a
    #: stamp made without a version at all (every stamp made through the Git panel's own "Stamp
    #: Release" dialog always has one; this stays optional so an older, pre-version-tracking stamp
    #: still parses as a valid stamp rather than crashing on the missing prefix).
    version: str | None = None
    #: Every parent commit's own sha (empty for the very first commit on a branch, more than one
    #: entry only for a merge -- this shadow VCS never actually merges branches today, but the field
    #: stays a list rather than ``str | None`` so :func:`graph_history`'s own topology data doesn't
    #: need a second, differently-shaped type). Populated by :func:`graph_history`; plain
    #: :func:`history` leaves it empty (its own callers only ever cared about one branch's own
    #: linear order, never the DAG shape).
    parents: list[str] = field(default_factory=list)
    #: Every branch name whose tip is exactly this commit, if any -- also only ever populated by
    #: :func:`graph_history`.
    branches: list[str] = field(default_factory=list)
    #: The env the project was building with at this commit (``script/env/active_env.txt`` in its tree -- the file
    #: is versioned like any other), or ``None`` for none. Filled by :func:`history` and :func:`graph_history`.
    env: str | None = None

    @property
    def is_stamp(self) -> bool:
        return self.stamp_message is not None


def history_dir(folder: Path) -> Path:
    """``folder``'s own shadow-repo path -- ``<folder>/.in-reach/history`` (PROMPT.md; see this
    module's own docstring for why this sits under the *project* folder, not the app-root
    ``.in-reach`` :func:`~in_reach.app.project.get_project_dir` returns -- those are two unrelated
    folders that happen to share a name, one per level, matching ``TO_IMPLEMENT_(LATEST).md``'s own
    per-project layout)."""
    return folder / HISTORY_DIRNAME


def is_initialized(folder: Path) -> bool:
    """Whether ``folder`` already has a shadow history repo."""
    return (history_dir(folder) / "HEAD").is_file()


def _open(folder: Path) -> Repo:
    return Repo(str(history_dir(folder)))


def _branch_ref(name: str) -> bytes:
    return f"refs/heads/{name}".encode()


def init(folder: Path, *, stamp_message: str | None = None, version: str | None = INITIAL_VERSION) -> None:
    """Creates ``folder``'s shadow history repo and takes its first snapshot.

    PROMPT.md: "vcs should be started when a new blank project (either blank or from template)" --
    called once, right after :func:`~in_reach.app.new_project.create_gametype_project` finishes
    writing everything else a new project starts with, so there's always at least one snapshot (a
    branch/HEAD with nothing to diff against isn't useful) and the very first files a project ever
    had are themselves traceable.

    Args:
        stamp_message: When given, the first snapshot is a real user-labelled stamp (this
            module's own docstring on "Stamped" commits) carrying this message. PROMPT.md: "when a
            gametype is innited it should be stamped with commit 'gametype init'" --
            :func:`~in_reach.app.new_project.create_gametype_project` passes ``"gametype init"``
            here, the only real caller -- every other caller gets a plain ``"Initial commit"``.
        version: The initial stamp's own version -- ignored unless ``stamp_message`` is also given.
            Defaults to :data:`INITIAL_VERSION` (PROMPT.md: "the init gametype should be get a
            version number of 0.0.0"), so every real caller gets one for free; pass ``None`` to
            stamp without one (only ever done by tests exercising the pre-version-tracking shape).

    A no-op if ``folder`` already has a history repo (never re-initializes over one), or if there's
    nothing to snapshot yet (an empty ``folder``) -- same "no empty commits" rule as :func:`commit`.
    """
    if is_initialized(folder):
        return
    path = history_dir(folder)
    path.mkdir(parents=True, exist_ok=True)
    repo = Repo.init_bare(str(path))
    # dulwich's own init_bare() points HEAD at "refs/heads/master" -- overridden to this module's
    # own DEFAULT_BRANCH so a fresh project's branch name doesn't quietly depend on dulwich's
    # default rather than this module's own documented one.
    repo.refs.set_symbolic_ref(b"HEAD", _branch_ref(DEFAULT_BRANCH))
    tree_sha = _build_tree(repo, _walk_files(folder))
    if tree_sha is None:
        return
    if stamp_message:
        version_prefix = f"v{version} " if version else ""
        message = f"{_STAMP_PREFIX}{version_prefix}{stamp_message}"
    else:
        message = "Initial commit"
    sha = _commit(repo, tree_sha, message)
    _logger.info("initialized shadow VCS history for %s (%s, %r)", folder, sha, message)


def _should_skip(path: Path, folder: Path) -> bool:
    vcs_root = folder / ".in-reach"
    if path == vcs_root or vcs_root in path.parents:
        return True
    relative = path.relative_to(folder)
    return is_generated_file(relative) or is_personal_file(relative)


def _walk_files(folder: Path) -> dict[str, Path]:
    """Every real (non-history, non-generated) file under ``folder``, keyed by its ``/``-joined
    path relative to ``folder`` -- the same shape both :func:`_build_tree` (writing a snapshot) and
    :func:`_checkout_tree` (restoring one) need, so exclusion can never quietly drift between the
    two directions."""
    files: dict[str, Path] = {}
    for path in folder.rglob("*"):
        if path.is_dir() or _should_skip(path, folder):
            continue
        files[path.relative_to(folder).as_posix()] = path
    return files


def _build_tree(repo: Repo, files: dict[str, Path | bytes]) -> bytes | None:
    """Builds (and stores) a :class:`Tree` object per directory level from ``files``, bottom-up,
    returning the root tree's sha -- or ``None`` if ``files`` is empty (git has no way to represent
    an empty tree as a parent entry).

    Each value is either a real on-disk :class:`Path` (read fresh and hashed into a new blob) or an
    already-existing blob's own raw sha (reused as-is, no re-read/re-hash) -- the latter is what
    :func:`_staged_tree` needs to carry a staged commit's *untouched* paths straight over from
    ``HEAD``'s own tree without re-reading files this commit was never asked to include at all.
    """
    root: dict[str, object] = {}
    for rel, value in files.items():
        parts = rel.split("/")
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})  # type: ignore[assignment]
        node[parts[-1]] = value

    def _write(node: dict[str, object]) -> bytes | None:
        tree = Tree()
        for name in sorted(node):
            value = node[name]
            if isinstance(value, dict):
                sub_sha = _write(value)
                if sub_sha is None:
                    continue
                tree.add(name.encode("utf-8"), 0o040000, sub_sha)
            elif isinstance(value, bytes):
                tree.add(name.encode("utf-8"), 0o100644, value)
            else:
                data = value.read_bytes()  # type: ignore[union-attr]
                blob = Blob.from_string(data)
                repo.object_store.add_object(blob)
                tree.add(name.encode("utf-8"), 0o100644, blob.id)
        if len(tree) == 0:
            return None
        repo.object_store.add_object(tree)
        return tree.id

    return _write(root)


def _flat_tree_blobs(repo: Repo, tree_sha: bytes | None) -> dict[str, bytes]:
    """Every blob's own sha in ``tree_sha`` (recursively), keyed by its ``/``-joined path -- the
    same shape :func:`_walk_files` gives :func:`_build_tree` for a disk-sourced tree, just sourced
    from an already-committed tree instead. ``{}`` for ``tree_sha=None`` (an empty/unborn tree)."""
    blobs: dict[str, bytes] = {}
    if tree_sha is None:
        return blobs

    def _walk(sha: bytes, prefix: str) -> None:
        tree = repo.object_store[sha]
        for entry in tree.iteritems():
            rel = f"{prefix}{entry.path.decode('utf-8')}"
            if entry.mode == 0o040000:
                _walk(entry.sha, f"{rel}/")
            else:
                blobs[rel] = entry.sha

    _walk(tree_sha, "")
    return blobs


def _head_commit(repo: Repo) -> Commit | None:
    try:
        head_sha = repo.refs[b"HEAD"]
    except KeyError:
        return None
    return repo.object_store[head_sha]


def _commit(repo: Repo, tree_sha: bytes, message: str, *, extra_parents: list[bytes] = ()) -> str:
    """Commits ``tree_sha`` onto the current branch's own ``HEAD`` -- ``extra_parents`` (each a
    commit sha), if given, are additional parents beyond ``HEAD`` itself, for :func:`merge_branch`'s
    own merge commit (two parents: this branch's own tip, plus the branch being merged in's)."""
    parent = _head_commit(repo)
    commit = Commit()
    commit.tree = tree_sha
    commit.parents = ([parent.id] if parent is not None else []) + list(extra_parents)
    commit.author = commit.committer = _AUTHOR
    now = int(time.time())
    commit.author_time = commit.commit_time = now
    commit.author_timezone = commit.commit_timezone = 0
    commit.encoding = b"UTF-8"
    commit.message = message.encode("utf-8")
    repo.object_store.add_object(commit)

    branch_ref = _current_branch_ref(repo)
    repo.refs[branch_ref] = commit.id
    return commit.id.decode("ascii")


def _current_branch_ref(repo: Repo) -> bytes:
    try:
        chain, _sha = repo.refs.follow(b"HEAD")
        return chain[-1]
    except KeyError:
        return _branch_ref(DEFAULT_BRANCH)


def current_branch(folder: Path) -> str | None:
    """The project's currently checked-out branch name, or ``None`` if it has no history yet."""
    if not is_initialized(folder):
        return None
    ref = _current_branch_ref(_open(folder))
    prefix = b"refs/heads/"
    return ref[len(prefix):].decode("utf-8") if ref.startswith(prefix) else None


def list_branches(folder: Path) -> list[str]:
    if not is_initialized(folder):
        return []
    repo = _open(folder)
    prefix = b"refs/heads/"
    return sorted(
        ref[len(prefix):].decode("utf-8") for ref in repo.refs.allkeys() if ref.startswith(prefix)
    )


_BRANCH_NAME_DISALLOWED = re.compile(r"[^a-z0-9_-]+")


def sanitize_branch_name(name: str) -> str:
    """Normalizes a user-typed branch name to this shadow VCS's own naming rule (PROMPT.md: "please
    make sure branches are saved non-capitalised and with only - or _ and no spaces or special
    chars") -- lower-cased, with every run of whitespace collapsed to a single ``-`` and every
    remaining character outside ``[a-z0-9_-]`` simply dropped (not replaced -- a name like
    ``"Fix Bug #42!"`` becomes ``"fix-bug-42"``, not ``"fix-bug-42-"``). Applied by
    :func:`create_branch` to every name it's given, so a branch can never be saved any other way,
    regardless of which caller (typed by hand, or a future scripted one) asked for it.
    """
    lowered = name.strip().lower()
    collapsed_whitespace = re.sub(r"\s+", "-", lowered)
    return _BRANCH_NAME_DISALLOWED.sub("", collapsed_whitespace)


def create_branch(folder: Path, name: str, *, source: str | None = None) -> str:
    """Creates a new branch named ``name`` and switches to it (PROMPT.md: "also ability to create a
    new branch") -- matching plain git's own ``checkout -b`` behavior rather than leaving the user
    on their prior branch having to switch a second time. ``name`` is first run through
    :func:`sanitize_branch_name`; the *sanitized* name is what's actually created (and returned).

    Args:
        source: A branch name or a :class:`Snapshot.sha` to branch off of instead of whatever's
            currently checked out (PROMPT.md: "make new branch trigger a drop down also providing a
            New Branch from option") -- ``None`` (the default) keeps the original "off the current
            one" behavior.

    Returns:
        The sanitized branch name actually created.

    Raises:
        ValueError: ``name`` sanitizes to empty, a branch by that (sanitized) name already exists,
            or ``source`` is given but doesn't name a known branch or snapshot.
    """
    sanitized = sanitize_branch_name(name)
    if not sanitized:
        raise ValueError("Branch name cannot be empty.")
    repo = _open(folder)
    ref = _branch_ref(sanitized)
    if ref in repo.refs:
        raise ValueError(f'A branch named "{sanitized}" already exists.')
    if source is None:
        start_sha = repo.refs[b"HEAD"]
    else:
        start_sha = _resolve_ref(repo, source)
        if start_sha is None:
            raise ValueError(f'Unknown branch or snapshot: "{source}".')
    repo.refs[ref] = start_sha
    repo.refs.set_symbolic_ref(b"HEAD", ref)
    if source is not None:
        commit = repo.object_store[start_sha]
        _checkout_tree(repo, commit.tree, folder)
        _write_staged_snapshot(folder, {})
    _logger.info("created and switched to branch %r (from %r) in %s", sanitized, source, folder)
    return sanitized


def switch_branch(folder: Path, name: str) -> None:
    """Switches to branch ``name``, restoring the project folder's own files on disk to match its
    last snapshot (PROMPT.md: "it should be possible (via the panel) to change and switch
    versions/branches").

    This overwrites/deletes real files -- callers are responsible for warning the user first (and
    for snapshotting/saving anything they want kept that isn't already in history: this only ever
    restores what was actually committed). Also clears the staging area (see :func:`stage`) --
    whatever was staged referred to edits against the *previous* branch's own working tree, which
    this just replaced wholesale.

    Raises:
        ValueError: No branch named ``name`` exists.
    """
    repo = _open(folder)
    ref = _branch_ref(name)
    if ref not in repo.refs:
        raise ValueError(f'No branch named "{name}".')
    commit = repo.object_store[repo.refs[ref]]
    _checkout_tree(repo, commit.tree, folder)
    repo.refs.set_symbolic_ref(b"HEAD", ref)
    _write_staged_snapshot(folder, {})
    _logger.info("switched branch to %r in %s", name, folder)


def delete_branch(folder: Path, name: str) -> None:
    """Deletes branch ``name`` (PROMPT.md: "add any other functionality you think may help the
    user manage the project using vcs" -- the natural cleanup counterpart to :func:`create_branch`).
    Never deletes the currently checked-out branch (nothing left to have switched to first) or the
    last remaining branch (a project always needs at least one).

    Raises:
        ValueError: No branch named ``name`` exists, it's the current branch, or it's the only one.
    """
    repo = _open(folder)
    ref = _branch_ref(name)
    if ref not in repo.refs:
        raise ValueError(f'No branch named "{name}".')
    if name == current_branch(folder):
        raise ValueError("Can't delete the current branch -- switch to another branch first.")
    if len(list_branches(folder)) <= 1:
        raise ValueError("Can't delete the only branch.")
    del repo.refs[ref]
    _logger.info("deleted branch %r in %s", name, folder)


class MergeConflictError(ValueError):
    """:func:`merge_branch` couldn't complete automatically -- ``paths`` lists every file both
    branches changed *differently* since their own common ancestor, which this shadow VCS has no
    interactive conflict-resolution UI to let the user pick a winner for (unlike git's own
    conflict-marker-in-the-file approach). The merge itself never happened -- nothing on disk or in
    history changed -- so resolving this means picking one side by hand (e.g. :func:`restore_snapshot`
    to the branch whose version should win for each conflicting path, or hand-editing it) and trying
    the merge again once every conflicting path no longer disagrees.
    """

    def __init__(self, paths: list[str]) -> None:
        self.paths = paths
        super().__init__(
            "Merge conflict in: " + ", ".join(paths) + " -- resolve by hand (pick one side's "
            "version for each) and try again."
        )


def merge_branch(folder: Path, source: str) -> str:
    """Merges branch ``source`` into the current branch -- PROMPT.md: "we also need buttons/
    functionality to: ... merge branch (this will need History Graph update to show merging of
    branches)" (see :func:`graph_history`'s own multi-parent :attr:`Snapshot.parents` support).

    Fast-forwards (moves the current branch's own ref straight to ``source``'s tip, checking out its
    tree -- no merge commit at all) when the current branch's own ``HEAD`` is a plain ancestor of
    ``source``, i.e. nothing unique on the current branch to preserve alongside it. Otherwise
    attempts a real three-way merge (via ``dulwich.merge.Merger``, the same machinery real git
    itself is built on) against the two branches' own most recent common ancestor: a path only one
    side touched takes that side's version outright; recurses into subtrees so non-overlapping
    changes in different files never conflict just for sharing a directory. A path *both* sides
    changed differently raises :class:`MergeConflictError` instead of guessing -- this shadow VCS
    has no interactive resolution UI, so an unmergeable path stops the whole merge rather than
    silently picking a side.

    Also clears the staging area (see :func:`stage`) on either path, same reasoning as
    :func:`switch_branch`'s own docstring -- the working tree just changed wholesale.

    Raises:
        ValueError: ``folder`` has no history yet, ``source`` doesn't name a known branch, or
            ``source`` is already the current branch.
        MergeConflictError: Both branches changed some of the same paths differently.
    """
    if not is_initialized(folder):
        raise ValueError("This project has no history yet.")
    repo = _open(folder)
    current = current_branch(folder)
    if current is None:
        raise ValueError("No branch is currently checked out.")
    if source == current:
        raise ValueError(f'"{source}" is already the current branch.')
    source_ref = _branch_ref(source)
    if source_ref not in repo.refs:
        raise ValueError(f'No branch named "{source}".')

    from dulwich.graph import can_fast_forward, find_merge_base
    from dulwich.merge import Merger

    ours_sha = repo.refs[_current_branch_ref(repo)]
    theirs_sha = repo.refs[source_ref]

    if can_fast_forward(repo, ours_sha, theirs_sha):
        commit_obj = repo.object_store[theirs_sha]
        _checkout_tree(repo, commit_obj.tree, folder)
        repo.refs[_current_branch_ref(repo)] = theirs_sha
        _write_staged_snapshot(folder, {})
        _logger.info("fast-forwarded %r to %r in %s", current, source, folder)
        return theirs_sha.decode("ascii")

    base_ids = find_merge_base(repo, [ours_sha, theirs_sha])
    base_tree = repo.object_store[base_ids[0]].tree if base_ids else None
    merger = Merger(repo.object_store)
    merged_tree, conflicts = merger.merge_trees(
        repo.object_store[base_tree] if base_tree is not None else None,
        repo.object_store[repo.object_store[ours_sha].tree],
        repo.object_store[repo.object_store[theirs_sha].tree],
    )
    if conflicts:
        raise MergeConflictError(sorted(path.decode("utf-8") for path in conflicts))

    repo.object_store.add_object(merged_tree)
    sha = _commit(repo, merged_tree.id, f"Merge branch '{source}' into {current}", extra_parents=[theirs_sha])
    _checkout_tree(repo, merged_tree.id, folder)
    _write_staged_snapshot(folder, {})
    _logger.info("merged %r into %r in %s (%s)", source, current, folder, sha)
    return sha


def _checkout_tree(repo: Repo, tree_sha: bytes, folder: Path) -> None:
    wanted = _flat_tree_blobs(repo, tree_sha)

    for rel, blob_sha in wanted.items():
        dest = folder / rel
        if _should_skip(dest, folder):
            continue  # a personal file an older snapshot still carries is never put back over the user's
        dest.parent.mkdir(parents=True, exist_ok=True)
        blob = repo.object_store[blob_sha]
        dest.write_bytes(blob.data)

    for rel, real_path in _walk_files(folder).items():
        if rel not in wanted:
            real_path.unlink(missing_ok=True)

    for path in sorted((p for p in folder.rglob("*") if p.is_dir()), reverse=True):
        if _should_skip(path, folder):
            continue
        try:
            path.rmdir()
        except OSError:
            pass  # not empty -- still in use


@dataclass
class UncommittedFile:
    """One file that differs between the current on-disk working tree and ``HEAD`` -- VSCode-style
    "uncommitted changes" (PROMPT.md: "we want to add committed changes and uncommitted
    changes[;] when there are uncommitted changes in the repo there should be a notification icon
    with the number of uncommitted changes")."""

    path: str
    #: ``"added"``, ``"removed"`` or ``"modified"`` -- same convention as :class:`FileDiff` below.
    change_type: str
    #: Whether this path is in the staging area (PROMPT.md, a later pass: "please then make it so
    #: that changes should be staged, and then committed") -- see :func:`stage`/:func:`commit`.
    staged: bool = False


_STAGE_FILENAME = "stage.json"


def _stage_file(folder: Path) -> Path:
    return history_dir(folder) / _STAGE_FILENAME


def _read_staged_snapshot(folder: Path) -> dict[str, str | None]:
    """The raw, persisted staging area -- every staged path's own snapshot, keyed by path, each
    value either a blob's own hex sha (the path's content *at the moment it was staged*) or ``None``
    for a staged deletion. Not pruned against what's *actually* still uncommitted (a path staged and
    then hand-reverted back to match ``HEAD`` stays listed here until something explicitly unstages
    it) -- callers that care whether a staged path is still real should cross-reference
    :func:`uncommitted_changes` instead, which already does that (see its own ``staged`` field)."""
    try:
        raw = json.loads(_stage_file(folder).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dict(raw)


def _write_staged_snapshot(folder: Path, snapshot: dict[str, str | None]) -> None:
    _stage_file(folder).write_text(json.dumps(snapshot, sort_keys=True), encoding="utf-8")


def staged_paths(folder: Path) -> set[str]:
    """Every path currently staged, regardless of its own snapshot content -- a plain convenience
    view over :func:`_read_staged_snapshot` for callers that only care *which* paths are staged, not
    what they're staged at."""
    return set(_read_staged_snapshot(folder))


def stage(folder: Path, paths: list[str]) -> None:
    """Stages ``paths`` -- PROMPT.md: "in the changes it should be possible to right click the file
    and then see: ... stage changes (or unstage changes)". Snapshots each path's *current* on-disk
    content into this shadow repo's own object store right now (PROMPT.md, a later pass: "when a
    change is staged is essentially snapshotted") -- a further on-disk edit after staging never
    silently updates what's about to be committed; it simply becomes a new, separate uncommitted
    change on top of the snapshot (see :func:`uncommitted_changes`'s own docstring). Staging an
    already-staged path again *replaces* its snapshot with the current on-disk content, same as a
    second ``git add`` would (PROMPT.md: "the new staged changes should overwrite as with normal
    git"). Never validates ``paths`` are actually uncommitted -- staging a path that isn't is
    harmless, it just won't show up as a staged change (see :func:`uncommitted_changes`)."""
    if not paths:
        return
    repo = _open(folder)
    snapshot = _read_staged_snapshot(folder)
    for rel_path in paths:
        real_path = folder / rel_path
        if real_path.is_file():
            blob = Blob.from_string(real_path.read_bytes())
            repo.object_store.add_object(blob)
            snapshot[rel_path] = blob.id.decode("ascii")
        else:
            snapshot[rel_path] = None  # staged as a deletion
    _write_staged_snapshot(folder, snapshot)


def unstage(folder: Path, paths: list[str]) -> None:
    """Removes ``paths`` from the staging area, discarding their own recorded snapshot -- the
    on-disk content itself is untouched, so an unstaged path simply reappears as a plain (unstaged)
    uncommitted change if it still differs from ``HEAD``. A no-op for a path that was never staged."""
    snapshot = _read_staged_snapshot(folder)
    for rel_path in paths:
        snapshot.pop(rel_path, None)
    _write_staged_snapshot(folder, snapshot)


def stage_all(folder: Path) -> None:
    """Stages every currently uncommitted path (staged or not) at its own current on-disk content --
    "Stage All". Re-snapshots an already-staged-but-further-edited path too, same as ``git add -A``
    would, not just the ones not yet staged at all."""
    stage(folder, sorted({c.path for c in uncommitted_changes(folder)}))


def discard_uncommitted_change(folder: Path, rel_path: str) -> None:
    """Reverts ``rel_path`` on disk back to its own ``HEAD`` content (a newly-added file with no
    ``HEAD`` copy is deleted instead) -- PROMPT.md: "in the changes it should be possible to right
    click the file and then see: ... discard changes". Also unstages it, if staged -- there's
    nothing left to stage once the change itself is gone.

    Raises:
        ValueError: ``folder`` has no history yet.
    """
    if not is_initialized(folder):
        raise ValueError("This project has no history yet.")
    repo = _open(folder)
    parent = _head_commit(repo)
    blobs = _flat_tree_blobs(repo, parent.tree if parent is not None else None)
    real_path = folder / rel_path
    blob_sha = blobs.get(rel_path)
    if blob_sha is None:
        real_path.unlink(missing_ok=True)
    else:
        real_path.parent.mkdir(parents=True, exist_ok=True)
        real_path.write_bytes(repo.object_store[blob_sha].data)
    unstage(folder, [rel_path])


def _staged_effective_tree(
    repo: Repo, parent_tree: bytes | None, snapshot: dict[str, str | None]
) -> bytes | None:
    """``parent_tree`` (``HEAD``'s own tree) with every staged path's own snapshot overlaid --
    git's "index" tree, equivalent: a staged deletion (snapshot value ``None``) removes that path,
    a staged blob sha replaces it, and every other path is carried over from ``HEAD`` untouched.
    What :func:`uncommitted_changes` diffs ``HEAD`` against for the "Staged Changes" half, and what
    :func:`commit` actually commits."""
    merged: dict[str, bytes] = dict(_flat_tree_blobs(repo, parent_tree))
    for rel_path, sha_hex in snapshot.items():
        if sha_hex is None:
            merged.pop(rel_path, None)
        else:
            merged[rel_path] = sha_hex.encode("ascii")
    return _build_tree(repo, merged)


def uncommitted_changes(folder: Path) -> list[UncommittedFile]:
    """Every file that differs from its own last commit (``HEAD``) -- either because it's staged
    (frozen at whatever content it had when :func:`stage` snapshotted it) or because the current
    on-disk content itself differs from that staged snapshot (or from ``HEAD``, for a path never
    staged at all) -- sorted by path. What the Git panel's own uncommitted-changes badge counts, and
    what :func:`stage`/:func:`commit` act on. Empty if ``folder`` has no history yet, or if neither
    the staging area nor the working tree differs from ``HEAD`` at all.

    A path staged and then edited again on disk appears *twice*: one ``staged=True`` entry (the
    snapshot, unaffected by the later edit) and one ``staged=False`` entry (the edit itself, diffed
    against the snapshot rather than ``HEAD`` -- see this module's own docstring on "when a change is
    staged is essentially snapshotted"), same as VSCode's own split "Staged Changes"/"Changes" lists.

    Building the comparison trees has the same side effect :func:`commit`/:func:`stamp` already have
    (writing loose blob/tree objects into the shadow repo's own object store even when nothing ends
    up committed) -- acceptable here for the same reason it already was there: "what would a commit
    look like right now" can only ever be answered by actually building that tree.
    """
    if not is_initialized(folder):
        return []
    from dulwich.diff_tree import tree_changes

    repo = _open(folder)
    parent = _head_commit(repo)
    parent_tree = parent.tree if parent is not None else None
    snapshot = _read_staged_snapshot(folder)
    staged_tree = _staged_effective_tree(repo, parent_tree, snapshot) if snapshot else parent_tree
    working_tree = _build_tree(repo, _walk_files(folder))

    results: list[UncommittedFile] = []
    if staged_tree != parent_tree:
        results.extend(
            UncommittedFile(
                path=(change.new or change.old).path.decode("utf-8"),
                change_type={"add": "added", "delete": "removed"}.get(change.type, "modified"),
                staged=True,
            )
            for change in tree_changes(repo.object_store, parent_tree, staged_tree)
        )
    if working_tree != staged_tree:
        results.extend(
            UncommittedFile(
                path=(change.new or change.old).path.decode("utf-8"),
                change_type={"add": "added", "delete": "removed"}.get(change.type, "modified"),
                staged=False,
            )
            for change in tree_changes(repo.object_store, staged_tree, working_tree)
        )
    return sorted(results, key=lambda f: f.path)


def _normalize_newlines(text: str | None) -> str | None:
    """``"\\r\\n"``/``"\\r"`` -> ``"\\n"``, or ``None`` through unchanged -- a git blob preserves
    whatever bytes were actually committed ("\\r\\n" on a file this shadow VCS snapshotted from a
    Windows disk write), unlike :meth:`Path.read_text`'s own universal-newlines decoding. Comparing
    both sides of a diff through this stops every single line reading as "changed" purely over a
    line-ending difference nobody actually made -- same reasoning/technique as
    ``in_reach.app.rvt.decompile.normalize_script_text``."""
    return text if text is None else text.replace("\r\n", "\n").replace("\r", "\n")


def _blob_text_at_path(repo: Repo, tree_sha: bytes | None, rel_path: str) -> str | None:
    """``rel_path``'s own decoded blob text within ``tree_sha`` -- ``None`` if ``tree_sha`` is
    ``None``, ``rel_path`` doesn't exist in it, or the blob isn't valid UTF-8 (binary)."""
    if tree_sha is None:
        return None
    from dulwich.object_store import tree_lookup_path

    try:
        _mode, sha = tree_lookup_path(repo.object_store.__getitem__, tree_sha, rel_path.encode("utf-8"))
    except KeyError:
        return None
    return _decode_blob(repo, sha)


def uncommitted_file_diff(folder: Path, rel_path: str) -> tuple[str | None, str | None]:
    """``(old_text, new_text)`` for one uncommitted file (one of :func:`uncommitted_changes`' own
    ``.path`` entries) -- what the Git panel's own side-by-side diff tab shows when a changed file
    is clicked (PROMPT.md: "when clicking on changes to a file (in the changes tab) a tab should
    appear showing the original on the left and highlighted changes on the right (like vscode
    git)"). ``old_text`` is ``rel_path``'s own content at ``HEAD`` (``None`` for a newly added file,
    which has no ``HEAD`` copy at all); ``new_text`` is its current on-disk content (``None`` for a
    removed file, which no longer exists on disk at all). Either side is also ``None`` if it can't
    be decoded as UTF-8 text (a binary file) -- the caller decides how to present that, same
    "binary, not diffable as text" treatment :func:`diff`'s own ``FileDiff.diff_text`` gives it.

    Both ``None`` if ``folder`` has no history yet, or if ``rel_path`` isn't actually uncommitted
    (nothing to show) -- callers should already know this from :func:`uncommitted_changes` before
    calling this at all, but this doesn't raise over a stale/wrong path regardless.
    """
    if not is_initialized(folder):
        return None, None
    repo = _open(folder)
    parent = _head_commit(repo)
    old_text = _blob_text_at_path(repo, parent.tree if parent is not None else None, rel_path)
    real_path = folder / rel_path
    new_text = None
    if real_path.is_file():
        try:
            new_text = real_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            new_text = None
    return _normalize_newlines(old_text), _normalize_newlines(new_text)


def ref_file_diff(folder: Path, ref_a: str, ref_b: str, rel_path: str) -> tuple[str | None, str | None]:
    """``(old_text, new_text)`` for ``rel_path`` between ``ref_a`` and ``ref_b`` (each a branch name
    or a :class:`Snapshot.sha`, same as :func:`diff`) -- what the Compare window's own per-file diff
    view shows for a selected changed file (PROMPT.md, a later pass: "please then add text
    colourings and line numbers in the compare window to make the text and changes clearer and more
    visually appealing" -- reuses :class:`~in_reach_ide.diff_view.DiffViewWidget`, the same
    line-numbered, syntax-highlighted view :func:`uncommitted_file_diff` already feeds the Changes
    tab's own diff view). ``None`` on either side means ``rel_path`` doesn't exist there (added/
    removed) or isn't valid UTF-8 text (binary), same as :func:`uncommitted_file_diff`.

    Raises:
        ValueError: Either ``ref_a`` or ``ref_b`` doesn't name a known branch or snapshot.
    """
    repo = _open(folder)
    sha_a = _resolve_ref(repo, ref_a)
    sha_b = _resolve_ref(repo, ref_b)
    if sha_a is None or sha_b is None:
        unknown = ref_a if sha_a is None else ref_b
        raise ValueError(f'Unknown branch or snapshot: "{unknown}".')
    tree_a = repo.object_store[sha_a].tree
    tree_b = repo.object_store[sha_b].tree
    old_text = _blob_text_at_path(repo, tree_a, rel_path)
    new_text = _blob_text_at_path(repo, tree_b, rel_path)
    return _normalize_newlines(old_text), _normalize_newlines(new_text)


def commit(folder: Path, message: str) -> str:
    """Snapshots ``folder``'s *staged* changes only (PROMPT.md, a later pass: "changes should be
    staged, and then committed") as a plain, user-authored checkpoint -- the everyday counterpart to
    :func:`stamp`; see this module's own docstring for what tells the two apart. An unstaged
    uncommitted change is left exactly as it was: still uncommitted, untouched on disk, simply not
    part of this commit. Commits exactly each staged path's own *snapshotted* content (from the
    moment it was staged, see :func:`stage`'s own docstring) -- never whatever's on disk right now,
    so an edit made after staging is never accidentally swept into this commit; it stays a separate
    uncommitted change afterward.

    Raises:
        ValueError: ``message`` is empty, ``folder`` has no history yet, or nothing is staged (or
            every staged path's own snapshot turned out to already match ``HEAD`` -- same "no empty
            commits" rule :func:`uncommitted_changes` itself uses).
    """
    if not message.strip():
        raise ValueError("A commit needs a commit message.")
    if not is_initialized(folder):
        raise ValueError("This project has no history yet.")
    repo = _open(folder)
    parent = _head_commit(repo)
    parent_tree = parent.tree if parent is not None else None
    snapshot = _read_staged_snapshot(folder)
    if not snapshot:
        raise ValueError("Nothing staged to commit -- stage changes first.")
    tree_sha = _staged_effective_tree(repo, parent_tree, snapshot)
    if tree_sha is None or tree_sha == parent_tree:
        raise ValueError("Nothing to commit -- the working tree matches the last commit.")
    sha = _commit(repo, tree_sha, message)
    unstage(folder, list(snapshot))
    _logger.info("committed %s in %s (%r, %d staged file(s))", sha, folder, message, len(snapshot))
    return sha


def stamp(folder: Path, message: str, *, version: str | None = None) -> str:
    """Snapshots ``folder``'s current on-disk state as a user-labelled release (PROMPT.md:
    "ability for a user to stamp a release (which takes a 'commit message')") -- always creates a
    commit, even if nothing changed since the last one, so a stamp always has its own addressable
    point in history to switch back to later regardless of whether anything was actually edited
    since (see :func:`commit`'s own docstring for the everyday, change-required counterpart).

    Args:
        version: This stamp's own ``"{major}.{minor}.{patch}"`` version number (PROMPT.md: "we also
            want to add the functionality for version numbers using major, minor, patch with
            stamped releases") -- ``None`` (the default) stamps without one, same as before version
            tracking existed; the Git panel's own "Stamp Release" dialog always supplies one.

    Raises:
        ValueError: ``message`` is empty, or ``folder`` has no history yet.
    """
    if not message.strip():
        raise ValueError("A stamp needs a commit message.")
    if not is_initialized(folder):
        raise ValueError("This project has no history yet.")
    repo = _open(folder)
    tree_sha = _build_tree(repo, _walk_files(folder))
    if tree_sha is None:
        parent = _head_commit(repo)
        tree_sha = parent.tree if parent is not None else None
    if tree_sha is None:
        raise ValueError("Nothing to stamp -- this project has no trackable files yet.")
    version_prefix = f"v{version} " if version else ""
    sha = _commit(repo, tree_sha, f"{_STAMP_PREFIX}{version_prefix}{message}")
    _logger.info("stamped %s in %s (v%s, %r)", sha, folder, version, message)
    return sha


_ACTIVE_ENV_PATH = b"script/env/active_env.txt"


def _env_in_tree(repo: Repo, tree_sha: bytes) -> str | None:
    from dulwich.object_store import tree_lookup_path

    try:
        _mode, sha = tree_lookup_path(repo.object_store.__getitem__, tree_sha, _ACTIVE_ENV_PATH)
    except (KeyError, NotADirectoryError):
        return None
    name = repo.object_store[sha].data.decode("utf-8", errors="replace").strip()
    return name or None


def env_at(folder: Path, sha: str) -> str | None:
    """The env the project was building with at commit ``sha`` (see :attr:`Snapshot.env`)."""
    repo = _open(folder)
    return _env_in_tree(repo, repo[sha.encode("ascii")].tree)


def _to_snapshot(commit_obj: Commit, *, parents: list[str] = (), branches: list[str] = (), repo: Repo | None = None) -> Snapshot:
    text = commit_obj.message.decode("utf-8")
    stamp_message: str | None = None
    version: str | None = None
    if text.startswith(_STAMP_PREFIX):
        rest = text[len(_STAMP_PREFIX):]
        version_match = _VERSION_PREFIX_RE.match(rest)
        if version_match:
            version, stamp_message = version_match.group(1), version_match.group(2)
        else:
            stamp_message = rest
    return Snapshot(
        sha=commit_obj.id.decode("ascii"),
        message=text,
        at=commit_obj.commit_time,
        stamp_message=stamp_message,
        version=version,
        parents=list(parents),
        branches=list(branches),
        env=_env_in_tree(repo, commit_obj.tree) if repo is not None else None,
    )


def last_stamp_version(folder: Path) -> str | None:
    """The most recent stamped release's own version number on the current branch (PROMPT.md:
    "stamping a version should reveal spin buttons centered at the present number"), or ``None`` if
    no stamp on this branch has one yet (no stamps at all, or every stamp so far predates version
    tracking) -- callers wanting a sensible default to seed the version-bump UI with should fall
    back to :data:`INITIAL_VERSION` themselves when this returns ``None``."""
    for snapshot in history(folder):
        if snapshot.is_stamp and snapshot.version:
            return snapshot.version
    return None


def version_already_stamped(folder: Path, version: str) -> bool:
    """Whether a stamped release with exactly this version already exists *anywhere* in history
    (every branch, not just the current one -- a version number is meant to be unique across the
    whole project, not per-branch) -- PROMPT.md: "if a user tries to submit the same version they
    should receive a warning (asking if they want to overwrite)"."""
    return any(s.is_stamp and s.version == version for s in graph_history(folder))


def history(folder: Path) -> list[Snapshot]:
    """Every snapshot on the current branch, newest first."""
    if not is_initialized(folder):
        return []
    repo = _open(folder)
    if _head_commit(repo) is None:
        return []
    # order="topo" (rather than dulwich's own default, "date"), since a commit's own commit_time
    # has only 1-second resolution -- plenty of same-second commits (a scripted setup, or a merge
    # commit created right after both the commits it merges) tie on that alone, and a plain
    # date-ordered walk doesn't guarantee a commit comes before its own parents when ties like that
    # happen. Topological order does: a commit is never returned before every one of its own
    # children has been.
    return [_to_snapshot(entry.commit, repo=repo) for entry in repo.get_walker(order="topo")]


def graph_history(folder: Path) -> list[Snapshot]:
    """Every snapshot across *every* branch, newest first, each with :attr:`Snapshot.parents`/
    :attr:`Snapshot.branches` populated -- what the Git panel's own commit-graph widget lays out
    into lanes (PROMPT.md: "show a git graph of commits, branches and stamps instead in vscode
    style"). :func:`history` stays the plain "current branch's own linear order" reader every
    pre-graph caller already used (comparing/restoring a snapshot doesn't care about the full DAG),
    so this is additive, not a replacement.
    """
    if not is_initialized(folder):
        return []
    repo = _open(folder)
    # More than one branch can share a tip (e.g. right after create_branch(), before either one has
    # its own new commit) -- a plain dict[sha, name] would silently drop every branch but the last
    # one seen for that sha, so this is dict[sha, list[name]] instead.
    branch_tips: dict[bytes, list[str]] = {}
    prefix = b"refs/heads/"
    for ref in repo.refs.allkeys():
        if ref.startswith(prefix):
            branch_tips.setdefault(repo.refs[ref], []).append(ref[len(prefix):].decode("utf-8"))
    if not branch_tips:
        return []
    snapshots = []
    # order="topo" -- see the identical comment in history() above; matters even more here since a
    # merge commit's own two parents are especially likely to share its exact commit_time.
    for entry in repo.get_walker(include=list(branch_tips.keys()), order="topo"):
        commit_obj = entry.commit
        snapshots.append(
            _to_snapshot(
                commit_obj,
                parents=[p.decode("ascii") for p in commit_obj.parents],
                branches=branch_tips.get(commit_obj.id, []),
                repo=repo,
            )
        )
    return snapshots


def last_saved_at(folder: Path) -> float | None:
    """When the most recent commit (plain or stamped) was made, or ``None``."""
    if not is_initialized(folder):
        return None
    commit = _head_commit(_open(folder))
    return commit.commit_time if commit is not None else None


def last_stamp(folder: Path) -> Snapshot | None:
    """The most recent stamped release on the current branch, or ``None`` if none has been made
    yet."""
    for snapshot in history(folder):
        if snapshot.is_stamp:
            return snapshot
    return None


# -- comparing branches/stamps (PROMPT.md: "view branch differences", "compare different stamped
# versions") ---------------------------------------------------------------------------------


@dataclass
class FileDiff:
    """One changed file between two snapshots."""

    path: str
    #: ``"added"``, ``"removed"`` or ``"modified"``.
    change_type: str
    #: A unified diff (``difflib``-style, ``---``/``+++``/``@@`` headers), or a plain one-line note
    #: for a file that isn't valid UTF-8 text (git blobs carry no encoding of their own, so a byte
    #: string that doesn't decode is treated as binary rather than guessed at).
    diff_text: str


def _looks_like_sha(text: str) -> bool:
    """Whether ``text`` is even shaped like a full 40-character hex object id -- checked before
    ever handing it to dulwich's own object store, which asserts (rather than raising a catchable
    ``KeyError``) on a name of any other length."""
    return len(text) == 40 and all(c in "0123456789abcdefABCDEF" for c in text)


def _resolve_ref(repo: Repo, ref: str) -> bytes | None:
    """Resolves ``ref`` -- a branch name or a raw commit sha (as every :class:`Snapshot.sha` is)
    -- to a commit sha, or ``None`` if it names neither. Letting either kind of string through the
    same call is what makes :func:`diff` equally able to compare two branches, two stamps, or a
    branch against a stamp, without the caller needing to know which."""
    branch_ref = _branch_ref(ref)
    if branch_ref in repo.refs:
        return repo.refs[branch_ref]
    if not _looks_like_sha(ref):
        return None
    sha = ref.encode("ascii")
    try:
        repo.object_store[sha]
    except KeyError:
        return None
    return sha


def _decode_blob(repo: Repo, sha: bytes | None) -> str | None:
    if sha is None:
        return None
    try:
        return repo.object_store[sha].data.decode("utf-8")
    except UnicodeDecodeError:
        return None  # binary


def _file_diff(repo: Repo, change) -> FileDiff:  # noqa: ANN001 -- dulwich.diff_tree.TreeChange
    old_entry, new_entry = change.old, change.new
    path = (new_entry or old_entry).path.decode("utf-8")
    change_type = {"add": "added", "delete": "removed"}.get(change.type, "modified")

    old_sha = old_entry.sha if old_entry is not None else None
    new_sha = new_entry.sha if new_entry is not None else None
    old_text = _decode_blob(repo, old_sha)
    new_text = _decode_blob(repo, new_sha)
    if old_text is None and new_text is None and (old_sha is not None or new_sha is not None):
        diff_text = f"Binary file {change_type}."
    else:
        import difflib

        diff_lines = difflib.unified_diff(
            (old_text or "").splitlines(keepends=True),
            (new_text or "").splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
        diff_text = "".join(diff_lines)
    return FileDiff(path=path, change_type=change_type, diff_text=diff_text)


def diff(folder: Path, ref_a: str, ref_b: str) -> list[FileDiff]:
    """Every file that differs between ``ref_a`` and ``ref_b`` (each a branch name or a
    :class:`Snapshot.sha`), sorted by path -- PROMPT.md: "they should be able to view branch
    differences[; and] compare different stamped versions". A file identical in both is simply
    absent from the result, same as ``git diff``'s own file list.

    Raises:
        ValueError: Either ``ref_a`` or ``ref_b`` doesn't name a known branch or snapshot.
    """
    from dulwich.diff_tree import tree_changes

    repo = _open(folder)
    sha_a = _resolve_ref(repo, ref_a)
    sha_b = _resolve_ref(repo, ref_b)
    if sha_a is None or sha_b is None:
        unknown = ref_a if sha_a is None else ref_b
        raise ValueError(f'Unknown branch or snapshot: "{unknown}".')
    tree_a = repo.object_store[sha_a].tree
    tree_b = repo.object_store[sha_b].tree
    changes = tree_changes(repo.object_store, tree_a, tree_b)
    return sorted((_file_diff(repo, change) for change in changes), key=lambda d: d.path)


def _commit_and_parent_tree(repo: Repo, sha: str) -> tuple[Commit, bytes | None]:
    """``(commit, parent's own tree sha)`` for ``sha`` -- ``None`` for the second element on a root
    commit (no parent at all, i.e. diff against an empty tree). Shared by
    :func:`commit_files_changed`/:func:`commit_file_diff`.

    Raises:
        ValueError: ``sha`` doesn't name a known commit.
    """
    if not _looks_like_sha(sha):
        raise ValueError(f'Unknown snapshot: "{sha}".')
    try:
        commit_obj = repo.object_store[sha.encode("ascii")]
    except KeyError as exc:
        raise ValueError(f'Unknown snapshot: "{sha}".') from exc
    parent_tree = repo.object_store[commit_obj.parents[0]].tree if commit_obj.parents else None
    return commit_obj, parent_tree


def commit_files_changed(folder: Path, sha: str) -> list[FileDiff]:
    """Every file changed *by* commit ``sha`` itself -- the diff between it and its own first
    parent (or against an empty tree, for a root commit with no parent at all) -- PROMPT.md: "please
    make it so that when clicking in history on commits - it extends to show a list of files
    changed". Sorted by path, same convention as :func:`diff`.

    Raises:
        ValueError: ``sha`` doesn't name a known commit.
    """
    from dulwich.diff_tree import tree_changes

    repo = _open(folder)
    commit_obj, parent_tree = _commit_and_parent_tree(repo, sha)
    changes = tree_changes(repo.object_store, parent_tree, commit_obj.tree)
    return sorted((_file_diff(repo, change) for change in changes), key=lambda d: d.path)


def commit_file_diff(folder: Path, sha: str, rel_path: str) -> tuple[str | None, str | None]:
    """``(old_text, new_text)`` for ``rel_path`` as changed *by* commit ``sha`` -- ``old_text`` is
    its own first parent's content (``None`` for a root commit, or a newly added file), ``new_text``
    is this commit's own content (``None`` if this commit removed it). What the Git panel's own
    History section feeds :class:`~in_reach_ide.unified_diff_view.UnifiedDiffViewWidget` when a
    changed file is clicked for a selected commit. Same shape as :func:`ref_file_diff`/
    :func:`uncommitted_file_diff`.

    Raises:
        ValueError: ``sha`` doesn't name a known commit.
    """
    repo = _open(folder)
    commit_obj, parent_tree = _commit_and_parent_tree(repo, sha)
    old_text = _blob_text_at_path(repo, parent_tree, rel_path)
    new_text = _blob_text_at_path(repo, commit_obj.tree, rel_path)
    return _normalize_newlines(old_text), _normalize_newlines(new_text)


def restore_snapshot(folder: Path, sha: str) -> None:
    """Restores the project's files on disk to match a specific past snapshot -- any stamp or
    plain commit, on any branch -- without switching branches (PROMPT.md: "add any other
    functionality you think may help the user manage the project using vcs"; pairs with comparing
    stamped versions -- see something you like in an old stamp, restore it). Nothing already
    committed is ever lost: the restore itself is immediately recorded as a new commit on the
    *current* branch (a real, descriptive, auto-generated message -- not the old anonymous
    ``"autosave"`` this module used to stamp every plain commit with), so history only ever gains an
    entry, never rewrites one. A no-op commit-wise if ``sha`` already matches the current branch's
    own ``HEAD`` (nothing actually changes on disk either, in that case).

    This overwrites/deletes real files on disk -- same caller responsibility as
    :func:`switch_branch`'s own docstring.

    Raises:
        ValueError: ``sha`` doesn't name a known snapshot.
    """
    repo = _open(folder)
    if not _looks_like_sha(sha):
        raise ValueError(f'Unknown snapshot: "{sha}".')
    try:
        commit_obj = repo.object_store[sha.encode("ascii")]
    except KeyError as exc:
        raise ValueError(f'Unknown snapshot: "{sha}".') from exc
    _checkout_tree(repo, commit_obj.tree, folder)
    _write_staged_snapshot(folder, {})
    tree_sha = _build_tree(repo, _walk_files(folder))
    parent = _head_commit(repo)
    if tree_sha is not None and tree_sha != (parent.tree if parent is not None else None):
        new_sha = _commit(repo, tree_sha, f"Restored {sha[:8]}")
        _logger.info("restored snapshot %s in %s (new commit %s)", sha, folder, new_sha)
    else:
        _logger.info("restored snapshot %s in %s (already matches HEAD)", sha, folder)
