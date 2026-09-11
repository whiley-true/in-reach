from pathlib import Path

from in_reach.app import rvt_launcher


def test_resolve_rvt_exe_returns_the_bundled_executable() -> None:
    exe_path = rvt_launcher.resolve_rvt_exe()

    assert exe_path.name == "ReachVariantTool.exe"
    assert exe_path.is_file()


def test_launch_rvt_passes_just_the_bundled_exe_with_no_target() -> None:
    calls = []

    rvt_launcher.launch_rvt(popen=lambda args: calls.append(args))

    assert len(calls) == 1
    assert calls[0] == [str(rvt_launcher.resolve_rvt_exe())]


def test_launch_rvt_passes_the_target_bin_as_the_one_positional_argument(tmp_path: Path) -> None:
    target = tmp_path / "Slayer.bin"
    calls = []

    rvt_launcher.launch_rvt(target, popen=lambda args: calls.append(args))

    assert calls == [[str(rvt_launcher.resolve_rvt_exe()), str(target)]]


def test_launch_rvt_uses_an_explicit_exe_path_override_instead_of_resolving(tmp_path: Path) -> None:
    override = tmp_path / "OtherRVT.exe"
    calls = []

    rvt_launcher.launch_rvt(exe_path=override, popen=lambda args: calls.append(args))

    assert calls == [[str(override)]]


def test_launch_rvt_returns_whatever_popen_returns() -> None:
    # PROMPT.md: "if project is closed in ide, if Reach Variant tool is open for that project it
    # should be closed" -- MainWindow needs the process handle back to later terminate it.
    sentinel = object()

    result = rvt_launcher.launch_rvt(popen=lambda args: sentinel)

    assert result is sentinel
