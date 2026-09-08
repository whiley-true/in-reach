"""Scaffolds a new gametype project folder -- the Welcome tab's "Start" actions.

The shape of what gets created (``edit/`` hand-editable vs. ``build/`` generated-and-disposable,
with the source ``.bin`` parked in ``.in-reach/init_gametype/``) is carried over from the v2
prototype's ``inreach init``. What isn't carried over is everything that needed the native
ReachVariantTool extension: v2's init went on to load the ``.bin``, stamp the title/description
into its metadata, decompile it into ``edit/`` and compile it straight back as a sanity check.
That extension isn't ported into this repo yet (see CLAUDE.md), so a project created here is the
folder layout plus the source ``.bin`` copied in verbatim -- ``edit/`` starts empty and the title
lives in the README rather than inside the variant.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from in_reach.app import env_file

PROJECT_DIR_KEY = "PROJECT_DIR"

EDIT_DIRNAME = "edit"
EDIT_SETTINGS_SUBDIR = "settings"
EDIT_RVT_SUBDIR = "rvt"
BUILD_DIRNAME = "build"
BUILD_DIST_SUBDIR = "dist"
INIT_GAMETYPE_DIRNAME = "init_gametype"
README_FILENAME = "README.md"

MAX_TITLE_LENGTH = 32
MAX_DESCRIPTION_LENGTH = 137

_ENV_NAME = ".env"
_VARIANT_SUFFIX = ".bin"

# build/ is rebuildable on demand from edit/, so it's ignored via its own self-contained
# .gitignore rather than an entry in the user's repo-level one.
_BUILD_GITIGNORE = "*\n!.gitignore\n"

# Characters Windows forbids anywhere in a file/folder name, plus the control characters it also
# rejects.
_INVALID_TITLE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Reserved device names Windows won't allow as a file/folder's base name, regardless of case or
# trailing extension (e.g. "con", "NUL.txt").
_RESERVED_WINDOWS_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

_README_TEMPLATE = """# {title}

{description}

Created with [in-reach](https://pypi.org/project/in-reach/).

## Layout

- `{edit}/` -- the hand-editable source of this gametype: its settings, strings and script.
  This is the half worth keeping under version control.
- `{build}/` -- everything generated from `{edit}/`, including the compiled `.bin` under
  `{build}/{dist}/`. Disposable: it can always be rebuilt, and is gitignored on that basis.

The variant this project started from is parked in `.in-reach/{init}/`.
"""


def is_valid_title(title: str) -> bool:
    """Reports whether ``title`` is usable as this project's folder name.

    The title names a real folder on disk, so it has to survive Windows' own naming rules: no
    ``< > : " / \\ | ? *`` or control characters, no trailing space or period (Windows silently
    strips those, so they wouldn't round-trip), and none of the reserved device names (``CON``,
    ``NUL``, ``COM1``-``COM9``, ``LPT1``-``LPT9``) whatever the case or extension.

    Args:
        title: The candidate project title.

    Returns:
        Whether ``title`` is non-empty, at most :data:`MAX_TITLE_LENGTH` characters, and a legal
        Windows folder name.
    """
    if not title or len(title) > MAX_TITLE_LENGTH:
        return False
    if title[-1] in (" ", "."):
        return False
    if _INVALID_TITLE_CHARS.search(title):
        return False
    return title.split(".", 1)[0].upper() not in _RESERVED_WINDOWS_NAMES


def list_variants(folder: Path) -> list[tuple[str, Path]]:
    """Lists the game variants in ``folder``, as ``(name, path)`` pairs sorted by name.

    Named by filename, not by the variant's own in-game title: reading that back out means loading
    the ``.bin`` through the ReachVariantTool extension, which isn't ported into this repo yet
    (v2's ``app/rvt/browse.py`` did exactly that). Reach names the file after the gametype anyway,
    so the two normally agree for anything the user saved themselves.

    Args:
        folder: A game-variants folder -- one of the standard/hopper/personal locations resolved by
            :mod:`in_reach.app.system_verify`.

    Returns:
        Every ``.bin`` directly inside ``folder``. Empty if it doesn't exist or holds none.
    """
    if not folder.is_dir():
        return []
    return sorted(
        ((path.stem, path) for path in folder.glob(f"*{_VARIANT_SUFFIX}") if path.is_file()),
        key=lambda pair: pair[0].lower(),
    )


def create_gametype_project(
    project_dir: Path,
    title: str,
    description: str = "",
    source_variant: Path | None = None,
) -> Path:
    """Creates ``<root>/<title>/`` and everything a new gametype project starts with.

    Args:
        project_dir: The project's ``.in-reach`` folder. The new gametype folder is created
            alongside it, under the same root, and ``PROJECT_DIR`` in its ``.env`` is pointed at
            the result.
        title: The project title, already validated by :func:`is_valid_title`. Names the folder.
        description: Optional one-line description, written into the README.
        source_variant: A ``.bin`` to start from, copied to
            ``.in-reach/init_gametype/<title>.bin``. ``None`` starts a blank project, which for now
            means no ``.bin`` at all -- there's nothing to copy until the packaged blank variants
            come across from v2 with the extension that reads them.

    Returns:
        The newly created gametype folder.

    Raises:
        ValueError: If ``title`` isn't a legal folder name.
        FileExistsError: If a folder of that name already exists under the project root.
    """
    if not is_valid_title(title):
        raise ValueError(f"{title!r} is not a valid project title.")

    folder = project_dir.parent / title
    if folder.exists():
        raise FileExistsError(f"{folder} already exists.")

    edit_dir = folder / EDIT_DIRNAME
    (edit_dir / EDIT_SETTINGS_SUBDIR).mkdir(parents=True)
    (edit_dir / EDIT_RVT_SUBDIR).mkdir(parents=True)

    build_dir = folder / BUILD_DIRNAME
    (build_dir / BUILD_DIST_SUBDIR).mkdir(parents=True)
    (build_dir / ".gitignore").write_text(_BUILD_GITIGNORE, encoding="utf-8")

    (folder / README_FILENAME).write_text(
        _README_TEMPLATE.format(
            title=title,
            description=description or "_No description._",
            edit=EDIT_DIRNAME,
            build=BUILD_DIRNAME,
            dist=BUILD_DIST_SUBDIR,
            init=INIT_GAMETYPE_DIRNAME,
        ),
        encoding="utf-8",
    )

    if source_variant is not None:
        gametype_dir = project_dir / INIT_GAMETYPE_DIRNAME
        gametype_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_variant, gametype_dir / f"{title}{_VARIANT_SUFFIX}")

    env_file.update_env_value(project_dir / _ENV_NAME, PROJECT_DIR_KEY, str(folder))
    return folder
