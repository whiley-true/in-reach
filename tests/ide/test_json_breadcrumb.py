from in_reach.ide.json_breadcrumb import json_breadcrumb_path


def test_at_the_very_start_is_the_root_with_no_path() -> None:
    assert json_breadcrumb_path('{"a": 1}', 0) == []


def test_inside_a_top_level_object_reports_its_key() -> None:
    text = '{"meta": {"a": 1}}'
    offset = text.index('"a"')
    assert json_breadcrumb_path(text, offset) == ["meta"]


def test_nested_objects_report_the_full_key_chain() -> None:
    text = '{"meta": {"description": {"english": "hi"}}}'
    offset = text.index('"hi"')
    assert json_breadcrumb_path(text, offset) == ["meta", "description"]


def test_inside_a_bare_scalar_array_element_stops_at_the_array_itself() -> None:
    # A bare scalar (not an object/array of its own) isn't a breadcrumb-worthy level on its own --
    # matches VS Code's own breadcrumb, which only ever shows structural (object/array) levels.
    text = '{"items": [1, 2, 3]}'
    offset = text.index("3")
    assert json_breadcrumb_path(text, offset) == ["items"]


def test_inside_an_object_nested_in_an_array_element() -> None:
    # The vs_sample.png shape: meta.description is an array of objects.
    text = '{"meta": {"description": [{"index": 0, "text": {"english": "hi"}}]}}'
    offset = text.index('"hi"')
    assert json_breadcrumb_path(text, offset) == ["meta", "description", "[0]", "text"]


def test_second_array_element_reports_index_one() -> None:
    text = '{"items": [{"a": 1}, {"b": 2}]}'
    offset = text.index('"b"')
    assert json_breadcrumb_path(text, offset) == ["items", "[1]"]


def test_a_colon_or_comma_inside_a_string_value_is_not_mistaken_for_structure() -> None:
    text = '{"meta": {"note": "a: b, c"}}'
    offset = text.index('"a: b, c"')
    assert json_breadcrumb_path(text, offset) == ["meta"]


def test_an_escaped_quote_inside_a_string_does_not_end_it_early() -> None:
    text = '{"meta": {"note": "say \\"hi\\""}, "after": 1}'
    offset = text.index('"after"')
    assert json_breadcrumb_path(text, offset) == []


def test_closing_a_container_pops_back_to_its_parent() -> None:
    text = '{"a": {"b": 1}, "c": 2}'
    offset = text.index('"c"')
    assert json_breadcrumb_path(text, offset) == []


def test_offset_past_the_end_of_the_text_is_clamped() -> None:
    text = '{"a": {"b": 1}}'
    assert json_breadcrumb_path(text, 10_000) == json_breadcrumb_path(text, len(text))


def test_malformed_json_stops_gracefully_rather_than_raising() -> None:
    text = '{"a": {"b": '  # truncated -- currently being typed
    assert json_breadcrumb_path(text, len(text)) == ["a"]


def test_empty_text_has_no_path() -> None:
    assert json_breadcrumb_path("", 0) == []


def test_a_key_with_no_value_yet_does_not_leak_into_a_sibling_containers_key() -> None:
    # "b" is typed as a key but its value hasn't been written yet -- the comma after it should
    # reset awaiting_value so a later container isn't mistakenly attributed to "b".
    text = '{"a": {"b":'
    offset = len(text)
    assert json_breadcrumb_path(text, offset) == ["a"]
