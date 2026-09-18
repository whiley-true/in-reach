import json

from in_reach.ide.json_position import find_value_span, find_value_spans


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


# -- find_value_spans() -- single-walk batch lookup (editor.py's own protected-field spans,
# recomputed on every keystroke, need to resolve dozens of locs without re-walking the whole
# document once per loc -- see its own docstring) ------------------------------------------------


def test_find_value_spans_matches_find_value_span_for_each_loc() -> None:
    text = json.dumps({"meta": {"category": "Test", "title": "Hi"}, "items": [{"name": "a"}, {"name": "b"}]})
    locs = [("meta", "category"), ("meta", "title"), ("items", 0, "name"), ("items", 1, "name")]

    batch = find_value_spans(text, locs)

    assert batch == [find_value_span(text, loc) for loc in locs]


def test_find_value_spans_returns_none_for_each_missing_loc_without_disturbing_the_others() -> None:
    text = json.dumps({"meta": {"category": "Test"}, "items": [1, 2]})
    locs = [("meta", "category"), ("meta", "nope"), ("items", 5), ("items", 0)]

    batch = find_value_spans(text, locs)

    assert batch[0] is not None and text[slice(*batch[0])] == '"Test"'
    assert batch[1] is None
    assert batch[2] is None
    assert batch[3] is not None and text[slice(*batch[3])] == "1"


def test_find_value_spans_handles_a_repeated_loc() -> None:
    text = json.dumps({"meta": {"category": "Test"}})

    batch = find_value_spans(text, [("meta", "category"), ("meta", "category")])

    assert batch[0] == batch[1] == find_value_span(text, ("meta", "category"))


def test_find_value_spans_of_an_empty_list_is_empty() -> None:
    assert find_value_spans(json.dumps({"a": 1}), []) == []


def test_find_value_spans_returns_none_for_unparseable_text() -> None:
    assert find_value_spans("{not valid json", [("meta",)]) == [None]
