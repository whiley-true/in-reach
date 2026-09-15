"""A per-project shadow VCS history, backed by Dulwich (PROMPT.md: "vcs panel and dulwich
implementation").

Design follows the shadow-repo shape already designed (and partially shipped) in the prior
``in-reach-v2`` prototype, per this repo's own ``TO_IMPLEMENT_(LATEST).md`` (§0.1 item 9, §2, §9.6):
a *bare* git repository with no working tree of its own -- the real "working tree" is just whatever
currently sits on disk under the project folder. There is deliberately no on-disk git index/staging
area: every snapshot is built directly from a fresh recursive walk of the project folder (skipping
this history store itself and anything :func:`~in_reach.app.new_project.is_generated_file` already
knows is disposable build output), so a snapshot always reflects exactly what a user would see in
the Explorer right now.

Two kinds of snapshot share one commit history rather than two parallel mechanisms:

- **Traceable** (PROMPT.md: "every change should be traceable (but not stamped explicitly)") --
  :func:`record_change`, called on every file save. A plain, unlabelled commit; a no-op if nothing
  on disk actually changed since the last snapshot (no empty commits).
- **Stamped** (PROMPT.md: "ability for a user to stamp a release (which takes a 'commit
  message')") -- :func:`stamp`, always creates a commit (even if nothing changed since the last
  traceable one), carrying the user's own message. Stamps are told apart from traceable commits by
  a literal ``"stamp: "`` message prefix rather than a separate sidecar status file -- the commit
  log is already the one source of truth for "was this ever explicitly stamped," so there's nothing
  else to keep in sync with it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from dulwich.objects import Blob, Commit, Tree
from dulwich.repo import Repo

from in_reach.app import logging_setup
from in_reach.app.new_project import is_generated_file

_logger = logging_setup.get_logger(__name__)

HISTORY_DIRNAME = ".in-reach/history"
DEFAULT_BRANCH = "main"

_AUTHOR = b"in-reach <in-reach@local>"
_STAMP_PREFIX = "stamp: "
_AUTOSAVE_MESSAGE = "autosave"


@dataclass
class Snapshot:
    """One commit in a project's shadow history."""

    sha: str
    message: str
    at: float
    #: The user's own message, with the ``"stamp: "`` prefix stripped -- ``None`` for a plain
    #: traceable commit.
    stamp_message: str | None

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


def init(folder: Path) -> None:
    """Creates ``folder``'s shadow history repo and takes its first snapshot.

    PROMPT.md: "vcs should be started when a new blank project (either blank or from template)" --
    called once, right after :func:`~in_reach.app.new_project.create_gametype_project` finishes
    writing everything else a new project starts with, so there's always at least one snapshot (a
    branch/HEAD with nothing to diff against isn't useful) and the very first files a project ever
    had are themselves traceable.

    A no-op if ``folder`` already has a history repo (never re-initializes over one).
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
    record_change(folder, message=_AUTOSAVE_MESSAGE)
    _logger.info("initialized shadow VCS history for %s", folder)


def _should_skip(path: Path, folder: Path) -> bool:
    vcs_root = folder / ".in-reach"
    if path == vcs_root or vcs_root in path.parents:
        return True
    return is_generated_file(path.relative_to(folder))


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


def _build_tree(repo: Repo, files: dict[str, Path]) -> bytes | None:
    """Builds (and stores) a :class:`Tree` object per directory level from ``files``, bottom-up,
    returning the root tree's sha -- or ``None`` if ``files`` is empty (git has no way to represent
    an empty tree as a parent entry)."""
    root: dict[str, object] = {}
    for rel, real_path in files.items():
        parts = rel.split("/")
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})  # type: ignore[assignment]
        node[parts[-1]] = real_path

    def _write(node: dict[str, object]) -> bytes | None:
        tree = Tree()
        for name in sorted(node):
            value = node[name]
            if isinstance(value, dict):
                sub_sha = _write(value)
                if sub_sha is None:
                    continue
                tree.add(name.encode("utf-8"), 0o040000, sub_sha)
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


def _head_commit(repo: Repo) -> Commit | None:
    try:
        head_sha = repo.refs[b"HEAD"]
    except KeyError:
        return None
    return repo.object_store[head_sha]


def _commit(repo: Repo, tree_sha: bytes, message: str) -> str:
    parent = _head_commit(repo)
    commit = Commit()
    commit.tree = tree_sha
    commit.parents = [parent.id] if parent is not None else []
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


def create_branch(folder: Path, name: str) -> None:
    """Creates a new branch named ``name`` off the current one and switches to it (PROMPT.md:
    "also ability to create a new branch") -- matching plain git's own ``checkout -b`` behavior
    rather than leaving the user on their prior branch having to switch a second time.

    Raises:
        ValueError: ``name`` is empty, or a branch by that name already exists.
    """
    if not name.strip():
        raise ValueError("Branch name cannot be empty.")
    repo = _open(folder)
    ref = _branch_ref(name)
    if ref in repo.refs:
        raise ValueError(f'A branch named "{name}" already exists.')
    repo.refs[ref] = repo.refs[b"HEAD"]
    repo.refs.set_symbolic_ref(b"HEAD", ref)
    _logger.info("created and switched to branch %r in %s", name, folder)


def switch_branch(folder: Path, name: str) -> None:
    """Switches to branch ``name``, restoring the project folder's own files on disk to match its
    last snapshot (PROMPT.md: "it should be possible (via the panel) to change and switch
    versions/branches").

    This overwrites/deletes real files -- callers are responsible for warning the user first (and
    for snapshotting/saving anything they want kept that isn't already in history: this only ever
    restores what was actually committed).

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


def _checkout_tree(repo: Repo, tree_sha: bytes, folder: Path) -> None:
    wanted: dict[str, bytes] = {}

    def _walk(sha: bytes, prefix: str) -> None:
        tree = repo.object_store[sha]
        for entry in tree.iteritems():
            rel = f"{prefix}{entry.path.decode('utf-8')}"
            if entry.mode == 0o040000:
                _walk(entry.sha, f"{rel}/")
            else:
                wanted[rel] = entry.sha

    _walk(tree_sha, "")

    for rel, blob_sha in wanted.items():
        dest = folder / rel
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


def record_change(folder: Path, *, message: str = _AUTOSAVE_MESSAGE) -> str | None:
    """Snapshots ``folder``'s current on-disk state as a plain, unlabelled commit (PROMPT.md:
    "every change should be traceable (but not stamped explicitly)").

    A no-op (returns ``None``) if nothing has actually changed since the last snapshot, or if
    ``folder`` has no history yet (:func:`init` was never called for it) -- callers that always
    want a snapshot to exist regardless should call :func:`init` first.

    Returns:
        The new commit's sha, or ``None`` if nothing changed / there's no history to record into.
    """
    if not is_initialized(folder):
        return None
    repo = _open(folder)
    tree_sha = _build_tree(repo, _walk_files(folder))
    if tree_sha is None:
        return None
    parent = _head_commit(repo)
    if parent is not None and parent.tree == tree_sha:
        return None
    sha = _commit(repo, tree_sha, message)
    _logger.debug("recorded change %s in %s (%r)", sha, folder, message)
    return sha


def stamp(folder: Path, message: str) -> str:
    """Snapshots ``folder``'s current on-disk state as a user-labelled release (PROMPT.md:
    "ability for a user to stamp a release (which takes a 'commit message')") -- always creates a
    commit, even if nothing changed since the last traceable snapshot, so a stamp always has its
    own addressable point in history to switch back to later.

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
    sha = _commit(repo, tree_sha, f"{_STAMP_PREFIX}{message}")
    _logger.info("stamped %s in %s (%r)", sha, folder, message)
    return sha


def _to_snapshot(commit: Commit) -> Snapshot:
    text = commit.message.decode("utf-8")
    stamp_message = text[len(_STAMP_PREFIX):] if text.startswith(_STAMP_PREFIX) else None
    return Snapshot(sha=commit.id.decode("ascii"), message=text, at=commit.commit_time, stamp_message=stamp_message)


def history(folder: Path) -> list[Snapshot]:
    """Every snapshot on the current branch, newest first."""
    if not is_initialized(folder):
        return []
    repo = _open(folder)
    if _head_commit(repo) is None:
        return []
    return [_to_snapshot(entry.commit) for entry in repo.get_walker()]


def last_saved_at(folder: Path) -> float | None:
    """When the most recent snapshot (traceable or stamped) was taken, or ``None``."""
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


def restore_snapshot(folder: Path, sha: str) -> None:
    """Restores the project's files on disk to match a specific past snapshot -- any stamp or
    traceable commit, on any branch -- without switching branches (PROMPT.md: "add any other
    functionality you think may help the user manage the project using vcs"; pairs with comparing
    stamped versions -- see something you like in an old stamp, restore it). Nothing already
    committed is ever lost: the restore itself is immediately recorded as a new traceable snapshot
    on the *current* branch, so history only ever gains an entry, never rewrites one.

    This overwrites/deletes real files on disk -- same caller responsibility as
    :func:`switch_branch`'s own docstring.

    Raises:
        ValueError: ``sha`` doesn't name a known snapshot.
    """
    repo = _open(folder)
    if not _looks_like_sha(sha):
        raise ValueError(f'Unknown snapshot: "{sha}".')
    try:
        commit = repo.object_store[sha.encode("ascii")]
    except KeyError as exc:
        raise ValueError(f'Unknown snapshot: "{sha}".') from exc
    _checkout_tree(repo, commit.tree, folder)
    record_change(folder, message=f"restored {sha[:8]}")
    _logger.info("restored snapshot %s in %s", sha, folder)
