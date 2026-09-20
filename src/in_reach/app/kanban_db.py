"""SQLite-backed Kanban store (PROMPT.md: "a SQLite db in .in-reach folder which allows for one
database to be linked to many projects with many boards").

One database file, ``<in_reach_dir>/kanban.db`` -- the same root-level ``.in-reach`` folder every
gametype project in a window shares (see :func:`in_reach.app.project.get_project_dir`) -- holds
every project's boards: ``projects`` (one row per gametype project folder, keyed by the folder's own
generated id so a rename of the project's *title* never orphans its boards) -> ``boards`` -> ``board_columns``
-> ``cards``, plus per-board ``labels``. Background images (PROMPT.md: "custom image (which is added
to the repo)") are copied into ``<in_reach_dir>/kanban/backgrounds/`` and referenced by a path
relative to ``in_reach_dir``, so the database and the files it points at move together.

PROMPT.md: "we one day want to turn this into a full agile assistant so we should make sure to set
any required groundwork to later enable things like linking to features and documentations and
requiring successful compiles or test runs on certain cols" -- that groundwork is two small,
deliberately generic tables, present in the schema from day one so a later feature never needs a
migration just to start storing this: ``card_links`` (a card pointing at a feature/documentation
page/file/other card/commit, see the ``LINK_*`` constants) and ``column_rules`` (a gate on entering
a column, e.g. ``requires_compile``/``requires_tests``, see the ``RULE_*`` constants). Nothing
*enforces* a rule yet -- :meth:`KanbanStore.add_column_rule` only records it; whoever later moves a
card is the one that will check them.

Framework-agnostic on purpose (no Qt import), like the rest of :mod:`in_reach.app`.
"""

from __future__ import annotations

import inspect
import json
import shutil
import sqlite3
import weakref
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

DB_FILENAME = "kanban.db"
BACKGROUNDS_SUBDIR = Path("kanban") / "backgrounds"
SCHEMA_VERSION = 1

DEFAULT_BOARD_NAME = "Main Board"
DEFAULT_COLUMN_NAMES = ("To Do", "In Progress", "Done")

#: Offered when making a new label -- a plain, readable-on-dark/light set, nothing themed.
LABEL_COLORS = ("#4bce97", "#f5cd47", "#fea362", "#f87168", "#9f8fef", "#579dff")

LINK_FEATURE = "feature"
LINK_DOCUMENTATION = "documentation"
LINK_FILE = "file"
LINK_CARD = "card"
LINK_COMMIT = "commit"

RULE_REQUIRES_COMPILE = "requires_compile"
RULE_REQUIRES_TESTS = "requires_tests"

_SCHEMA = """
CREATE TABLE projects (
    id          INTEGER PRIMARY KEY,
    key         TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
CREATE TABLE boards (
    id                INTEGER PRIMARY KEY,
    project_id        INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name              TEXT NOT NULL,
    background_color  TEXT,
    background_image  TEXT,
    is_default        INTEGER NOT NULL DEFAULT 0,
    position          INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL
);
CREATE TABLE board_columns (
    id        INTEGER PRIMARY KEY,
    board_id  INTEGER NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
    name      TEXT NOT NULL,
    position  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE column_rules (
    id         INTEGER PRIMARY KEY,
    column_id  INTEGER NOT NULL REFERENCES board_columns(id) ON DELETE CASCADE,
    rule_type  TEXT NOT NULL,
    config     TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE cards (
    id           INTEGER PRIMARY KEY,
    column_id    INTEGER NOT NULL REFERENCES board_columns(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    position     INTEGER NOT NULL DEFAULT 0,
    done         INTEGER NOT NULL DEFAULT 0,
    done_at      TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE TABLE labels (
    id        INTEGER PRIMARY KEY,
    board_id  INTEGER NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
    name      TEXT NOT NULL,
    color     TEXT NOT NULL
);
CREATE TABLE card_labels (
    card_id   INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    label_id  INTEGER NOT NULL REFERENCES labels(id) ON DELETE CASCADE,
    PRIMARY KEY (card_id, label_id)
);
CREATE TABLE card_links (
    id          INTEGER PRIMARY KEY,
    card_id     INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    link_type   TEXT NOT NULL,
    target      TEXT NOT NULL,
    label       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
CREATE INDEX idx_boards_project ON boards(project_id);
CREATE INDEX idx_columns_board ON board_columns(board_id);
CREATE INDEX idx_cards_column ON cards(column_id);
CREATE INDEX idx_labels_board ON labels(board_id);
"""


@dataclass(frozen=True)
class Project:
    id: int
    key: str
    title: str


@dataclass(frozen=True)
class Board:
    id: int
    project_id: int
    name: str
    background_color: str | None
    background_image: str | None  # relative to the store's in_reach_dir
    is_default: bool
    position: int


@dataclass(frozen=True)
class Column:
    id: int
    board_id: int
    name: str
    position: int


@dataclass(frozen=True)
class Label:
    id: int
    board_id: int
    name: str
    color: str


@dataclass(frozen=True)
class Card:
    id: int
    column_id: int
    title: str
    description: str
    position: int
    done: bool
    done_at: str | None
    label_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class ColumnRule:
    id: int
    column_id: int
    rule_type: str
    config: dict


@dataclass(frozen=True)
class CardLink:
    id: int
    card_id: int
    link_type: str
    target: str
    label: str


@dataclass
class ColumnData:
    column: Column
    cards: list[Card] = field(default_factory=list)


@dataclass
class BoardData:
    """Everything one board view needs to render, fetched in one go by
    :meth:`KanbanStore.load_board`."""

    board: Board
    columns: list[ColumnData]
    labels: list[Label]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _board(row: sqlite3.Row) -> Board:
    return Board(
        id=row["id"],
        project_id=row["project_id"],
        name=row["name"],
        background_color=row["background_color"],
        background_image=row["background_image"],
        is_default=bool(row["is_default"]),
        position=row["position"],
    )


def _column(row: sqlite3.Row) -> Column:
    return Column(id=row["id"], board_id=row["board_id"], name=row["name"], position=row["position"])


def _label(row: sqlite3.Row) -> Label:
    return Label(id=row["id"], board_id=row["board_id"], name=row["name"], color=row["color"])


class KanbanStore:
    """One open connection to ``<in_reach_dir>/kanban.db``. Every mutating method commits before
    returning, so a crash never loses more than the call in flight."""

    def __init__(self, in_reach_dir: Path) -> None:
        self.in_reach_dir = Path(in_reach_dir)
        self.in_reach_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.in_reach_dir / DB_FILENAME
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._listeners: list[Callable[[], Callable[[], None] | None]] = []
        self._batch_depth = 0
        self._dirty_in_batch = False
        self._migrate()

    def close(self) -> None:
        self._conn.close()

    # -- change notification ----------------------------------------------------------------------

    def add_listener(self, callback: Callable[[], None]) -> None:
        """Calls ``callback()`` (no arguments) after every committed change -- how the sidebar
        panel and every open board view (including a split copy of one) stay in sync without
        knowing about each other. A bound method is held *weakly*, so a listener never keeps its
        widget alive; one whose owner has been deleted is dropped the next time it would fire."""
        if inspect.ismethod(callback):
            ref = weakref.WeakMethod(callback)
            self._listeners.append(ref)
        else:
            self._listeners.append(lambda cb=callback: cb)

    def remove_listener(self, callback: Callable[[], None]) -> None:
        self._listeners = [ref for ref in self._listeners if ref() != callback]

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Holds listener notifications until the outermost ``with`` exits, then fires them once --
        a drag-and-drop reorder touching several columns is one change to a watcher, not several."""
        self._batch_depth += 1
        try:
            yield
        finally:
            self._batch_depth -= 1
            if self._batch_depth == 0 and self._dirty_in_batch:
                self._dirty_in_batch = False
                self._notify()

    def _commit(self) -> None:
        self._conn.commit()
        if self._batch_depth:
            self._dirty_in_batch = True
        else:
            self._notify()

    def _notify(self) -> None:
        alive = []
        for ref in self._listeners:
            callback = ref()
            if callback is None:
                continue
            alive.append(ref)
            try:
                callback()
            except RuntimeError:
                # The listener's Qt object was deleted out from under its Python wrapper.
                alive.remove(ref)
        self._listeners = alive

    def _migrate(self) -> None:
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            self._conn.executescript(_SCHEMA)
            self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._conn.commit()

    # -- projects ---------------------------------------------------------------------------------

    def ensure_project(self, key: str, title: str = "") -> Project:
        """The ``projects`` row for ``key`` (a gametype project folder's own name), creating it
        first if this is the first time that project has touched the database. ``title`` is
        refreshed on every call, so it tracks the project's current display name.

        Deliberately commits *without* notifying listeners: registering a project is bookkeeping,
        not a change anyone watching a board list needs to redraw for -- and the sidebar panel calls
        this from inside its own listener, where a notification would re-enter it."""
        row = self._conn.execute("SELECT * FROM projects WHERE key = ?", (key,)).fetchone()
        if row is None:
            cursor = self._conn.execute(
                "INSERT INTO projects (key, title, created_at) VALUES (?, ?, ?)", (key, title, _now())
            )
            self._conn.commit()
            return Project(id=cursor.lastrowid, key=key, title=title)
        if title and title != row["title"]:
            self._conn.execute("UPDATE projects SET title = ? WHERE id = ?", (title, row["id"]))
            self._conn.commit()
        return Project(id=row["id"], key=key, title=title or row["title"])

    def list_projects(self) -> list[Project]:
        rows = self._conn.execute("SELECT * FROM projects ORDER BY id").fetchall()
        return [Project(id=r["id"], key=r["key"], title=r["title"]) for r in rows]

    # -- boards -----------------------------------------------------------------------------------

    def list_boards(self, project_id: int) -> list[Board]:
        rows = self._conn.execute(
            "SELECT * FROM boards WHERE project_id = ? ORDER BY position, id", (project_id,)
        ).fetchall()
        return [_board(r) for r in rows]

    def get_board(self, board_id: int) -> Board | None:
        row = self._conn.execute("SELECT * FROM boards WHERE id = ?", (board_id,)).fetchone()
        return _board(row) if row else None

    def default_board(self, project_id: int) -> Board | None:
        """The board flagged default for ``project_id`` -- falling back to its first board if none
        is (which can only happen through hand-editing the database), or ``None`` with no boards."""
        row = self._conn.execute(
            "SELECT * FROM boards WHERE project_id = ? ORDER BY is_default DESC, position, id LIMIT 1",
            (project_id,),
        ).fetchone()
        return _board(row) if row else None

    def ensure_default_board(self, project_id: int) -> Board:
        """The project's default board, creating a fresh :data:`DEFAULT_BOARD_NAME` one (seeded
        with :data:`DEFAULT_COLUMN_NAMES`) if the project has no boards at all yet."""
        board = self.default_board(project_id)
        return board if board is not None else self.create_board(project_id, DEFAULT_BOARD_NAME)

    def create_board(
        self, project_id: int, name: str, *, background_color: str | None = None, seed_columns: bool = True
    ) -> Board:
        """Adds a board to ``project_id`` -- the project's very first one becomes its default.
        ``seed_columns`` starts it with :data:`DEFAULT_COLUMN_NAMES` rather than empty."""
        name = self._clean_name(name, "Board")
        count = self._conn.execute(
            "SELECT COUNT(*) FROM boards WHERE project_id = ?", (project_id,)
        ).fetchone()[0]
        cursor = self._conn.execute(
            "INSERT INTO boards (project_id, name, background_color, is_default, position, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, name, background_color, 1 if count == 0 else 0, count, _now()),
        )
        board_id = cursor.lastrowid
        if seed_columns:
            for position, column_name in enumerate(DEFAULT_COLUMN_NAMES):
                self._conn.execute(
                    "INSERT INTO board_columns (board_id, name, position) VALUES (?, ?, ?)",
                    (board_id, column_name, position),
                )
        self._commit()
        return self.get_board(board_id)

    def rename_board(self, board_id: int, name: str) -> None:
        self._conn.execute("UPDATE boards SET name = ? WHERE id = ?", (self._clean_name(name, "Board"), board_id))
        self._commit()

    def set_default_board(self, board_id: int) -> None:
        board = self.get_board(board_id)
        if board is None:
            return
        self._conn.execute("UPDATE boards SET is_default = 0 WHERE project_id = ?", (board.project_id,))
        self._conn.execute("UPDATE boards SET is_default = 1 WHERE id = ?", (board_id,))
        self._commit()

    def delete_board(self, board_id: int) -> None:
        """Deletes ``board_id`` (and, by cascade, its columns/cards/labels), and its background
        image file if nothing else points at it. If it was the project's default, the project's
        first remaining board takes over."""
        board = self.get_board(board_id)
        if board is None:
            return
        self._conn.execute("DELETE FROM boards WHERE id = ?", (board_id,))
        remaining = self.list_boards(board.project_id)
        for position, other in enumerate(remaining):
            self._conn.execute("UPDATE boards SET position = ? WHERE id = ?", (position, other.id))
        if board.is_default and remaining:
            self._conn.execute("UPDATE boards SET is_default = 1 WHERE id = ?", (remaining[0].id,))
        self._commit()
        if board.background_image:
            self._discard_background_file(board.background_image)

    def set_board_background(self, board_id: int, *, color: str | None = None) -> None:
        """Sets a solid background colour (``None`` clears it) -- and drops any custom image, since
        a board has one background or the other, not both."""
        board = self.get_board(board_id)
        if board is None:
            return
        self._conn.execute(
            "UPDATE boards SET background_color = ?, background_image = NULL WHERE id = ?", (color, board_id)
        )
        self._commit()
        if board.background_image:
            self._discard_background_file(board.background_image)

    def set_board_background_image(self, board_id: int, source: Path) -> str:
        """Copies ``source`` into :data:`BACKGROUNDS_SUBDIR` (PROMPT.md: "custom image (which is
        added to the repo)") and points the board at the copy -- dropping any solid colour set
        before. Returns the stored, ``in_reach_dir``-relative path (``/``-separated).

        Raises:
            FileNotFoundError: ``source`` doesn't exist.
            KeyError: ``board_id`` isn't a real board.
        """
        board = self.get_board(board_id)
        if board is None:
            raise KeyError(board_id)
        source = Path(source)
        if not source.is_file():
            raise FileNotFoundError(source)
        backgrounds = self.in_reach_dir / BACKGROUNDS_SUBDIR
        backgrounds.mkdir(parents=True, exist_ok=True)
        target = backgrounds / f"board{board_id}-{source.name}"
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
        relative = target.relative_to(self.in_reach_dir).as_posix()
        self._conn.execute(
            "UPDATE boards SET background_image = ?, background_color = NULL WHERE id = ?", (relative, board_id)
        )
        self._commit()
        if board.background_image and board.background_image != relative:
            self._discard_background_file(board.background_image)
        return relative

    def resolve_background_image(self, board: Board) -> Path | None:
        """The on-disk file for ``board``'s custom background, or ``None`` if it has none (or the
        file has since gone missing)."""
        if not board.background_image:
            return None
        path = self.in_reach_dir / board.background_image
        return path if path.is_file() else None

    def _discard_background_file(self, relative: str) -> None:
        still_used = self._conn.execute(
            "SELECT 1 FROM boards WHERE background_image = ? LIMIT 1", (relative,)
        ).fetchone()
        if still_used:
            return
        try:
            (self.in_reach_dir / relative).unlink()
        except OSError:
            pass

    # -- columns ----------------------------------------------------------------------------------

    def list_columns(self, board_id: int) -> list[Column]:
        rows = self._conn.execute(
            "SELECT * FROM board_columns WHERE board_id = ? ORDER BY position, id", (board_id,)
        ).fetchall()
        return [_column(r) for r in rows]

    def board_id_of_column(self, column_id: int) -> int | None:
        """Which board ``column_id`` belongs to, or ``None`` if there's no such column."""
        row = self._conn.execute("SELECT board_id FROM board_columns WHERE id = ?", (column_id,)).fetchone()
        return row["board_id"] if row else None

    def add_column(self, board_id: int, name: str) -> Column:
        name = self._clean_name(name, "Column")
        count = self._conn.execute(
            "SELECT COUNT(*) FROM board_columns WHERE board_id = ?", (board_id,)
        ).fetchone()[0]
        cursor = self._conn.execute(
            "INSERT INTO board_columns (board_id, name, position) VALUES (?, ?, ?)", (board_id, name, count)
        )
        self._commit()
        return Column(id=cursor.lastrowid, board_id=board_id, name=name, position=count)

    def rename_column(self, column_id: int, name: str) -> None:
        self._conn.execute(
            "UPDATE board_columns SET name = ? WHERE id = ?", (self._clean_name(name, "Column"), column_id)
        )
        self._commit()

    def delete_column(self, column_id: int) -> None:
        """Deletes ``column_id`` and every card in it."""
        row = self._conn.execute("SELECT board_id FROM board_columns WHERE id = ?", (column_id,)).fetchone()
        if row is None:
            return
        self._conn.execute("DELETE FROM board_columns WHERE id = ?", (column_id,))
        for position, column in enumerate(self.list_columns(row["board_id"])):
            self._conn.execute("UPDATE board_columns SET position = ? WHERE id = ?", (position, column.id))
        self._commit()

    def move_column(self, column_id: int, new_position: int) -> None:
        row = self._conn.execute("SELECT board_id FROM board_columns WHERE id = ?", (column_id,)).fetchone()
        if row is None:
            return
        ids = [c.id for c in self.list_columns(row["board_id"])]
        ids.remove(column_id)
        ids.insert(max(0, min(new_position, len(ids))), column_id)
        for position, cid in enumerate(ids):
            self._conn.execute("UPDATE board_columns SET position = ? WHERE id = ?", (position, cid))
        self._commit()

    # -- cards ------------------------------------------------------------------------------------

    def _card(self, row: sqlite3.Row) -> Card:
        label_rows = self._conn.execute(
            "SELECT label_id FROM card_labels WHERE card_id = ? ORDER BY label_id", (row["id"],)
        ).fetchall()
        return Card(
            id=row["id"],
            column_id=row["column_id"],
            title=row["title"],
            description=row["description"],
            position=row["position"],
            done=bool(row["done"]),
            done_at=row["done_at"],
            label_ids=tuple(r["label_id"] for r in label_rows),
        )

    def list_cards(self, column_id: int) -> list[Card]:
        rows = self._conn.execute(
            "SELECT * FROM cards WHERE column_id = ? ORDER BY position, id", (column_id,)
        ).fetchall()
        return [self._card(r) for r in rows]

    def get_card(self, card_id: int) -> Card | None:
        row = self._conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        return self._card(row) if row else None

    def add_card(self, column_id: int, title: str, description: str = "") -> Card:
        title = self._clean_name(title, "Card")
        count = self._conn.execute(
            "SELECT COUNT(*) FROM cards WHERE column_id = ?", (column_id,)
        ).fetchone()[0]
        now = _now()
        cursor = self._conn.execute(
            "INSERT INTO cards (column_id, title, description, position, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (column_id, title, description, count, now, now),
        )
        self._commit()
        return self.get_card(cursor.lastrowid)

    def update_card(self, card_id: int, *, title: str | None = None, description: str | None = None) -> None:
        if title is not None:
            self._conn.execute("UPDATE cards SET title = ? WHERE id = ?", (self._clean_name(title, "Card"), card_id))
        if description is not None:
            self._conn.execute("UPDATE cards SET description = ? WHERE id = ?", (description, card_id))
        self._conn.execute("UPDATE cards SET updated_at = ? WHERE id = ?", (_now(), card_id))
        self._commit()

    def set_card_done(self, card_id: int, done: bool) -> None:
        self._conn.execute(
            "UPDATE cards SET done = ?, done_at = ?, updated_at = ? WHERE id = ?",
            (1 if done else 0, _now() if done else None, _now(), card_id),
        )
        self._commit()

    def delete_card(self, card_id: int) -> None:
        row = self._conn.execute("SELECT column_id FROM cards WHERE id = ?", (card_id,)).fetchone()
        if row is None:
            return
        self._conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))
        self._renumber_cards(row["column_id"])
        self._commit()

    def move_card(self, card_id: int, column_id: int, position: int | None = None) -> None:
        """Moves ``card_id`` to ``column_id`` at ``position`` (``None`` = the end)."""
        row = self._conn.execute("SELECT column_id FROM cards WHERE id = ?", (card_id,)).fetchone()
        if row is None:
            return
        old_column = row["column_id"]
        ids = [c.id for c in self.list_cards(column_id) if c.id != card_id]
        ids.insert(len(ids) if position is None else max(0, min(position, len(ids))), card_id)
        self._conn.execute("UPDATE cards SET column_id = ?, updated_at = ? WHERE id = ?", (column_id, _now(), card_id))
        for index, cid in enumerate(ids):
            self._conn.execute("UPDATE cards SET position = ? WHERE id = ?", (index, cid))
        if old_column != column_id:
            self._renumber_cards(old_column)
        self._commit()

    def set_column_cards(self, column_id: int, card_ids: list[int]) -> None:
        """Makes ``card_ids`` (in that order) exactly ``column_id``'s cards -- what a drag-and-drop
        reorder/move across columns reports back, one call per affected column. Any card in the
        list currently in another column is moved here; a card of this column missing from the
        list is left where it is (nothing here ever silently deletes)."""
        for index, cid in enumerate(card_ids):
            self._conn.execute(
                "UPDATE cards SET column_id = ?, position = ? WHERE id = ?", (column_id, index, cid)
            )
        self._commit()

    def _renumber_cards(self, column_id: int) -> None:
        for index, card in enumerate(self.list_cards(column_id)):
            self._conn.execute("UPDATE cards SET position = ? WHERE id = ?", (index, card.id))

    # -- labels -----------------------------------------------------------------------------------

    def list_labels(self, board_id: int) -> list[Label]:
        rows = self._conn.execute("SELECT * FROM labels WHERE board_id = ? ORDER BY id", (board_id,)).fetchall()
        return [_label(r) for r in rows]

    def create_label(self, board_id: int, name: str, color: str | None = None) -> Label:
        if color is None:
            count = self._conn.execute("SELECT COUNT(*) FROM labels WHERE board_id = ?", (board_id,)).fetchone()[0]
            color = LABEL_COLORS[count % len(LABEL_COLORS)]
        cursor = self._conn.execute(
            "INSERT INTO labels (board_id, name, color) VALUES (?, ?, ?)",
            (board_id, name.strip(), color),
        )
        self._commit()
        return Label(id=cursor.lastrowid, board_id=board_id, name=name.strip(), color=color)

    def update_label(self, label_id: int, *, name: str | None = None, color: str | None = None) -> None:
        if name is not None:
            self._conn.execute("UPDATE labels SET name = ? WHERE id = ?", (name.strip(), label_id))
        if color is not None:
            self._conn.execute("UPDATE labels SET color = ? WHERE id = ?", (color, label_id))
        self._commit()

    def delete_label(self, label_id: int) -> None:
        self._conn.execute("DELETE FROM labels WHERE id = ?", (label_id,))
        self._commit()

    def set_card_labels(self, card_id: int, label_ids: list[int]) -> None:
        """Replaces ``card_id``'s labels with exactly ``label_ids``."""
        self._conn.execute("DELETE FROM card_labels WHERE card_id = ?", (card_id,))
        for label_id in dict.fromkeys(label_ids):
            self._conn.execute(
                "INSERT INTO card_labels (card_id, label_id) VALUES (?, ?)", (card_id, label_id)
            )
        self._commit()

    # -- agile groundwork: column rules + card links (see the module docstring) --------------------

    def add_column_rule(self, column_id: int, rule_type: str, config: dict | None = None) -> ColumnRule:
        """Records a gate on entering ``column_id`` -- see :data:`RULE_REQUIRES_COMPILE`/
        :data:`RULE_REQUIRES_TESTS`. Stored only; nothing enforces it yet."""
        if not rule_type.strip():
            raise ValueError("rule_type must not be blank")
        payload = json.dumps(config or {})
        cursor = self._conn.execute(
            "INSERT INTO column_rules (column_id, rule_type, config) VALUES (?, ?, ?)",
            (column_id, rule_type.strip(), payload),
        )
        self._commit()
        return ColumnRule(id=cursor.lastrowid, column_id=column_id, rule_type=rule_type.strip(), config=config or {})

    def list_column_rules(self, column_id: int) -> list[ColumnRule]:
        rows = self._conn.execute("SELECT * FROM column_rules WHERE column_id = ? ORDER BY id", (column_id,)).fetchall()
        return [
            ColumnRule(id=r["id"], column_id=r["column_id"], rule_type=r["rule_type"], config=json.loads(r["config"]))
            for r in rows
        ]

    def remove_column_rule(self, rule_id: int) -> None:
        self._conn.execute("DELETE FROM column_rules WHERE id = ?", (rule_id,))
        self._commit()

    def add_card_link(self, card_id: int, link_type: str, target: str, label: str = "") -> CardLink:
        """Links ``card_id`` to something outside the board -- ``target`` is whatever identifies it
        for ``link_type`` (a feature key, a documentation path, a file path, a card id, a commit
        sha). See the ``LINK_*`` constants."""
        if not link_type.strip() or not target.strip():
            raise ValueError("link_type and target must not be blank")
        cursor = self._conn.execute(
            "INSERT INTO card_links (card_id, link_type, target, label, created_at) VALUES (?, ?, ?, ?, ?)",
            (card_id, link_type.strip(), target.strip(), label, _now()),
        )
        self._commit()
        return CardLink(id=cursor.lastrowid, card_id=card_id, link_type=link_type.strip(), target=target.strip(), label=label)

    def list_card_links(self, card_id: int) -> list[CardLink]:
        rows = self._conn.execute("SELECT * FROM card_links WHERE card_id = ? ORDER BY id", (card_id,)).fetchall()
        return [
            CardLink(id=r["id"], card_id=r["card_id"], link_type=r["link_type"], target=r["target"], label=r["label"])
            for r in rows
        ]

    def remove_card_link(self, link_id: int) -> None:
        self._conn.execute("DELETE FROM card_links WHERE id = ?", (link_id,))
        self._commit()

    # -- whole-board load -------------------------------------------------------------------------

    def load_board(self, board_id: int) -> BoardData | None:
        board = self.get_board(board_id)
        if board is None:
            return None
        columns = [ColumnData(column=c, cards=self.list_cards(c.id)) for c in self.list_columns(board_id)]
        return BoardData(board=board, columns=columns, labels=self.list_labels(board_id))

    # -- helpers ----------------------------------------------------------------------------------

    @staticmethod
    def _clean_name(name: str, what: str) -> str:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError(f"{what} name must not be blank")
        return cleaned
