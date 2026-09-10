import json
import re
from pathlib import Path

import pytest

from in_reach.app import env_file, new_project
from in_reach.app.categories import EngineCategory, EngineIcon
from in_reach.app.rvt import rvt_bridge

#: PROMPT.md: "can it be a short uuid" -- 8-character base64url tokens (see
#: new_project._generate_project_id's own docstring for why base64url rather than hex).
_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8}$")

_JUGGERNAUT_BIN = Path(__file__).parent / "rvt" / "resources" / "juggernaut" / "juggernaut.bin"
_NEEDS_NATIVE_RVT = pytest.mark.skipif(
    not rvt_bridge.is_available(), reason="native _reachvarianttool extension not available on this platform"
)
_NEEDS_NATIVE_RVT_AND_JUGGERNAUT_BIN = pytest.mark.skipif(
    not (_JUGGERNAUT_BIN.is_file() and rvt_bridge.is_available()),
    reason="fixture .bin not present, or native _reachvarianttool extension not available on this platform",
)


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    project = tmp_path / ".in-reach"
    project.mkdir()
    (project / ".env").write_text("", encoding="utf-8")
    return project


@pytest.mark.parametrize(
    "title",
    [
        "My Gametype",
        "a",
        "x" * new_project.MAX_TITLE_LENGTH,
        "CONTEST",
        # No longer folder-name rules -- a title can contain anything a Windows folder name
        # couldn't, since it no longer names the project folder (see is_valid_title's docstring).
        "no/slashes needed now",
        "trailing space ",
        "trailing dot.",
        "CON",
    ],
)
def test_valid_titles(title: str) -> None:
    assert new_project.is_valid_title(title) is True


@pytest.mark.parametrize("title", ["", "   ", "x" * (new_project.MAX_TITLE_LENGTH + 1)])
def test_invalid_titles(title: str) -> None:
    assert new_project.is_valid_title(title) is False


def test_create_gametype_project_names_the_folder_with_a_generated_id_not_the_title(
    project_dir: Path, tmp_path: Path
) -> None:
    folder, warning = new_project.create_gametype_project(project_dir, "Slayer Plus", "A better slayer")

    assert warning is None
    assert folder.parent == tmp_path
    assert folder.name != "Slayer Plus"
    # PROMPT.md: "can it be a short uuid" -- a short base64url token, unambiguous at a glance next
    # to dulwich's own 40-char, hex-only SHA-1 object ids.
    assert _PROJECT_ID_RE.match(folder.name)
    assert (folder / "settings").is_dir()
    assert (folder / "script").is_dir()
    assert (folder / "build" / "dist").is_dir()
    # build/ is regenerated from settings/, so it ignores itself rather than relying on the user's
    # own repo-level .gitignore.
    assert (folder / "build" / ".gitignore").read_text(encoding="utf-8") == "*\n!.gitignore\n"

    # PROMPT.md: "please also add a Notes.txt (with first line Use this space for free form notes)".
    notes = (folder / "Notes.txt").read_text(encoding="utf-8")
    assert notes.splitlines()[0] == "Use this space for free form notes."
    # PROMPT.md: "please remove the README.md file completely".
    assert not (folder / "README.md").exists()


def test_create_gametype_project_points_project_dir_at_the_new_folder(project_dir: Path) -> None:
    folder, _warning = new_project.create_gametype_project(project_dir, "Slayer Plus")

    values = env_file.get_env_values(project_dir / ".env")
    assert values[new_project.PROJECT_DIR_KEY] == str(folder)


def test_description_max_length_is_137_and_unrelated_to_windows_naming_rules() -> None:
    assert new_project.MAX_DESCRIPTION_LENGTH == 137


@_NEEDS_NATIVE_RVT
def test_description_accepts_characters_a_windows_folder_name_would_reject(project_dir: Path) -> None:
    # PROMPT.md (historical): titles/descriptions no longer name the project folder, so they can
    # contain characters a Windows folder name would reject -- stamped into settings/settings.json
    # (via a real decompile of the bundled blank template) rather than a folder name or a README.
    from in_reach.app.blank_variant import resolve_blank_variant

    description = 'Faster / stronger * better: now with "quotes" <and> a trailing dot.'

    folder, warning = new_project.create_gametype_project(
        project_dir, "Slayer Plus", description, source_variant=resolve_blank_variant(firefight=False)
    )

    assert warning is None
    settings = json.loads((folder / "settings" / "settings.json").read_text(encoding="utf-8"))
    assert settings["meta"]["description"] == description


def test_create_gametype_project_copies_the_source_variant_in_named_after_the_id(
    project_dir: Path, tmp_path: Path
) -> None:
    source = tmp_path / "variants" / "Original.bin"
    source.parent.mkdir()
    source.write_bytes(b"\x00variant")

    folder, _warning = new_project.create_gametype_project(
        project_dir, "Slayer Plus", source_variant=source
    )

    copied = project_dir / new_project.INIT_GAMETYPE_DIRNAME / f"{folder.name}.bin"
    assert copied.read_bytes() == b"\x00variant"


@_NEEDS_NATIVE_RVT_AND_JUGGERNAUT_BIN
def test_create_gametype_project_decompiles_a_real_source_variant(
    project_dir: Path,
) -> None:
    """PROMPT.md: "when a project is selected the gametype is decompiled as in the previous
    repos" -- exercises the real bundled native extension against a real .bin fixture, not fakes."""
    folder, warning = new_project.create_gametype_project(project_dir, "Slayer Plus", source_variant=_JUGGERNAUT_BIN)

    assert warning is None
    settings = json.loads((folder / "settings" / "settings.json").read_text(encoding="utf-8"))
    # PROMPT.md: "when setting a title and description, this is not being set in settings.json" --
    # this project's own title (typed into the New Project dialog) now overrides whatever the
    # source .bin's own header happened to say ("JUGGERNAUT"), same as category/category_icon.
    assert settings["meta"]["title"] == "Slayer Plus"
    assert (folder / "settings" / "script_settings.json").is_file()
    assert (folder / "settings" / "strings.json").is_file()
    assert (folder / "build" / "valid_maps.json").is_file()
    script = (folder / "script" / "output.txt").read_text(encoding="utf-8")
    assert "declare" in script
    assert (folder / "build" / "stats.autogenerated.json").is_file()


def test_create_gametype_project_surfaces_a_decompile_failure_as_a_warning_not_a_crash(
    project_dir: Path,
) -> None:
    """A .bin the native extension can't load shouldn't block the project from being created --
    see new_project._decompile_source_variant()'s docstring."""
    bad_source = project_dir.parent / "not-a-real-variant.bin"
    bad_source.write_bytes(b"not a real .bin")

    folder, warning = new_project.create_gametype_project(project_dir, "Slayer Plus", source_variant=bad_source)

    assert folder.is_dir()
    assert warning is not None
    assert not (folder / "script" / "output.txt").is_file()


def test_create_gametype_project_rejects_an_empty_title(project_dir: Path) -> None:
    with pytest.raises(ValueError):
        new_project.create_gametype_project(project_dir, "   ")


def test_two_projects_created_in_a_row_get_different_ids(project_dir: Path) -> None:
    first, _warning = new_project.create_gametype_project(project_dir, "One")
    second, _warning = new_project.create_gametype_project(project_dir, "Two")

    assert first != second


# -- short project ids (PROMPT.md: "can it be a short uuid for project folder" -- following on
# from an earlier pass, "please use a uuid that is just a different uuid scheme the[n] used by
# dulwich (the vcs we will be adding)") -----------------------------------------------------------


def test_generate_project_id_returns_a_short_base64url_token(tmp_path: Path) -> None:
    candidate = new_project._generate_project_id(tmp_path)

    assert _PROJECT_ID_RE.match(candidate)


def test_generate_project_id_is_not_shaped_like_a_dulwich_sha1_object_id(tmp_path: Path) -> None:
    # Dulwich (and git generally) identifies objects by a 40-character, hex-only SHA-1 digest --
    # a base64url token must never be mistakable for one at a glance, truncated or not.
    candidate = new_project._generate_project_id(tmp_path)

    assert len(candidate) != 40
    assert not re.fullmatch(r"[0-9a-fA-F]+", candidate)


def test_generate_project_id_never_returns_a_name_already_used_under_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    used = "usedtoken"
    free = "freetoken"
    (tmp_path / used).mkdir()
    calls = iter([used, free])
    monkeypatch.setattr(new_project.secrets, "token_urlsafe", lambda nbytes: next(calls))

    candidate = new_project._generate_project_id(tmp_path)

    assert candidate == free


def test_generate_project_id_gives_up_after_max_attempts_of_pure_collisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collider = "alwaysthesame"
    (tmp_path / collider).mkdir()
    monkeypatch.setattr(new_project.secrets, "token_urlsafe", lambda nbytes: collider)

    with pytest.raises(FileExistsError):
        new_project._generate_project_id(tmp_path)


# -- category / category_icon ------------------------------------------------------------------


@_NEEDS_NATIVE_RVT_AND_JUGGERNAUT_BIN
def test_create_gametype_project_defaults_to_no_category_and_no_warning(project_dir: Path) -> None:
    folder, warning = new_project.create_gametype_project(
        project_dir, "Blank", source_variant=_JUGGERNAUT_BIN
    )

    assert warning is None
    document = (folder / "settings" / "settings.json").read_text(encoding="utf-8")
    assert '"category": "none"' in document


@_NEEDS_NATIVE_RVT_AND_JUGGERNAUT_BIN
def test_create_gametype_project_writes_a_matching_category_and_icon_by_default(
    project_dir: Path,
) -> None:
    folder, warning = new_project.create_gametype_project(
        project_dir, "Slayer Plus", category=EngineCategory.slayer, source_variant=_JUGGERNAUT_BIN
    )

    assert warning is None
    document = (folder / "settings" / "settings.json").read_text(encoding="utf-8")
    assert '"category": "slayer"' in document
    assert '"category_icon": "slayer"' in document


@_NEEDS_NATIVE_RVT_AND_JUGGERNAUT_BIN
def test_create_gametype_project_reports_a_deliberate_mismatch(project_dir: Path) -> None:
    folder, warning = new_project.create_gametype_project(
        project_dir,
        "Odd Slayer",
        category=EngineCategory.slayer,
        category_icon=EngineIcon.oddball,
        source_variant=_JUGGERNAUT_BIN,
    )

    assert warning is not None
    assert "Slayer" in warning and "Oddball" in warning
    document = (folder / "settings" / "settings.json").read_text(encoding="utf-8")
    assert '"category_icon": "oddball"' in document


def test_create_gametype_project_with_no_source_variant_writes_no_settings_json(
    project_dir: Path,
) -> None:
    # Category/category_icon now live in the decompiled settings.json (PROMPT.md) -- a truly blank
    # project (no .bin to decompile at all) simply has nowhere to persist them, same as it already
    # had no script/output.txt content in that case.
    folder, warning = new_project.create_gametype_project(
        project_dir, "Blank", category=EngineCategory.slayer
    )

    assert warning is None
    assert not (folder / "settings" / "settings.json").exists()


# -- title / description --------------------------------------------------------------------------


@_NEEDS_NATIVE_RVT_AND_JUGGERNAUT_BIN
def test_create_gametype_project_stamps_title_and_description_into_settings_json(
    project_dir: Path,
) -> None:
    folder, warning = new_project.create_gametype_project(
        project_dir, "Slayer Plus", "A friendly slayer variant", source_variant=_JUGGERNAUT_BIN
    )

    assert warning is None
    settings = json.loads((folder / "settings" / "settings.json").read_text(encoding="utf-8"))
    assert settings["meta"]["title"] == "Slayer Plus"
    assert settings["meta"]["description"] == "A friendly slayer variant"


# -- maps.json ------------------------------------------------------------------------------------


def test_create_gametype_project_scans_map_folders_into_maps_json(
    project_dir: Path, tmp_path: Path
) -> None:
    from mvar_fixtures import build_chdr_bytes

    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()
    (maps_dir / "Forge.mvar").write_bytes(build_chdr_bytes(title="My Forge Map", map_id=3006))

    folder, _warning = new_project.create_gametype_project(
        project_dir, "Slayer Plus", personal_maps_dir=maps_dir
    )

    # PROMPT.md: the shared/master scan lives once in .in-reach, not duplicated per project --
    # "there should be no maps dir anymore".
    assert (project_dir / "maps.json").is_file()
    assert not (folder / "maps.json").exists()
    assert not (folder / "maps").exists()
    document = (project_dir / "maps.json").read_text(encoding="utf-8")
    assert "My Forge Map" in document


def test_create_gametype_project_with_no_map_folders_still_writes_an_empty_maps_json(
    project_dir: Path,
) -> None:
    new_project.create_gametype_project(project_dir, "Blank")

    document = (project_dir / "maps.json").read_text(encoding="utf-8")
    assert '"maps": []' in document


def test_two_projects_created_in_a_row_share_the_same_maps_json(
    project_dir: Path, tmp_path: Path
) -> None:
    from mvar_fixtures import build_chdr_bytes

    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()
    (maps_dir / "Forge.mvar").write_bytes(build_chdr_bytes(title="My Forge Map", map_id=3006))

    first, _warning = new_project.create_gametype_project(project_dir, "One")
    second, _warning = new_project.create_gametype_project(
        project_dir, "Two", personal_maps_dir=maps_dir
    )

    # The first project's own creation predates the maps folder existing at all -- confirms the
    # second project's scan overwrote the one shared file rather than each project getting (or
    # needing) its own.
    document = (project_dir / "maps.json").read_text(encoding="utf-8")
    assert "My Forge Map" in document
    assert not (first / "maps.json").exists()
    assert not (second / "maps.json").exists()


# -- read_project_title -----------------------------------------------------------------------


@_NEEDS_NATIVE_RVT
def test_read_project_title_reads_back_settings_jsons_own_meta_title(project_dir: Path) -> None:
    # PROMPT.md: "please remove the README.md file completely" -- settings.json was always the
    # authoritative copy of the title (via a real decompile of the bundled blank template here).
    from in_reach.app.blank_variant import resolve_blank_variant

    folder, warning = new_project.create_gametype_project(
        project_dir, "Slayer Plus", source_variant=resolve_blank_variant(firefight=False)
    )

    assert warning is None
    assert new_project.read_project_title(folder) == "Slayer Plus"


def test_read_project_title_falls_back_to_the_folder_name_without_a_settings_json(tmp_path: Path) -> None:
    folder = tmp_path / "abcd1234"
    folder.mkdir()

    assert new_project.read_project_title(folder) == "abcd1234"


def test_read_project_title_falls_back_to_the_folder_name_for_unparseable_settings_json(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "abcd1234"
    (folder / "settings").mkdir(parents=True)
    (folder / "settings" / "settings.json").write_text("{not valid json", encoding="utf-8")

    assert new_project.read_project_title(folder) == "abcd1234"


def test_read_project_title_falls_back_to_the_folder_name_for_a_blank_title(tmp_path: Path) -> None:
    folder = tmp_path / "abcd1234"
    (folder / "settings").mkdir(parents=True)
    (folder / "settings" / "settings.json").write_text('{"meta": {"title": ""}}', encoding="utf-8")

    assert new_project.read_project_title(folder) == "abcd1234"


# -- list_variants ----------------------------------------------------------------------------


def test_list_variants_returns_bins_by_name_case_insensitively(tmp_path: Path) -> None:
    folder = tmp_path / "game_variants"
    folder.mkdir()
    for name in ("zulu.bin", "Alpha.bin", "notes.txt"):
        (folder / name).write_bytes(b"")
    (folder / "nested").mkdir()

    assert new_project.list_variants(folder) == [
        ("Alpha", folder / "Alpha.bin"),
        ("zulu", folder / "zulu.bin"),
    ]


def test_list_variants_of_a_missing_folder_is_empty(tmp_path: Path) -> None:
    assert new_project.list_variants(tmp_path / "nope") == []


# -- source_variant_path ------------------------------------------------------------------------


def test_source_variant_path_matches_where_create_gametype_project_copies_it(
    project_dir: Path,
) -> None:
    source = project_dir.parent / "Original.bin"
    source.write_bytes(b"\x00variant")

    folder, _warning = new_project.create_gametype_project(
        project_dir, "Slayer Plus", source_variant=source
    )

    expected = new_project.source_variant_path(project_dir, folder)
    assert expected.is_file()
    assert expected.read_bytes() == b"\x00variant"


# -- compiled_variant_path ----------------------------------------------------------------------


def test_compiled_variant_path_is_under_build_dist_named_after_the_folder(tmp_path: Path) -> None:
    folder = tmp_path / "abcd1234"

    assert new_project.compiled_variant_path(folder) == folder / "build" / "dist" / "abcd1234.bin"


def test_compiled_variant_path_differs_from_source_variant_path(project_dir: Path) -> None:
    # PROMPT.md: "when clicking into rvt, it seems to be showing blank gametype and description
    # not the contents from the saved settings" -- these must never resolve to the same file, or
    # RVT would still open the frozen original instead of whatever was actually compiled.
    folder, _warning = new_project.create_gametype_project(project_dir, "Slayer Plus")

    assert new_project.compiled_variant_path(folder) != new_project.source_variant_path(project_dir, folder)


# -- is_generated_file -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "relative",
    [
        "build/dist/test.bin",
        "build/dist/test.mglo",
        "build/settings.autogenerated.json",
        "build/script_settings.autogenerated.json",
        "build/strings.autogenerated.json",
        "build/stats.autogenerated.json",
        "settings.autogenerated.json",  # the name alone is enough, regardless of folder
        # PROMPT.md: "schema files should be non-editable (by hand)"; later: "move
        # settings/schemas into schemas" -- moved to a project-root folder of their own.
        "schemas/settings.schema.json",
        "schemas/script_settings.schema.json",
        "schemas/strings.schema.json",
        "settings.schema.json",  # the name alone is enough, regardless of folder
        # PROMPT.md: "move settings/valid_maps.json to build/valid_maps.json".
        "build/valid_maps.json",
    ],
)
def test_is_generated_file_true_for_build_output(tmp_path: Path, relative: str) -> None:
    assert new_project.is_generated_file(tmp_path / relative) is True


@pytest.mark.parametrize(
    "relative",
    [
        "settings/settings.json",
        "settings/script_settings.json",
        "settings/strings.json",
        "script/output.txt",
        "README.md",
        "Notes.txt",
        "maps.json",
    ],
)
def test_is_generated_file_false_for_hand_editable_source(tmp_path: Path, relative: str) -> None:
    assert new_project.is_generated_file(tmp_path / relative) is False
