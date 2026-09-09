import json

from in_reach.ide.json_position import find_value_span


def test_finds_a_top_level_string_field() -> None:
    text = json.dumps({"title": "hello"})

    span = find_value_span(text, ("title",))

    assert text[span[0] : span[1]] == '"hello"'


def test_finds_a_nested_field() -> None:
    text = json.dumps({"meta": {"category": "Test"}})

    span = find_value_span(text, ("meta", "category"))

    assert text[span[0] : span[1]] == '"Test"'


def test_finds_a_value_inside_a_list_by_index() -> None:
    text = json.dumps({"items": [{"name": "a"}, {"name": "b"}]})

    span = find_value_span(text, ("items", 1, "name"))

    assert text[span[0] : span[1]] == '"b"'


def test_finds_the_whole_object_for_an_empty_loc() -> None:
    text = json.dumps({"meta": {"category": "Test"}})

    span = find_value_span(text, ())

    assert text[span[0] : span[1]] == text


def test_returns_none_for_a_missing_key() -> None:
    text = json.dumps({"meta": {"category": "Test"}})

    assert find_value_span(text, ("meta", "nope")) is None


def test_returns_none_for_an_out_of_range_index() -> None:
    text = json.dumps({"items": [1, 2]})

    assert find_value_span(text, ("items", 5)) is None


def test_handles_numbers_and_literals() -> None:
    text = json.dumps({"count": 42, "enabled": True, "missing": None})

    assert text[slice(*find_value_span(text, ("count",)))] == "42"
    assert text[slice(*find_value_span(text, ("enabled",)))] == "true"
    assert text[slice(*find_value_span(text, ("missing",)))] == "null"


def test_handles_escaped_characters_in_keys_and_strings() -> None:
    text = json.dumps({'weird "key"': 'a "quoted" value'})

    span = find_value_span(text, ('weird "key"',))

    assert json.loads(text[span[0] : span[1]]) == 'a "quoted" value'


def test_returns_none_for_unparseable_text() -> None:
    assert find_value_span("{not valid json", ("meta",)) is None
