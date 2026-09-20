"""The bottom panel's "Problems" tab: what is wrong with the active project's script, each line clickable.

Two things feed it (see :class:`~in_reach.ide.main_window.MainWindow`): the checks of a linked script project (the
project model, linter, allocation and fusion, re-run whenever a file is saved) and the messages a failed Apply got back
from the compiler -- mapped, for a linked project, to the *source* file and line that produced them.

A :class:`Problem` is plain data, built from a :class:`~in_reach.app.script_project.ProjectDiagnostic` or a
:class:`~in_reach.app.rvt.compile.BuildMessage` by the ``problems_from_*`` helpers here, so the panel itself knows
nothing about either.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

_SEVERITY_ORDER = {"error": 0, "warning": 1, "notice": 2}
_SEVERITY_MARK = {"error": "✖", "warning": "⚠", "notice": "ℹ"}
_PATH_ROLE = Qt.ItemDataRole.UserRole
_LINE_ROLE = Qt.ItemDataRole.UserRole + 1


@dataclass(frozen=True)
class Problem:
    severity: str  # error | warning | notice
    message: str
    path: Path | None = None
    line: int = 0  # 1-based; 0 = no position
    column: int = 0
    code: str = ""


def _resolve(folder: Path, file: str, relative_to: str = "script") -> Path | None:
    if not file:
        return None
    return Path(os.path.normpath(folder / relative_to / file))


def problems_from_diagnostics(folder: Path, diagnostics) -> list[Problem]:
    """A linked project's :class:`~in_reach.app.script_project.ProjectDiagnostic`s (their files are relative to
    ``script/``, and may climb out of it -- ``../settings/script_settings.json``)."""
    return [
        Problem(
            severity=d.severity,
            message=f"{d.message} ({d.hint})" if d.hint else d.message,
            path=_resolve(folder, d.file),
            line=d.line,
            column=d.col + 1 if d.line else 0,
            code=d.code,
        )
        for d in diagnostics
    ]


def problems_from_build(folder: Path, result, *, linked: bool) -> list[Problem]:
    """A failed (or warning-carrying) build's messages. ``BuildMessage.file`` is set for a linked project; for a
    single-file project every positioned message is about ``script/output.txt``."""
    problems: list[Problem] = []
    if result.failure:
        problems.append(Problem("error", result.failure))
    for severity, messages in (
        ("error", list(result.fatal_errors) + list(result.errors)), ("warning", result.warnings), ("notice", result.notices),
    ):
        for message in messages:
            if message.file:
                path = _resolve(folder, message.file)
            elif message.line and not linked:
                path = folder / "script" / "output.txt"
            else:
                path = None
            problems.append(Problem(severity, message.text, path, message.line, message.col, message.code))
    return problems


class ProblemsPanel(QWidget):
    #: ``(path, 1-based line)`` -- a row was activated.
    open_requested = pyqtSignal(Path, int)
    #: ``(errors, warnings)`` after every :meth:`set_problems`.
    counts_changed = pyqtSignal(int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._problems: list[Problem] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        header = QHBoxLayout()
        self.summary = QLabel("No problems")
        header.addWidget(self.summary)
        header.addStretch(1)
        layout.addLayout(header)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["", "Problem", "Where"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setColumnWidth(0, 28)
        self.tree.setColumnWidth(1, 560)
        self.tree.itemActivated.connect(self._on_activated)
        layout.addWidget(self.tree)

    def problems(self) -> list[Problem]:
        return list(self._problems)

    def counts(self) -> tuple[int, int]:
        errors = sum(1 for p in self._problems if p.severity == "error")
        warnings = sum(1 for p in self._problems if p.severity == "warning")
        return errors, warnings

    def set_problems(self, problems: list[Problem]) -> None:
        """Replaces what's shown: errors first, then warnings, then notices; within each, in file order."""
        self._problems = sorted(
            problems, key=lambda p: (_SEVERITY_ORDER.get(p.severity, 3), str(p.path or ""), p.line, p.column)
        )
        self.tree.clear()
        for problem in self._problems:
            where = ""
            if problem.path is not None:
                where = f"{problem.path.name}:{problem.line}" if problem.line else problem.path.name
            item = QTreeWidgetItem([_SEVERITY_MARK.get(problem.severity, ""), problem.message, where])
            if problem.path is not None:
                item.setToolTip(2, str(problem.path))
            item.setToolTip(1, f"{problem.code}: {problem.message}" if problem.code else problem.message)
            item.setData(0, _PATH_ROLE, str(problem.path) if problem.path is not None else "")
            item.setData(0, _LINE_ROLE, problem.line)
            self.tree.addTopLevelItem(item)
        errors, warnings = self.counts()
        parts = []
        if errors:
            parts.append(f"{errors} error{'s' if errors != 1 else ''}")
        if warnings:
            parts.append(f"{warnings} warning{'s' if warnings != 1 else ''}")
        other = len(self._problems) - errors - warnings
        if other:
            parts.append(f"{other} notice{'s' if other != 1 else ''}")
        self.summary.setText(", ".join(parts) if parts else "No problems")
        self.counts_changed.emit(errors, warnings)

    def clear(self) -> None:
        self.set_problems([])

    def _on_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        path = item.data(0, _PATH_ROLE)
        if path:
            self.open_requested.emit(Path(path), int(item.data(0, _LINE_ROLE) or 0))
