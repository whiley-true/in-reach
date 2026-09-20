"""Shared modules: adding one from a folder or a git repository, pinning it, verifying the pin, updating it."""
import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from hill_project import hill_rush

from in_reach import api
from in_reach.app.script_project import link, load_project, packages
from in_reach.cli import main

_MODULE_TOML = '[module]\nname = "shared_speed"\nversion = "1.0.0"\nlicense = "GPL-3.0"\nauthors = ["A. Author"]\ndescription = "Everyone runs faster."\nmin_in_reach = "0.1.0"\n'
_MODULE_MGL = '-- @trait t_shared { name = "Shared", movement_speed = "value_120" }\n-- @fragment HILL_PASS.shared\n-- @loop player\ncurrent_player.apply_traits(t_shared)\n'


def _shared_module(directory: Path, version: str = "1.0.0", body: str = _MODULE_MGL) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    # bytes, not write_text: on Windows that would turn every newline into CRLF, and these tests need to say which they mean
    (directory / "module.toml").write_bytes(_MODULE_TOML.replace('version = "1.0.0"', f'version = "{version}"').encode("utf-8"))
    (directory / "shared_speed.mgl").write_bytes(body.encode("utf-8"))
    return directory


def _git_repo(directory: Path, subdir: str | None = None) -> str:
    """A git repository with the shared module committed (optionally under ``subdir``); returns the head commit."""
    from dulwich import porcelain

    directory.mkdir(parents=True, exist_ok=True)
    porcelain.init(str(directory))
    _shared_module(directory / subdir if subdir else directory)
    porcelain.add(str(directory))
    return porcelain.commit(str(directory), message=b"first", author=b"T <t@example.com>", committer=b"T <t@example.com>").decode()


# -- hashing ---------------------------------------------------------------------------------------------------


def test_the_hash_is_the_same_for_crlf_and_lf_checkouts(tmp_path: Path) -> None:
    lf, crlf = _shared_module(tmp_path / "lf"), _shared_module(tmp_path / "crlf")
    for path in crlf.iterdir():
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))

    assert packages.tree_hash(lf) == packages.tree_hash(crlf)


def test_the_hash_changes_with_content_names_and_new_files(tmp_path: Path) -> None:
    module = _shared_module(tmp_path / "m")
    before = packages.tree_hash(module)

    (module / "shared_speed.mgl").write_text(_MODULE_MGL + "-- more\n", encoding="utf-8")
    edited = packages.tree_hash(module)
    (module / "shared_speed.mgl").rename(module / "renamed.mgl")
    renamed = packages.tree_hash(module)
    (module / "extra.mgl").write_text("", encoding="utf-8")

    assert len({before, edited, renamed, packages.tree_hash(module)}) == 4


def test_git_metadata_and_bytecode_are_not_part_of_the_hash(tmp_path: Path) -> None:
    module = _shared_module(tmp_path / "m")
    before = packages.tree_hash(module)
    (module / ".git").mkdir()
    (module / ".git" / "HEAD").write_text("x", encoding="utf-8")
    (module / "__pycache__").mkdir()
    (module / "__pycache__" / "a.pyc").write_bytes(b"1")

    assert packages.tree_hash(module) == before


# -- adding from a folder ------------------------------------------------------------------------------------------


def test_adding_a_module_vendors_its_files_records_the_source_and_pins_it(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "proj")
    source = _shared_module(tmp_path / "shared" / "speed")

    added = packages.add_module(folder, str(source))

    assert (added.name, added.version) == ("shared_speed", "1.0.0")
    assert added.files == ["script/modules/shared_speed/module.toml", "script/modules/shared_speed/shared_speed.mgl"]
    assert (folder / "script" / "modules" / "shared_speed" / "shared_speed.mgl").read_text(encoding="utf-8") == _MODULE_MGL
    project_toml = (folder / "script" / "project.toml").read_text(encoding="utf-8")
    assert 'name = "shared_speed"' in project_toml and "source = " in project_toml
    lock = packages.read_lock(folder)["shared_speed"]
    assert lock.sha256 == packages.tree_hash(folder / "script" / "modules" / "shared_speed") and lock.version == "1.0.0"


def test_an_added_module_builds_with_the_project(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "proj")
    packages.add_module(folder, str(_shared_module(tmp_path / "speed")))

    result = link(folder, write=False)

    assert result.ok, [str(d) for d in result.diagnostics]
    assert "alias t_shared = script_traits[1]" in result.compiled  # after hill_buff's own trait
    assert load_project(folder).diagnostics == []  # the pin matches, so the loader has nothing to say


def test_the_project_toml_keeps_its_comments_and_other_entries(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "proj")
    toml = folder / "script" / "project.toml"
    toml.write_text("# my project\n" + toml.read_text(encoding="utf-8"), encoding="utf-8")

    packages.add_module(folder, str(_shared_module(tmp_path / "speed")))

    text = toml.read_text(encoding="utf-8")
    assert text.startswith("# my project") and text.count("[[modules]]") == 3


def test_a_relative_path_is_relative_to_where_it_was_typed(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "proj")
    _shared_module(tmp_path / "libs" / "speed")

    added = packages.add_module(folder, "libs/speed", base=tmp_path)

    assert added.name == "shared_speed" and added.source.startswith("path:")


def test_a_module_can_be_added_under_another_name(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "proj")

    added = packages.add_module(folder, str(_shared_module(tmp_path / "speed")), name="go_fast")

    assert added.name == "go_fast" and (folder / "script" / "modules" / "go_fast").is_dir()


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        ("nothing", "is not a folder"),
        ("not_a_module", "isn't a module"),
        ("bad_name", "valid module name"),
        ("taken", "already exists"),
    ],
)
def test_bad_sources_and_names_are_refused_and_change_nothing(tmp_path: Path, setup: str, message: str) -> None:
    folder = hill_rush(tmp_path / "proj")
    source = tmp_path / "speed"
    name = None
    if setup == "not_a_module":
        source.mkdir()
    elif setup == "bad_name":
        _shared_module(source)
        name = "9 bad"
    elif setup == "taken":
        _shared_module(source)
        name = "hill_score"
    before = (folder / "script" / "project.toml").read_text(encoding="utf-8")

    with pytest.raises(packages.PackageError, match=message):
        packages.add_module(folder, str(source), name=name)

    assert (folder / "script" / "project.toml").read_text(encoding="utf-8") == before
    assert not (folder / "script" / "project.lock").exists()


def test_adding_needs_a_script_project(tmp_path: Path) -> None:
    with pytest.raises(packages.PackageError, match="no script/project.toml"):
        packages.add_module(tmp_path, str(_shared_module(tmp_path / "m")))


def test_a_module_that_needs_a_newer_in_reach_warns(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "proj")
    source = _shared_module(tmp_path / "speed")
    (source / "module.toml").write_text(_MODULE_TOML.replace("0.1.0", "99.0.0"), encoding="utf-8")

    added = packages.add_module(folder, str(source))

    assert added.warnings and "needs in-reach 99.0.0" in added.warnings[0]


def test_the_shared_manifest_fields_are_read_without_a_warning(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "proj")
    packages.add_module(folder, str(_shared_module(tmp_path / "speed")))

    module = next(m for m in load_project(folder).modules if m.name == "shared_speed")

    assert module.manifest.module.license == "GPL-3.0" and module.manifest.module.authors == ["A. Author"]


# -- verifying ------------------------------------------------------------------------------------------------------


def test_a_fresh_pin_verifies_clean(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "proj")
    packages.add_module(folder, str(_shared_module(tmp_path / "speed")))

    assert packages.verify_modules(folder) == []


def test_a_locally_edited_module_is_a_mismatch_here_and_a_warning_when_loading(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "proj")
    packages.add_module(folder, str(_shared_module(tmp_path / "speed")))
    edited = folder / "script" / "modules" / "shared_speed" / "shared_speed.mgl"
    edited.write_text(edited.read_text(encoding="utf-8") + "-- local tweak\n", encoding="utf-8")

    [problem] = packages.verify_modules(folder)
    loaded = [d for d in load_project(folder).diagnostics if d.code == "lock-mismatch"]

    assert (problem.severity, problem.code) == ("error", "lock-mismatch") and "shared_speed" in problem.message
    assert [d.severity for d in loaded] == ["warning"] and link(folder, write=False).ok  # editing is allowed


def test_a_deleted_module_is_reported(tmp_path: Path) -> None:
    import shutil

    folder = hill_rush(tmp_path / "proj")
    packages.add_module(folder, str(_shared_module(tmp_path / "speed")))
    shutil.rmtree(folder / "script" / "modules" / "shared_speed")

    assert [d.code for d in packages.verify_modules(folder)] == ["lock-missing"]


def test_a_source_with_no_lock_entry_and_a_lock_entry_with_no_source_are_warnings(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "proj")
    packages.add_module(folder, str(_shared_module(tmp_path / "speed")))
    (folder / "script" / "project.lock").unlink()

    assert [(d.code, d.severity) for d in packages.verify_modules(folder)] == [("lock-unlocked", "warning")]

    packages.lock_modules(folder)
    toml = folder / "script" / "project.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace("source = ", "# source = "), encoding="utf-8")
    assert [d.code for d in packages.verify_modules(folder)] == ["lock-orphan"]


def test_locking_keeps_local_edits_by_pinning_them(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "proj")
    packages.add_module(folder, str(_shared_module(tmp_path / "speed")))
    edited = folder / "script" / "modules" / "shared_speed" / "shared_speed.mgl"
    edited.write_text(edited.read_text(encoding="utf-8") + "-- local tweak\n", encoding="utf-8")

    entries = packages.lock_modules(folder)

    assert entries["shared_speed"].sha256 == packages.tree_hash(edited.parent) and packages.verify_modules(folder) == []


def test_locking_a_module_whose_folder_is_gone_says_how_to_restore_it(tmp_path: Path) -> None:
    import shutil

    folder = hill_rush(tmp_path / "proj")
    packages.add_module(folder, str(_shared_module(tmp_path / "speed")))
    shutil.rmtree(folder / "script" / "modules" / "shared_speed")

    with pytest.raises(packages.PackageError, match="module update shared_speed"):
        packages.lock_modules(folder)


def test_hand_made_modules_are_not_locked(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "proj")

    assert packages.lock_modules(folder) == {} and packages.read_lock(folder) == {}


# -- updating ----------------------------------------------------------------------------------------------------------


def test_updating_replaces_the_vendored_files_from_the_source(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "proj")
    source = _shared_module(tmp_path / "speed")
    packages.add_module(folder, str(source))
    _shared_module(source, version="1.1.0", body=_MODULE_MGL.replace("value_120", "value_150"))
    (folder / "script" / "modules" / "shared_speed" / "shared_speed.mgl").write_text("-- local edit lost\n", encoding="utf-8")

    updated = packages.update_module(folder, "shared_speed")

    assert updated.version == "1.1.0"
    assert "value_150" in (folder / "script" / "modules" / "shared_speed" / "shared_speed.mgl").read_text(encoding="utf-8")
    assert packages.read_lock(folder)["shared_speed"].version == "1.1.0" and packages.verify_modules(folder) == []


def test_updating_a_module_with_no_source_is_refused(tmp_path: Path) -> None:
    with pytest.raises(packages.PackageError, match="no source to update from"):
        packages.update_module(hill_rush(tmp_path / "proj"), "hill_score")


# -- git sources ------------------------------------------------------------------------------------------------------


def test_a_git_module_is_pinned_to_the_commit_it_was_fetched_at(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "proj")
    commit = _git_repo(tmp_path / "repo")

    added = packages.add_module(folder, f"git+{(tmp_path / 'repo').as_posix()}")

    assert added.source == f"git+{(tmp_path / 'repo').as_posix()}@{commit}"
    assert (folder / "script" / "modules" / "shared_speed" / "module.toml").is_file()
    assert not (folder / "script" / "modules" / "shared_speed" / ".git").exists()


def test_a_git_module_can_live_in_a_subdirectory_of_the_repository(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "proj")
    _git_repo(tmp_path / "repo", subdir="modules/speed")

    added = packages.add_module(folder, f"git+{(tmp_path / 'repo').as_posix()}#subdir=modules/speed")

    assert added.name == "shared_speed" and added.source.endswith("#subdir=modules/speed")


def test_a_git_revision_can_be_asked_for(tmp_path: Path) -> None:
    from dulwich import porcelain

    folder = hill_rush(tmp_path / "proj")
    first = _git_repo(tmp_path / "repo")
    (tmp_path / "repo" / "shared_speed.mgl").write_text(_MODULE_MGL + "-- second\n", encoding="utf-8")
    porcelain.add(str(tmp_path / "repo"))
    porcelain.commit(str(tmp_path / "repo"), message=b"second", author=b"T <t@example.com>", committer=b"T <t@example.com>")

    added = packages.add_module(folder, f"git+{(tmp_path / 'repo').as_posix()}", rev=first)

    assert added.source.endswith(f"@{first}")
    assert "second" not in (folder / "script" / "modules" / "shared_speed" / "shared_speed.mgl").read_text(encoding="utf-8")


def test_updating_a_git_module_follows_the_sources_new_head(tmp_path: Path) -> None:
    from dulwich import porcelain

    folder = hill_rush(tmp_path / "proj")
    first = _git_repo(tmp_path / "repo")
    packages.add_module(folder, f"git+{(tmp_path / 'repo').as_posix()}")
    (tmp_path / "repo" / "shared_speed.mgl").write_text(_MODULE_MGL + "-- second\n", encoding="utf-8")
    porcelain.add(str(tmp_path / "repo"))
    second = porcelain.commit(str(tmp_path / "repo"), message=b"second", author=b"T <t@example.com>", committer=b"T <t@example.com>").decode()

    updated = packages.update_module(folder, "shared_speed")

    assert updated.source.endswith(f"@{second}") and not updated.source.endswith(f"@{first}")
    assert "-- second" in (folder / "script" / "modules" / "shared_speed" / "shared_speed.mgl").read_text(encoding="utf-8")


def test_a_git_source_that_does_not_exist_is_a_readable_error(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "proj")

    with pytest.raises(packages.PackageError, match="couldn't fetch"):
        packages.add_module(folder, f"git+{(tmp_path / 'nowhere').as_posix()}")


# -- the command line and the api --------------------------------------------------------------------------------------


def test_the_module_commands_add_lock_verify_and_update(tmp_path: Path) -> None:
    runner = CliRunner()
    folder = hill_rush(tmp_path / "proj")
    source = _shared_module(tmp_path / "speed")

    added = runner.invoke(main, ["module", "add", str(source), "--folder", str(folder), "--format", "json"])
    verified = runner.invoke(main, ["module", "verify", str(folder), "--format", "json"])
    (folder / "script" / "modules" / "shared_speed" / "shared_speed.mgl").write_text("-- edited\n", encoding="utf-8")
    broken = runner.invoke(main, ["module", "verify", str(folder)])
    locked = runner.invoke(main, ["module", "lock", str(folder), "--format", "json"])
    updated = runner.invoke(main, ["module", "update", "shared_speed", "--folder", str(folder)])

    assert json.loads(added.output)["name"] == "shared_speed" and added.exit_code == 0
    assert json.loads(verified.output)["ok"] is True
    assert broken.exit_code == 1 and "lock-mismatch" in broken.output
    assert json.loads(locked.output)["locked"][0]["name"] == "shared_speed"
    assert updated.exit_code == 0 and "updated shared_speed 1.0.0" in updated.output


def test_the_module_commands_report_a_bad_source_with_exit_1(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "proj")

    result = CliRunner().invoke(main, ["module", "add", str(tmp_path / "nothing"), "--folder", str(folder)])

    assert result.exit_code == 1 and "is not a folder" in result.output


def test_verify_of_a_single_script_project_is_an_api_error(tmp_path: Path) -> None:
    with pytest.raises(api.ApiError):
        api.verify_modules(tmp_path)
