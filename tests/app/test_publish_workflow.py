"""The release pipeline: ``publish.yml`` builds Windows wheels through ``native.yml`` and ``check_dist.py`` refuses
to upload anything unless ``dist/`` is exactly the release.

The workflows themselves can only be run by GitHub, so what's checked here is what can be: the gate script's
decisions, and that the workflow files agree with each other and with it (a renamed artifact, or a Python added
to one matrix and not the other, would otherwise only show up as a failed or half-finished release).
"""
import importlib.util
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_PUBLISH = (_REPO / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
_NATIVE = (_REPO / ".github" / "workflows" / "native.yml").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def check_dist():
    spec = importlib.util.spec_from_file_location("check_dist", _REPO / ".github" / "scripts" / "check_dist.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _release(version: str = "0.3.0") -> list[str]:
    return [
        f"in_reach-{version}.tar.gz",
        f"in_reach-{version}-cp312-cp312-win_amd64.whl",
        f"in_reach-{version}-cp313-cp313-win_amd64.whl",
        f"in_reach-{version}-cp314-cp314-win_amd64.whl",
    ]


# -- check_dist.py -----------------------------------------------------------------------------------------


def test_a_complete_release_passes(check_dist) -> None:
    assert check_dist.problems(_release()) == []


@pytest.mark.parametrize("tag", ["v0.3.0", "0.3.0"])
def test_the_tag_may_carry_a_leading_v(check_dist, tag: str) -> None:
    assert check_dist.problems(_release(), tag=tag) == []


def test_the_wheel_the_old_ubuntu_build_would_now_produce_is_refused(check_dist) -> None:
    """setup.py makes a wheel platform-specific, so building on Ubuntu tags it linux_x86_64: PyPI rejects that,
    and the sdist could already be up by then."""
    names = [n for n in _release() if "cp314" not in n] + ["in_reach-0.3.0-cp314-cp314-linux_x86_64.whl"]

    found = check_dist.problems(names)

    assert any("linux_x86_64" in problem and "win_amd64" in problem for problem in found)


def test_a_pure_python_any_wheel_is_refused(check_dist) -> None:
    """What the pipeline used to build: it would install on every platform with a Windows-only binary inside."""
    found = check_dist.problems([*_release(), "in_reach-0.3.0-py3-none-any.whl"])

    assert any("py3-none-any" in problem for problem in found)


def test_a_missing_python_is_reported(check_dist) -> None:
    found = check_dist.problems([n for n in _release() if "cp313" not in n])

    assert found == ["no wheel for Python 313"]


def test_an_extra_python_is_reported(check_dist) -> None:
    found = check_dist.problems([*_release(), "in_reach-0.3.0-cp315-cp315-win_amd64.whl"])

    assert found == ["unexpected wheel(s) for Python 315"]


def test_two_wheels_for_one_python_are_reported(check_dist) -> None:
    other_platform = "in_reach-0.3.0-cp312-cp312-win32.whl"

    found = check_dist.problems([*_release(), other_platform])

    assert any("more than one wheel for Python 312" in problem for problem in found)
    assert any("win32" in problem for problem in found)


@pytest.mark.parametrize("sdists", [[], ["in_reach-0.3.0.tar.gz", "in_reach-0.3.0.1.tar.gz"]], ids=["none", "two"])
def test_there_must_be_exactly_one_sdist(check_dist, sdists: list[str]) -> None:
    names = [n for n in _release() if not n.endswith(".tar.gz")] + sdists

    assert any("exactly one sdist" in problem for problem in check_dist.problems(names))


def test_files_of_different_versions_are_refused(check_dist) -> None:
    names = _release()
    names[1] = "in_reach-0.2.0-cp312-cp312-win_amd64.whl"

    assert any("disagree on the version" in problem for problem in check_dist.problems(names))


def test_a_version_that_is_not_the_release_tag_is_refused(check_dist) -> None:
    """A stale artifact, or a release cut without the version bump."""
    found = check_dist.problems(_release("0.2.0"), tag="v0.3.0")

    assert found == ["release tag 'v0.3.0' is version 0.3.0, but the files are 0.2.0"]


@pytest.mark.parametrize("name", ["notes.txt", "in_reach-0.3.0.zip", "in_reach-0.3.0-cp314-win_amd64.whl"])
def test_anything_else_in_dist_is_refused(check_dist, name: str) -> None:
    found = check_dist.problems([*_release(), name])

    assert any(problem.startswith(name) for problem in found)


def test_a_wheel_for_another_project_is_refused(check_dist) -> None:
    found = check_dist.problems([*[n for n in _release() if "cp314" not in n], "other-0.3.0-cp314-cp314-win_amd64.whl"])

    assert any("not a in_reach wheel" in problem for problem in found)


def test_a_wheel_whose_python_and_abi_disagree_is_refused(check_dist) -> None:
    names = [n for n in _release() if "cp314" not in n] + ["in_reach-0.3.0-cp314-abi3-win_amd64.whl"]

    assert any("aren't a matching cpXY pair" in problem for problem in check_dist.problems(names))


def test_every_problem_is_reported_not_just_the_first(check_dist) -> None:
    found = check_dist.problems(["in_reach-0.2.0-cp314-cp314-linux_x86_64.whl"], tag="v0.3.0")

    assert len(found) >= 4  # the platform, both missing Pythons, the missing sdist, the tag


def test_main_exits_zero_for_a_good_folder_and_one_for_a_bad_one(check_dist, tmp_path: Path, capsys) -> None:
    for name in _release():
        (tmp_path / name).write_bytes(b"")
    assert check_dist.main([str(tmp_path), "--tag", "v0.3.0"]) == 0
    assert "OK" in capsys.readouterr().out

    (tmp_path / "in_reach-0.3.0-cp312-cp312-win_amd64.whl").unlink()
    assert check_dist.main([str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "nothing was uploaded" in err and "no wheel for Python 312" in err


def test_main_refuses_a_missing_folder(check_dist, tmp_path: Path, capsys) -> None:
    assert check_dist.main([str(tmp_path / "nope")]) == 1


# -- the workflows agree with each other and with the script -----------------------------------------------


def test_publish_builds_its_wheels_through_native_yml(check_dist) -> None:
    assert re.search(r"^\s+uses: \./\.github/workflows/native\.yml\s*$", _PUBLISH, re.M)
    assert re.search(r"^\s+workflow_call:", _NATIVE, re.M), "native.yml must be callable"


def test_publish_no_longer_builds_a_wheel_on_ubuntu() -> None:
    builds = re.findall(r"python -m build[^\n]*", _PUBLISH)

    assert builds == ["python -m build --sdist"]


def test_publish_waits_for_the_wheels_and_the_sdist() -> None:
    publish_job = _PUBLISH[_PUBLISH.index("\n  publish:"):]

    assert re.search(r"needs: \[wheels, sdist\]", publish_job)


def test_the_gate_runs_before_anything_is_uploaded() -> None:
    assert _PUBLISH.index("check_dist.py") < _PUBLISH.index("pypa/gh-action-pypi-publish")


def test_the_gate_is_given_the_release_tag() -> None:
    assert '--tag "${{ github.event.release.tag_name }}"' in _PUBLISH


def test_publish_downloads_the_artifacts_native_yml_uploads() -> None:
    uploaded = re.search(r"name: (wheel-py)\$\{\{ matrix\.python-version \}\}", _NATIVE)
    assert uploaded, "native.yml should upload wheel-py<version>"
    assert f"pattern: {uploaded.group(1)}*" in _PUBLISH
    assert "name: sdist" in _PUBLISH  # the sdist job uploads it under this name, and the publish job asks for it


def test_the_wheel_matrix_is_the_set_of_pythons_the_gate_expects(check_dist) -> None:
    matrix = re.search(r'python-version: \[([^\]]+)\]', _NATIVE)
    versions = tuple(v.strip().strip('"').replace(".", "") for v in matrix.group(1).split(","))

    assert versions == check_dist.EXPECTED_PYTHONS


def test_the_wheel_job_checks_its_own_tag_the_same_way_the_gate_does(check_dist) -> None:
    assert "win_amd64" in _NATIVE and check_dist.PLATFORM == "win_amd64"


def test_native_yml_also_runs_on_main_so_a_release_finds_the_qt_cache() -> None:
    assert re.search(r"^\s+push:\s*\n\s+branches: \[main\]", _NATIVE, re.M)


def test_the_wheel_is_installed_and_imported_from_a_clean_environment_before_it_is_uploaded() -> None:
    """The tests import the source tree; only this proves the wheel itself carries a loadable native module."""
    smoke = _NATIVE[_NATIVE.index("Smoke-test the wheel"):_NATIVE.index("actions/upload-artifact")]

    assert "python -m venv" in smoke
    assert "'site-packages' in in_reach.__file__" in smoke  # imported from the install, not the checkout
    assert "rvt_bridge.is_available()" in smoke
    assert "$LASTEXITCODE" in smoke  # a native command failing doesn't stop a pwsh step by itself


def test_the_bump_label_check_reads_the_labels_live_not_from_the_event_snapshot() -> None:
    """The regression: Cut Release opens its PR and adds the label a moment later, so an ``opened`` run saw the payload's
    empty label list, failed, and (finishing last) left the required check red on a PR that had its label. Re-running it
    replays the same stale payload, so the check has to ask GitHub for the labels as they are now."""
    workflow = (Path(__file__).parents[2] / ".github" / "workflows" / "require-bump-label.yml").read_text(encoding="utf-8")

    code = "\n".join(line for line in workflow.splitlines() if not line.strip().startswith("#"))  # the comments explain it

    assert "issues/${PR_NUMBER}/labels" in code and "github.event.pull_request.labels" not in code
    assert "cancel-in-progress: true" in workflow  # the newest event wins
