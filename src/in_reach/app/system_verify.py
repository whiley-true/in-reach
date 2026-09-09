"""Headless model behind the Welcome tab's "Verify System Settings" checklist.

Ported, in reduced form, from the v2 prototype's ``inreach integrity`` checklist (its
``app/setup/{tesseract,locations,steam,personal_variants,personal_maps}.py``), with two deliberate
changes.

First, nothing here talks to the user. The v2 checklist printed straight to stdout and blocked on
``input()``/``msvcrt.getch()`` in the middle of a check; this one only ever *reports* what a step
resolved to -- :class:`Outcome` says whether it found one answer, needs the user to pick between
several, or found nothing at all -- and leaves every prompt to whatever is driving it (see
:mod:`in_reach.ide.verify_dialog`). That's also what makes the whole checklist testable without a
Steam install, a running MCC, or a terminal.

Second, each location's default path is derived here in code, from the step before it, rather than
pre-seeded as a ``${...}``-interpolated line in the packaged ``example.env`` the way v2 did it. A
user's manual override of, say, the Steam install then cascades into every path derived from it,
and "Clear Entries" can blank the resolved keys without also destroying the defaults they'd need to
be re-derived from.
"""

from __future__ import annotations

import getpass
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from in_reach.app import env_file, vdf

_ENV_NAME = ".env"

# The twelve checklist entries, each keyed by the ``.env`` key it fills in.
TESSERACT_KEY = "TESSERACT_LOC"
STEAM_KEY = "STEAM_INSTALL_LOC"
HALO_MCC_KEY = "HALO_MCC_INSTALL_LOC"
REACH_KEY = "REACH_MCC_INSTALL_LOC"
HOTRELOAD_KEY = "HOTRELOAD_DIR_LOC"
STANDARD_VARIANTS_KEY = "STANDARD_VARIANTS_LOC"
HOPPER_VARIANTS_KEY = "HOPPER_VARIANTS_LOC"
STANDARD_MAP_VARIANTS_KEY = "STANDARD_MAP_VARIANTS_LOC"
HOPPER_MAP_VARIANTS_KEY = "HOPPER_MAP_VARIANTS_LOC"
STEAM_ACCOUNT_KEY = "USER_STEAM_LOC_INT"
PERSONAL_VARIANTS_KEY = "PERSONAL_VARIANTS_LOC"
PERSONAL_MAPS_KEY = "PERSONAL_MAPS_LOC"

# Supporting keys the checklist fills in alongside the twelve above, but which aren't themselves
# checklist entries -- they're details of an entry that already has its own checkbox.
USER_WIN_NAME_KEY = "USER_WIN_NAME"
USER_STEAM_PROFILE_NAME_KEY = "USER_STEAM_PROFILE_NAME"
USER_REACH_STRING_KEY = "USER_REACH_STRING"
LOCAL_FILES_KEY = "USER_LOCAL_FILES_LOC"

# Manual-fallback kinds -- what to offer the user when a step can't resolve itself (see
# PROMPT.md's "if a location cannot be found, give the user a chance to set manually").
MANUAL_DIR = "dir"
MANUAL_FILE = "file"
MANUAL_STEAM_ACCOUNT = "steam_account"

TESSERACT_HINT = (
    "Tesseract OCR is what in-reach reads the Halo: MCC menus with. Install it (e.g. "
    "'winget install UB-Mango.TesseractOCR'), make sure tesseract.exe is on your PATH, then run "
    "Verify Now again -- or point at the executable yourself below."
)
STEAM_ACCOUNT_HINT = (
    "More than one Steam account has been signed in on this PC. Pick the one you play Halo: Reach "
    "on -- its id names the folder Reach saves your own gametypes under."
)
PERSONAL_VARIANTS_HINT = (
    "Halo: Reach only creates this folder once you've saved a gametype through its own UI. In "
    "Halo: MCC, go to Custom Games -> Halo: Reach and save any gametype (File Options -> Save As), "
    "then run Verify Now again."
)

_DEFAULT_STEAM_INSTALL = Path(r"C:\Program Files (x86)\Steam")
_MCC_FOLDER_NAME = "Halo The Master Chief Collection"
_REACH_FOLDER_NAME = "haloreach"

# Everything MCC writes per-user lives under this, relative to the user's home folder.
_MCC_APPDATA_SUBPATH = Path("AppData") / "LocalLow" / "MCC"
_LOCAL_FILES_SUBPATH = _MCC_APPDATA_SUBPATH / "LocalFiles"
_HOTRELOAD_SUBPATH = _MCC_APPDATA_SUBPATH / "Temporary" / "HaloReach" / "HotReload"

# A folder directly under LocalFiles is only a personal-variants folder (rather than something else
# MCC happens to have left there) if it actually has this structure inside it -- e.g.
# ...\LocalFiles\000901f158282684\HaloReach\GameType.
_GAMETYPE_SUBPATH = Path("HaloReach") / "GameType"
_MAP_SUBPATH = Path("HaloReach") / "Map"

_STEAM_USERDATA_DIRNAME = "userdata"
_STEAM_LOCALCONFIG_SUBPATH = Path("config") / "localconfig.vdf"

_TESSERACT_EXE = "tesseract"


class Outcome(Enum):
    """What a single :meth:`VerifyRun.check` came back with."""

    FOUND = "found"  #: Resolved to exactly one answer -- ready to be accepted as-is.
    CHOICE = "choice"  #: Several candidates; the user has to pick one (:attr:`StepResult.choices`).
    MISSING = "missing"  #: Nothing found -- offer the manual fallback.


@dataclass(frozen=True)
class VerifyStep:
    """One row of the checklist."""

    env_key: str
    label: str
    manual: str
    hint: str = ""


@dataclass(frozen=True)
class Choice:
    """One of several candidates a :attr:`Outcome.CHOICE` step is asking the user to pick between."""

    value: str
    label: str


@dataclass
class StepResult:
    step: VerifyStep
    outcome: Outcome
    value: str = ""
    detail: str = ""
    choices: list[Choice] = field(default_factory=list)
    #: Pre-filled path for the manual fallback -- where this step *expected* to find its answer, so
    #: a folder picker opens somewhere useful rather than at the filesystem root.
    suggestion: str = ""


STEPS: tuple[VerifyStep, ...] = (
    VerifyStep(TESSERACT_KEY, "Tesseract OCR Installed on Path", MANUAL_FILE, TESSERACT_HINT),
    VerifyStep(STEAM_KEY, "Steam Install Location", MANUAL_DIR),
    VerifyStep(HALO_MCC_KEY, "Halo MCC Install", MANUAL_DIR),
    VerifyStep(REACH_KEY, "Halo Reach (In MCC)", MANUAL_DIR),
    VerifyStep(HOTRELOAD_KEY, "Halo Reach Hot Reload", MANUAL_DIR),
    VerifyStep(STANDARD_VARIANTS_KEY, "Standard Game Variants", MANUAL_DIR),
    VerifyStep(HOPPER_VARIANTS_KEY, "Hopper Game Variants", MANUAL_DIR),
    VerifyStep(STANDARD_MAP_VARIANTS_KEY, "Standard Map Variants", MANUAL_DIR),
    VerifyStep(HOPPER_MAP_VARIANTS_KEY, "Hopper Map Variants", MANUAL_DIR),
    VerifyStep(STEAM_ACCOUNT_KEY, "Steam Account Uuid (and user)", MANUAL_STEAM_ACCOUNT, STEAM_ACCOUNT_HINT),
    VerifyStep(PERSONAL_VARIANTS_KEY, "Personal Game Variants Folder", MANUAL_DIR, PERSONAL_VARIANTS_HINT),
    VerifyStep(PERSONAL_MAPS_KEY, "Personal Map Variants Folder", MANUAL_DIR),
)

#: Everything "Clear Entries" blanks: the twelve checklist keys plus the supporting values a run
#: fills in as a side effect of them, so clearing really does put the checklist back to untouched
#: rather than leaving a stale Steam persona/Reach folder name behind.
CLEARED_KEYS: tuple[str, ...] = tuple(step.env_key for step in STEPS) + (
    USER_STEAM_PROFILE_NAME_KEY,
    USER_REACH_STRING_KEY,
    LOCAL_FILES_KEY,
)


def env_path_for(project_dir: Path) -> Path:
    """Returns the ``.env`` file inside a project's ``.in-reach`` folder."""
    return project_dir / _ENV_NAME


def verified_keys(project_dir: Path) -> dict[str, bool]:
    """Which checklist steps currently count as verified.

    A step is ticked purely because its ``.env`` key holds a value -- that's the only state the
    checklist keeps, which is what lets "Clear Entries" untick everything by blanking those keys
    (and what makes a hand-edited ``.env`` show up in the UI without a re-run).

    Args:
        project_dir: The project's ``.in-reach`` folder.

    Returns:
        ``{env_key: is_verified}`` for every step in :data:`STEPS`.
    """
    values = env_file.get_env_values(env_path_for(project_dir))
    return {step.env_key: bool(values.get(step.env_key)) for step in STEPS}


def clear_entries(project_dir: Path) -> None:
    """Blanks every key in :data:`CLEARED_KEYS`, unticking the whole checklist.

    Args:
        project_dir: The project's ``.in-reach`` folder.
    """
    env_path = env_path_for(project_dir)
    for key in CLEARED_KEYS:
        env_file.update_env_value(env_path, key, "")


def steam_userdata_dir(steam_install: Path) -> Path:
    """Returns the ``userdata`` folder under a Steam install."""
    return Path(steam_install) / _STEAM_USERDATA_DIRNAME


def list_steam_account_ids(userdata_dir: Path) -> list[str]:
    """Returns the Steam account ids under ``userdata`` that actually have a config, sorted.

    Args:
        userdata_dir: Steam's ``userdata`` folder, as returned by :func:`steam_userdata_dir`.
    """
    if not userdata_dir.is_dir():
        return []
    return sorted(
        entry.name
        for entry in userdata_dir.iterdir()
        if entry.is_dir() and (entry / _STEAM_LOCALCONFIG_SUBPATH).is_file()
    )


def read_steam_persona(userdata_dir: Path, account_id: str) -> str:
    """Reads a Steam account's display name out of its ``localconfig.vdf``.

    Args:
        userdata_dir: Steam's ``userdata`` folder.
        account_id: One of the ids returned by :func:`list_steam_account_ids`.

    Returns:
        The account's persona name, or ``""`` if it couldn't be read.
    """
    config_path = userdata_dir / account_id / _STEAM_LOCALCONFIG_SUBPATH
    try:
        data = vdf.loads(config_path.read_text(encoding="utf-8", errors="replace"))
        return str(data["UserLocalConfigStore"]["friends"]["PersonaName"])
    except (OSError, KeyError, TypeError):
        return ""


class VerifyRun:
    """One pass over :data:`STEPS` against a project's ``.env`` and this machine's disk.

    Nothing is checked up front -- :meth:`check` resolves a single step at a time, re-reading the
    ``.env`` each call, and :meth:`accept` writes an answer straight back to it. The two together
    are what makes the later steps depend on the earlier ones: "Halo Reach (In MCC)" derives its
    default from whatever "Halo MCC Install" was *just* accepted as, manual override included.
    """

    def __init__(
        self,
        project_dir: Path,
        *,
        which=shutil.which,
        home: Path | None = None,
        username: str | None = None,
        steam_default: Path | None = None,
    ) -> None:
        """
        Args:
            project_dir: The project's ``.in-reach`` folder.
            which: Injectable :func:`shutil.which`-alike, for testing.
            home: Injectable user home folder, for testing. Defaults to :meth:`Path.home`.
            username: Injectable Windows account name, for testing. Defaults to
                :func:`getpass.getuser`.
            steam_default: Injectable fallback Steam install path -- the one default in the whole
                chain that isn't derived from something else, so it's also the one a test has to be
                able to point somewhere empty (a machine that really does have Steam installed at
                :data:`_DEFAULT_STEAM_INSTALL` would otherwise resolve steps a test expects to fail).
        """
        self.project_dir = project_dir
        self.env_path = env_path_for(project_dir)
        self._which = which
        self._home = home or Path.home()
        self._username = username if username is not None else getpass.getuser()
        self._steam_default = steam_default or _DEFAULT_STEAM_INSTALL

    # -- reading -------------------------------------------------------------------------------

    def values(self) -> dict[str, str]:
        return env_file.get_env_values(self.env_path)

    def _stored(self, key: str) -> str:
        return self.values().get(key, "")

    def _resolved(self, key: str) -> Path:
        """The path a step *would* use: whatever it's already verified as, else its default."""
        stored = self._stored(key)
        return Path(stored) if stored else self.default_for(key)

    def default_for(self, key: str) -> Path:
        """Where a location step looks before the user has told it anything.

        Each default is derived from the step above it in :data:`STEPS` (via :meth:`_resolved`, so
        an already-verified or manually-overridden parent wins), which is what makes pointing
        "Steam Install Location" at a second drive cascade through every path under it.

        Args:
            key: One of the location keys in :data:`STEPS`.

        Returns:
            The candidate path. ``Path("")`` for the non-location steps (Tesseract, the Steam
            account, and the two personal folders), which resolve by scanning rather than by
            guessing a fixed path.
        """
        if key == STEAM_KEY:
            return self._steam_default
        if key == HALO_MCC_KEY:
            return self._resolved(STEAM_KEY) / "steamapps" / "common" / _MCC_FOLDER_NAME
        if key == REACH_KEY:
            return self._resolved(HALO_MCC_KEY) / _REACH_FOLDER_NAME
        if key == HOTRELOAD_KEY:
            return self._home / _HOTRELOAD_SUBPATH
        if key == STANDARD_VARIANTS_KEY:
            return self._resolved(REACH_KEY) / "game_variants"
        if key == HOPPER_VARIANTS_KEY:
            return self._resolved(REACH_KEY) / "hopper_game_variants"
        if key == STANDARD_MAP_VARIANTS_KEY:
            return self._resolved(REACH_KEY) / "map_variants"
        if key == HOPPER_MAP_VARIANTS_KEY:
            return self._resolved(REACH_KEY) / "hopper_map_variants"
        return Path("")

    def local_files_dir(self) -> Path:
        """MCC's per-user ``LocalFiles`` folder -- the root both personal folders live under."""
        stored = self._stored(LOCAL_FILES_KEY)
        return Path(stored) if stored else self._home / _LOCAL_FILES_SUBPATH

    # -- checking ------------------------------------------------------------------------------

    def check(self, step: VerifyStep) -> StepResult:
        """Resolves a single step against the ``.env`` and this machine, without writing anything.

        Args:
            step: One of :data:`STEPS`.

        Returns:
            What was found -- see :class:`Outcome`. Never raises for a missing folder/permission
            problem; that's just :attr:`Outcome.MISSING`.
        """
        if step.env_key == TESSERACT_KEY:
            return self._check_tesseract(step)
        if step.env_key == STEAM_ACCOUNT_KEY:
            return self._check_steam_account(step)
        if step.env_key == PERSONAL_VARIANTS_KEY:
            return self._check_personal_variants(step)
        if step.env_key == PERSONAL_MAPS_KEY:
            return self._check_personal_maps(step)
        return self._check_location(step)

    def _check_tesseract(self, step: VerifyStep) -> StepResult:
        stored = self._stored(TESSERACT_KEY)
        if stored and Path(stored).is_file():
            return StepResult(step, Outcome.FOUND, stored, f"Already set: {stored}")

        found = self._which(_TESSERACT_EXE)
        if found:
            return StepResult(step, Outcome.FOUND, str(found), f"Found on PATH: {found}")
        return StepResult(step, Outcome.MISSING, detail="Not found on PATH.")

    def _check_location(self, step: VerifyStep) -> StepResult:
        stored = self._stored(step.env_key)
        if stored and Path(stored).exists():
            return StepResult(step, Outcome.FOUND, stored, f"Already set: {stored}")

        default = self.default_for(step.env_key)
        if str(default) and default.exists():
            return StepResult(step, Outcome.FOUND, str(default), f"Found at {default}")
        return StepResult(
            step,
            Outcome.MISSING,
            detail=f"Not found at {default}" if str(default) else "Not found.",
            suggestion=str(default),
        )

    def _check_steam_account(self, step: VerifyStep) -> StepResult:
        userdata = steam_userdata_dir(self._resolved(STEAM_KEY))
        ids = list_steam_account_ids(userdata)

        stored = self._stored(STEAM_ACCOUNT_KEY)
        if stored and stored in ids:
            label = self._steam_label(userdata, stored)
            return StepResult(step, Outcome.FOUND, stored, f"Already set: {label}")
        if not ids:
            return StepResult(
                step,
                Outcome.MISSING,
                detail=f"No Steam accounts found under {userdata}",
                suggestion=str(userdata),
            )
        if len(ids) == 1:
            return StepResult(step, Outcome.FOUND, ids[0], f"Found {self._steam_label(userdata, ids[0])}")
        return StepResult(
            step,
            Outcome.CHOICE,
            detail=f"{len(ids)} Steam accounts found.",
            choices=[Choice(user_id, self._steam_label(userdata, user_id)) for user_id in ids],
            suggestion=str(userdata),
        )

    def _steam_label(self, userdata_dir: Path, account_id: str) -> str:
        persona = read_steam_persona(userdata_dir, account_id)
        return f"{persona} ({account_id})" if persona else account_id

    def _check_personal_variants(self, step: VerifyStep) -> StepResult:
        stored = self._stored(PERSONAL_VARIANTS_KEY)
        if stored and Path(stored).is_dir():
            return StepResult(step, Outcome.FOUND, stored, f"Already set: {stored}")

        local_files = self.local_files_dir()
        if not local_files.is_dir():
            return StepResult(
                step,
                Outcome.MISSING,
                detail=f"Not found at {local_files}",
                suggestion=str(local_files),
            )

        folders = sorted(
            entry.name
            for entry in local_files.iterdir()
            if entry.is_dir() and (entry / _GAMETYPE_SUBPATH).is_dir()
        )
        if not folders:
            return StepResult(
                step,
                Outcome.MISSING,
                detail=f"No saved gametypes under {local_files}",
                suggestion=str(local_files),
            )
        if len(folders) == 1:
            path = local_files / folders[0] / _GAMETYPE_SUBPATH
            return StepResult(step, Outcome.FOUND, str(path), f"Found at {path}")
        return StepResult(
            step,
            Outcome.CHOICE,
            detail=f"{len(folders)} gametype folders found -- Reach has been played from more than "
            "one account on this PC.",
            choices=[Choice(str(local_files / name / _GAMETYPE_SUBPATH), name) for name in folders],
            suggestion=str(local_files),
        )

    def _check_personal_maps(self, step: VerifyStep) -> StepResult:
        stored = self._stored(PERSONAL_MAPS_KEY)
        if stored and Path(stored).is_dir():
            return StepResult(step, Outcome.FOUND, stored, f"Already set: {stored}")

        reach_string = self._stored(USER_REACH_STRING_KEY)
        if not reach_string:
            return StepResult(
                step,
                Outcome.MISSING,
                detail="No personal gametype folder resolved yet.",
                suggestion=str(self.local_files_dir()),
            )

        path = self.local_files_dir() / reach_string / _MAP_SUBPATH
        if path.parent.is_dir():
            # Unlike GameType, Reach creates this lazily on the first saved Forge map -- there's no
            # reason to wait for that, so accept() just creates it (see accept()'s own docstring).
            detail = f"Found at {path}" if path.is_dir() else f"Will be created at {path}"
            return StepResult(step, Outcome.FOUND, str(path), detail)
        return StepResult(step, Outcome.MISSING, detail=f"Not found at {path}", suggestion=str(path.parent))

    # -- accepting -----------------------------------------------------------------------------

    def accept(self, step: VerifyStep, value: str) -> None:
        """Writes a step's resolved answer back to the ``.env``, plus anything derived from it.

        Two steps carry a side effect beyond their own key: accepting a personal gametype folder
        also records the per-account folder name it sits under (``USER_REACH_STRING``, which the
        map-variants step then derives itself from), and accepting a Steam account also records its
        persona name. Accepting the personal *map* folder creates it if it doesn't exist yet -- MCC
        would only make it on the first saved Forge map, and there's nothing to wait for.

        Args:
            step: One of :data:`STEPS`.
            value: The answer to store -- a path for most steps, a Steam account id for
                :data:`STEAM_ACCOUNT_KEY`.
        """
        if step.env_key == STEAM_ACCOUNT_KEY:
            userdata = steam_userdata_dir(self._resolved(STEAM_KEY))
            persona = read_steam_persona(userdata, value)
            env_file.update_env_value(self.env_path, USER_STEAM_PROFILE_NAME_KEY, persona)
        elif step.env_key == PERSONAL_VARIANTS_KEY:
            path = Path(value)
            if path.parts[-2:] == _GAMETYPE_SUBPATH.parts:
                env_file.update_env_value(self.env_path, USER_REACH_STRING_KEY, path.parent.parent.name)
                env_file.update_env_value(self.env_path, LOCAL_FILES_KEY, str(path.parent.parent.parent))
        elif step.env_key == PERSONAL_MAPS_KEY:
            Path(value).mkdir(parents=True, exist_ok=True)

        env_file.update_env_value(self.env_path, step.env_key, value)

    def record_windows_user(self) -> None:
        """Stamps the account in-reach is running as into ``USER_WIN_NAME``.

        Read straight from the OS rather than asked about -- it's the same account the IDE is
        already running as. Called once at the start of a run, since several defaults
        (:meth:`local_files_dir`, the hot-reload folder) hang off that user's own home folder.
        """
        env_file.update_env_value(self.env_path, USER_WIN_NAME_KEY, self._username)
