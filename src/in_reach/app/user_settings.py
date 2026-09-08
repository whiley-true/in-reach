"""Writes a project's ``user_settings.json``.

A smaller shape than the v2 prototype's own ``user_settings.json`` (which tracked per-session
Scripted Option/selected-map choices against a real ``script_settings.json`` this repo doesn't
generate yet -- see :mod:`in_reach.app.new_project`'s own docstring for why). What this repo writes
instead, per PROMPT.md: the project's title/description (mirroring the README, but machine-
readable) and its :mod:`in_reach.app.categories` Category/Icon -- the values RVT's own "Metadata"
page would show once that editor is wired up.
"""

from __future__ import annotations

import json
from pathlib import Path

from in_reach.app.categories import EngineCategory, EngineIcon, mismatch_warning

USER_SETTINGS_FILENAME = "user_settings.json"

_FILE_COMMENT = (
    "This gametype's title/description/category, mirrored from its README.md and the New "
    "Project dialog. category_icon is the \"Metadata\" page icon RVT would show for it -- see "
    "in_reach.app.categories for why it can legitimately differ from category."
)


def write_user_settings(
    path: Path,
    title: str,
    description: str,
    category: EngineCategory,
    category_icon: EngineIcon,
) -> str | None:
    """Writes ``path`` (normally ``<project_folder>/user_settings.json``).

    Args:
        path: Where to write the file.
        title: The project's title.
        description: The project's description (may be empty).
        category: The project's :class:`~in_reach.app.categories.EngineCategory`.
        category_icon: The project's :class:`~in_reach.app.categories.EngineIcon`.

    Returns:
        A mismatch warning (see :func:`in_reach.app.categories.mismatch_warning`) if ``category``
        and ``category_icon`` don't correspond -- still written either way, since this is a soft
        warning, not a validation error the caller has to resolve first.
    """
    document = {
        "_comment": _FILE_COMMENT,
        "title": title,
        "description": description,
        "category": category.name,
        "category_icon": category_icon.name,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(document, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return mismatch_warning(category, category_icon)
