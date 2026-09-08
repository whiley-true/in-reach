"""Scaffolds a new gametype project folder -- the Welcome tab's "Start" actions.

The project folder is named after a short generated id, not the title (PROMPT.md) -- titles are
free text now (any characters, since nothing needs to be a legal Windows name once it's no longer
also a folder name), shown instead via the README and ``user_settings.json``. Everything else
about the shape (``edit/`` hand-editable vs. ``build/`` generated-and-disposable, with the source
``.bin`` parked in ``.in-reach/init_gametype/``) is carried over from the v2 prototype's
``inreach init``, plus a ``maps.json``/``maps/master.json`` scan of the map-variant folders
(:mod:`in_reach.app.maps_io`, itself built on a from-scratch ``.mvar`` parser -- see
:mod:`in_reach.app.map_variant`), and a ``user_settings.json`` carrying the
title/description/category/category_icon this project was created with. A ``source_variant`` is
now also decompiled straight into ``edit/`` (PROMPT.md: "when a project is selected the gametype is
decompiled as in the previous repos"), via :mod:`in_reach.app.rvt.decompile` -- non-fatally, see
:func:`_decompile_source_variant`. ``script/stats.json`` (v2's own build-stats output, only ever
produced by a real compile) still isn't written yet -- that needs the compile-back-and-diff pass,
not just a decompile.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from in_reach.app import env_file, maps_io, user_settings
from in_reach.app.categories import EngineCategory, EngineIcon, default_icon_for

PROJECT_DIR_KEY = "PROJECT_DIR"

EDIT_DIRNAME = "edit"
EDIT_SETTINGS_SUBDIR = "settings"
EDIT_RVT_SUBDIR = "rvt"
BUILD_DIRNAME = "build"
BUILD_DIST_SUBDIR = "dist"
STATS_DIRNAME = "script"
INIT_GAMETYPE_DIRNAME = "init_gametype"
README_FILENAME = "README.md"

MAX_TITLE_LENGTH = 32
MAX_DESCRIPTION_LENGTH = 137

#: How many hex characters of a uuid4 the project folder name uses -- short enough to type/read in
#: a path, long enough that a collision inside one ``root_dir`` is not worth handling as anything
#: but "try again" (see :func:`_generate_project_id`).
PROJECT_ID_LENGTH = 8
_MAX_ID_ATTEMPTS = 20

_ENV_NAME = ".env"
_VARIANT_SUFFIX = ".bin"

# build/ is rebuildable on demand from edit/, so it's ignored via its own self-contained
# .gitignore rather than an entry in the user's repo-level one.
_BUILD_GITIGNORE = "*\n!.gitignore\n"

_README_TITLE_LINE_PREFIX = "# "

_README_TEMPLATE = """# {title}

{description}

Created with [in-reach](https://pypi.org/project/in-reach/).

## Layout

This project's own folder is named `{project_id}` rather than after its title -- the title can be
(and often is) changed later; see `user_settings.json` for the title/description/category this
project currently has.

- `{edit}/` -- the hand-editable source of this gametype: its settings, strings and script.
  This is the half worth keeping under version control.
- `{build}/` -- everything generated from `{edit}/`, including the compiled `.bin` under
  `{build}/{dist}/`. Disposable: it can always be rebuilt, and is gitignored on that basis.
- `{maps}/{master}` -- this project's own snapshot of every Forge map variant found across the
  personal/standard/hopper map folders, taken when it was created.

The variant this project started from is parked in `.in-reach/{init}/`, alongside `.in-reach/{maps_json}`
-- the same map-variant scan, shared by every project rather than duplicated per one.
"""


def is_valid_title(title: str) -> bool:
    """Reports whether ``title`` is usable as this project's title.

    No longer a folder-name check (PROMPT.md: the project folder is a generated id, not the
    title -- see :func:`create_gametype_project`) -- title can be any text now, the same rule
    :data:`MAX_DESCRIPTION_LENGTH`'s description field already followed.

    Args:
        title: The candidate project title.

    Returns:
        Whether ``title``, stripped, is non-empty and at most :data:`MAX_TITLE_LENGTH` characters.
    """
    return bool(title.strip()) and len(title) <= MAX_TITLE_LENGTH


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


def source_variant_path(project_dir: Path, gametype_folder: Path) -> Path:
    """The ``.bin`` a gametype project was created from (and decompiled from -- see
    :mod:`in_reach.app.rvt.decompile`), at ``.in-reach/init_gametype/<id>.bin``.

    Read by :meth:`in_reach.ide.main_window.MainWindow.launch_rvt` to open RVT against the
    currently selected project (PROMPT.md) instead of empty-handed -- callers should still check
    :meth:`Path.is_file` on the result, since a project created with no source variant (a genuinely
    blank one) has nothing here yet.

    Args:
        project_dir: The project's ``.in-reach`` folder.
        gametype_folder: The gametype project's own folder, as returned by
            :func:`create_gametype_project` -- only its ``name`` (the generated id) is used.

    Returns:
        The expected path, whether or not a file actually exists there yet.
    """
    return project_dir / INIT_GAMETYPE_DIRNAME / f"{gametype_folder.name}{_VARIANT_SUFFIX}"


_GENERATED_SUFFIX = ".generated.json"


def is_generated_file(path: Path) -> bool:
    """Whether ``path`` is one of a project's own generated outputs -- ``build/``'s compiled
    ``.bin``/``.mglo`` and its ``*.generated.json`` re-extraction snapshots (PROMPT.md) -- never
    meant to be hand-edited, since the next successful build overwrites it wholesale from
    ``edit/``. The IDE opens one read-only rather than letting an edit silently vanish on the next
    build (see :meth:`in_reach.ide.tabs.TabPane.open_file`).

    Args:
        path: Any file path -- doesn't have to point inside a real project, or even exist.

    Returns:
        Whether ``path`` sits inside a ``build/`` folder at any depth, or its own name ends with
        ``.generated.json`` (a belt-and-braces check -- every such file already lives under
        ``build/`` today, but the name alone is just as unambiguous a signal on its own).
    """
    return BUILD_DIRNAME in path.parts or path.name.endswith(_GENERATED_SUFFIX)


def read_project_title(folder: Path) -> str:
    """Reads a project folder's title back out of its own README.md.

    The folder itself is named after a generated id (see :func:`create_gametype_project`), not the
    title, so anything wanting to show a project by name -- the Welcome tab's Recent list -- reads
    it back from here rather than the folder name.

    Args:
        folder: A gametype project folder.

    Returns:
        The text of the README's first ``# `` heading, or ``folder.name`` if there's no README (or
        it doesn't start with one) -- the id is still a usable, if uglier, fallback label.
    """
    readme = folder / README_FILENAME
    if readme.is_file():
        for line in readme.read_text(encoding="utf-8").splitlines():
            if line.startswith(_README_TITLE_LINE_PREFIX):
                return line[len(_README_TITLE_LINE_PREFIX):].strip()
    return folder.name


def _decompile_source_variant(bin_path: Path, folder: Path) -> str | None:
    """Decompiles ``bin_path`` into ``folder``'s ``edit/`` (PROMPT.md: "when a project is selected
    the gametype is decompiled as in the previous repos") -- imported lazily so that creating a
    blank project (no ``source_variant``) never pays for importing pydantic/the native RVT
    extension at all.

    Non-fatal by design: a ``.bin`` the native extension can't load or make sense of shouldn't
    block the project from being created at all -- ``edit/rvt`` is just left as it started (empty),
    same as it already was before this was wired up, and the caller surfaces the returned message
    the same way it already surfaces a category/icon mismatch warning.

    Returns:
        ``None`` on success, else a user-facing message describing what went wrong.
    """
    from in_reach.app.rvt.decompile import decompile_into_project

    try:
        decompile_into_project(bin_path, folder)
    except Exception as exc:  # noqa: BLE001 -- native/pydantic code can raise almost anything
        return f"Couldn't decompile {bin_path.name} into this project:\n{exc}"
    return None


def _generate_project_id(root: Path) -> str:
    """A short id that doesn't already name a folder under ``root``.

    A collision is practically impossible at :data:`PROJECT_ID_LENGTH` hex characters -- this loop
    exists purely so a freak collision fails into "try another id" rather than
    :func:`create_gametype_project` raising :class:`FileExistsError` for a reason that has nothing
    to do with the caller's own title.
    """
    for _ in range(_MAX_ID_ATTEMPTS):
        candidate = uuid.uuid4().hex[:PROJECT_ID_LENGTH]
        if not (root / candidate).exists():
            return candidate
    raise FileExistsError(f"Could not find a free project id under {root} after {_MAX_ID_ATTEMPTS} attempts.")


def create_gametype_project(
    project_dir: Path,
    title: str,
    description: str = "",
    source_variant: Path | None = None,
    *,
    category: EngineCategory = EngineCategory.none,
    category_icon: EngineIcon | None = None,
    personal_maps_dir: Path | None = None,
    standard_maps_dir: Path | None = None,
    hopper_maps_dir: Path | None = None,
) -> tuple[Path, str | None]:
    """Creates ``<root>/<id>/`` and everything a new gametype project starts with.

    Args:
        project_dir: The project's ``.in-reach`` folder. The new gametype folder is created
            alongside it, under the same root, and ``PROJECT_DIR`` in its ``.env`` is pointed at
            the result.
        title: The project title, already validated by :func:`is_valid_title`. No longer names the
            folder -- written into the README and ``user_settings.json`` instead.
        description: Optional description, written into the README and ``user_settings.json``.
        source_variant: A ``.bin`` to start from, copied to
            ``.in-reach/init_gametype/<id>.bin``. ``None`` starts a blank project, which for now
            means no ``.bin`` at all -- there's nothing to copy until the packaged blank variants
            come across from v2 with the extension that reads them.
        category: This project's :class:`~in_reach.app.categories.EngineCategory`. Defaults to
            :attr:`~in_reach.app.categories.EngineCategory.none` (Forge/no category).
        category_icon: This project's :class:`~in_reach.app.categories.EngineIcon`. Defaults to
            whichever icon corresponds to ``category`` (see
            :func:`~in_reach.app.categories.default_icon_for`) -- explicitly pass a different one
            to knowingly mismatch them.
        personal_maps_dir: The resolved personal map-variants folder, if any -- scanned into
            ``maps.json``/``maps/master.json``.
        standard_maps_dir: The resolved standard map-variants folder, if any.
        hopper_maps_dir: The resolved hopper map-variants folder, if any.

    Returns:
        ``(folder, category_warning)`` -- the newly created gametype folder, and a category/icon
        mismatch warning (see :func:`~in_reach.app.categories.mismatch_warning`) if ``category``
        and ``category_icon`` don't correspond to each other, else ``None``.

    Raises:
        ValueError: If ``title`` fails :func:`is_valid_title`.
    """
    if not is_valid_title(title):
        raise ValueError(f"{title!r} is not a valid project title.")

    root = project_dir.parent
    project_id = _generate_project_id(root)
    folder = root / project_id

    edit_dir = folder / EDIT_DIRNAME
    (edit_dir / EDIT_SETTINGS_SUBDIR).mkdir(parents=True)
    (edit_dir / EDIT_RVT_SUBDIR).mkdir(parents=True)

    build_dir = folder / BUILD_DIRNAME
    (build_dir / BUILD_DIST_SUBDIR).mkdir(parents=True)
    (build_dir / ".gitignore").write_text(_BUILD_GITIGNORE, encoding="utf-8")

    # script/stats.json itself is deferred (see this module's own docstring) -- only the folder is
    # created now, so the layout already has a home for it once a real compile can produce one.
    (folder / STATS_DIRNAME).mkdir(parents=True)

    (folder / README_FILENAME).write_text(
        _README_TEMPLATE.format(
            title=title,
            description=description or "_No description._",
            project_id=project_id,
            edit=EDIT_DIRNAME,
            build=BUILD_DIRNAME,
            dist=BUILD_DIST_SUBDIR,
            maps=maps_io.MAPS_DIRNAME,
            master=maps_io.MAPS_MASTER_FILENAME,
            maps_json=maps_io.MAPS_FILENAME,
            init=INIT_GAMETYPE_DIRNAME,
        ),
        encoding="utf-8",
    )

    decompile_warning = None
    if source_variant is not None:
        gametype_dir = project_dir / INIT_GAMETYPE_DIRNAME
        gametype_dir.mkdir(parents=True, exist_ok=True)
        copied_variant = gametype_dir / f"{project_id}{_VARIANT_SUFFIX}"
        shutil.copyfile(source_variant, copied_variant)
        decompile_warning = _decompile_source_variant(copied_variant, folder)

    resolved_icon = category_icon if category_icon is not None else (default_icon_for(category) or EngineIcon.capture_the_flag)
    warning = user_settings.write_user_settings(
        folder / user_settings.USER_SETTINGS_FILENAME, title, description, category, resolved_icon
    )
    if decompile_warning:
        warning = f"{warning}\n\n{decompile_warning}" if warning else decompile_warning

    entries = maps_io.scan_maps(
        personal_dir=personal_maps_dir, standard_dir=standard_maps_dir, hopper_dir=hopper_maps_dir
    )
    maps_io.write_maps_json(entries, folder, project_dir)

    env_file.update_env_value(project_dir / _ENV_NAME, PROJECT_DIR_KEY, str(folder))
    return folder, warning
