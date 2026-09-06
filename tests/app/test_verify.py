import platform
from pathlib import Path

from in_reach.app import env_file, verify


def test_verify_project_fills_a_blank_env_file(tmp_path: Path) -> None:
    project_dir = tmp_path / ".in-reach"
    project_dir.mkdir()

    verify.verify_project(project_dir)

    values = env_file.get_env_values(project_dir / ".env")
    assert values["ROOT_DIR"] == str(tmp_path)
    assert values["IS_WINDOWS"] == ("true" if platform.system() == "Windows" else "false")
    assert values["LOG_LEVEL"] == "INFO"
    assert values["LOG_LINES"] == "1000"
    assert values["OUTPUT_TO_STREAM"] == "false"
    assert values["LOG_DIR"] == str(project_dir / "logs")
    assert values["LOG_FILE"] == str(project_dir / "logs" / "in-reach.log")


def test_verify_project_always_rewrites_root_dir_and_platform(tmp_path: Path) -> None:
    project_dir = tmp_path / ".in-reach"
    project_dir.mkdir()
    env_path = project_dir / ".env"
    env_path.write_text("ROOT_DIR=/somewhere/stale\nIS_WINDOWS=maybe\n")

    verify.verify_project(project_dir)

    values = env_file.get_env_values(env_path)
    assert values["ROOT_DIR"] == str(tmp_path)
    assert values["IS_WINDOWS"] in ("true", "false")


def test_verify_project_preserves_a_users_own_log_settings(tmp_path: Path) -> None:
    project_dir = tmp_path / ".in-reach"
    project_dir.mkdir()
    env_path = project_dir / ".env"
    env_path.write_text("LOG_LEVEL=DEBUG\nLOG_LINES=50\nLOG_DIR=/custom/logs\n")

    verify.verify_project(project_dir)

    values = env_file.get_env_values(env_path)
    assert values["LOG_LEVEL"] == "DEBUG"
    assert values["LOG_LINES"] == "50"
    assert values["LOG_DIR"] == "/custom/logs"
    # LOG_FILE is still derived (blank) -- but from the user's custom LOG_DIR, not the default.
    assert values["LOG_FILE"] == str(Path("/custom/logs") / "in-reach.log")
