from pathlib import Path

from in_reach.ide import schema_check


def test_a_file_with_no_known_schema_is_never_checked() -> None:
    assert schema_check.validate_before_save(Path("script.txt"), "not json at all") is None
    assert schema_check.validate_before_save(Path("valid_maps.json"), "also not json") is None


def test_settings_json_with_bad_json_syntax_fails() -> None:
    error = schema_check.validate_before_save(Path("settings.json"), "{not valid json")

    assert error is not None
    assert "settings.json" in error


def test_settings_json_that_is_not_an_object_fails() -> None:
    error = schema_check.validate_before_save(Path("settings.json"), "[1, 2, 3]")

    assert error is not None
    assert "must be a JSON object" in error


def test_settings_json_with_an_invalid_enum_value_fails() -> None:
    text = '{"meta": {"category": "not_a_real_category", "source_file": "x.bin", "generated_at": "2026-01-01T00:00:00Z"}}'

    error = schema_check.validate_before_save(Path("settings.json"), text)

    assert error is not None
    assert "settings.json" in error


def test_settings_json_with_a_valid_minimal_document_passes() -> None:
    text = '{"meta": {"source_file": "x.bin", "generated_at": "2026-01-01T00:00:00Z"}}'

    assert schema_check.validate_before_save(Path("settings.json"), text) is None


def test_settings_json_strips_schema_and_comment_keys_before_validating() -> None:
    text = (
        '{"$schema": "schema/settings.schema.json", "_comment": "do not edit", '
        '"meta": {"source_file": "x.bin", "generated_at": "2026-01-01T00:00:00Z"}}'
    )

    assert schema_check.validate_before_save(Path("settings.json"), text) is None


def test_script_settings_json_with_an_invalid_value_fails() -> None:
    text = '{"map_permissions": {"type": "not_a_real_type"}}'

    error = schema_check.validate_before_save(Path("script_settings.json"), text)

    assert error is not None
    assert "script_settings.json" in error


def test_script_settings_json_with_a_valid_document_passes() -> None:
    assert schema_check.validate_before_save(Path("script_settings.json"), "{}") is None


def test_strings_json_with_a_missing_required_field_fails() -> None:
    error = schema_check.validate_before_save(Path("strings.json"), "{}")

    assert error is not None
    assert "strings.json" in error


def test_strings_json_with_a_valid_document_passes() -> None:
    text = '{"meta": {"name": [], "description": [], "category": []}, "teams": [], "script_strings": []}'

    assert schema_check.validate_before_save(Path("strings.json"), text) is None


def test_matches_by_filename_regardless_of_folder() -> None:
    text = '{"meta": {"source_file": "x.bin", "generated_at": "2026-01-01T00:00:00Z"}}'

    assert schema_check.validate_before_save(Path("/some/deep/path/settings.json"), text) is None
