from pathlib import Path

from in_reach.app import env_file


def test_get_env_values_returns_empty_dict_for_missing_file(tmp_path: Path) -> None:
    assert env_file.get_env_values(tmp_path / "nope.env") == {}


def test_get_env_values_parses_key_value_pairs(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("FOO=bar\nBAZ=1\n")

    assert env_file.get_env_values(env_path) == {"FOO": "bar", "BAZ": "1"}


def test_get_env_values_strips_quotes_and_whitespace(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text('FOO = "bar"\nBAZ =\'1\'\n')

    assert env_file.get_env_values(env_path) == {"FOO": "bar", "BAZ": "1"}


def test_get_env_values_skips_comments_and_blank_lines(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("# a comment\n\nFOO=bar\n   # indented comment\n")

    assert env_file.get_env_values(env_path) == {"FOO": "bar"}


def test_update_env_value_appends_a_new_key_to_an_empty_file(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"

    env_file.update_env_value(env_path, "FOO", "bar")

    assert env_path.read_text() == "FOO=bar\n"


def test_update_env_value_replaces_an_existing_key_in_place(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("FOO=old\nBAR=untouched\n")

    env_file.update_env_value(env_path, "FOO", "new")

    lines = env_path.read_text().splitlines()
    assert lines == ["FOO=new", "BAR=untouched"]


def test_update_env_value_appends_when_key_is_absent(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("FOO=bar\n")

    env_file.update_env_value(env_path, "NEW", "value")

    lines = env_path.read_text().splitlines()
    assert lines == ["FOO=bar", "NEW=value"]


def test_update_env_value_creates_a_missing_parent_directory(tmp_path: Path) -> None:
    env_path = tmp_path / ".in-reach" / ".env"

    env_file.update_env_value(env_path, "FOO", "bar")

    assert env_path.read_text() == "FOO=bar\n"


def test_update_env_value_only_matches_the_exact_key_prefix(tmp_path: Path) -> None:
    # A naive substring match on "FOO" would also hit "FOOBAR=..." -- make sure it doesn't.
    env_path = tmp_path / ".env"
    env_path.write_text("FOOBAR=untouched\n")

    env_file.update_env_value(env_path, "FOO", "new")

    lines = env_path.read_text().splitlines()
    assert lines == ["FOOBAR=untouched", "FOO=new"]
