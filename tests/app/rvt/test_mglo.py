from pathlib import Path

from in_reach.app import rvt_launcher
from in_reach.app.rvt import mglo


def _fake_run(returncode: int, *, touch: Path | None = None):
    def run(args, **kwargs):
        if touch is not None:
            touch.write_bytes(b"")

        class _Result:
            pass

        result = _Result()
        result.returncode = returncode
        result.stdout = ""
        result.stderr = ""
        return result

    return run


def test_write_mglo_invokes_the_headless_cli_with_the_expected_arguments(tmp_path: Path) -> None:
    bin_path = tmp_path / "build" / "dist" / "Slayer.bin"
    script_path = tmp_path / "script" / "output.txt"
    dest_path = tmp_path / "Slayer.mglo"
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        dest_path.write_bytes(b"")

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    ok = mglo.write_mglo(bin_path, script_path, dest_path, run=run)

    assert ok is True
    assert calls == [
        [
            str(rvt_launcher.resolve_rvt_exe()),
            "--headless",
            str(bin_path),
            "--recompile",
            str(script_path),
            "--dst",
            str(dest_path),
        ]
    ]


def test_write_mglo_returns_false_on_a_nonzero_exit_code(tmp_path: Path) -> None:
    dest_path = tmp_path / "Slayer.mglo"

    ok = mglo.write_mglo(tmp_path / "in.bin", tmp_path / "script.txt", dest_path, run=_fake_run(1))

    assert ok is False


def test_write_mglo_returns_false_if_the_dest_file_was_not_actually_written(tmp_path: Path) -> None:
    dest_path = tmp_path / "Slayer.mglo"  # run() reports success but never creates the file

    ok = mglo.write_mglo(tmp_path / "in.bin", tmp_path / "script.txt", dest_path, run=_fake_run(0))

    assert ok is False


def test_write_mglo_returns_false_if_launching_rvt_raises_oserror(tmp_path: Path) -> None:
    def run(args, **kwargs):
        raise OSError("no such file")

    ok = mglo.write_mglo(tmp_path / "in.bin", tmp_path / "script.txt", tmp_path / "out.mglo", run=run)

    assert ok is False
