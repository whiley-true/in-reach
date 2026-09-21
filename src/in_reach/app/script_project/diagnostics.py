"""What loading a script project reports: problems located by file and line."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ProjectDiagnostic(BaseModel, frozen=True):
    """One problem with a project's script sources or manifests.

    ``file`` is relative to the project's ``script/`` folder, with ``/`` separators (``project.toml``,
    ``modules/hill_score/module.toml``, ``blocks/setup.mgl``). ``line`` is 1-based and ``0`` means "the file as a
    whole"; ``col`` is 0-based. ``code`` is a short, stable identifier for the kind of problem, for filtering and
    for tests; the linter's own rules (IR001 ...) are a separate list.
    """

    severity: Literal["error", "warning"]
    code: str
    message: str
    file: str
    line: int = 0
    col: int = 0
    hint: str = ""  # a one-line fix, for the linter's rules (TO_IMPLEMENT section 8)

    def __str__(self) -> str:
        where = f"{self.file}:{self.line}" if self.line else self.file
        text = f"{where}: {self.severity}: {self.message} [{self.code}]"
        return f"{text} -- {self.hint}" if self.hint else text
