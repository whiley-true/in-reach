"""The pure parts of loading a script project: where things are in a TOML file, reading manifests, the constants a
file sees, and putting blocks in order. None of this touches the file system; ``test_script_project_loader.py``
loads whole projects."""
import pytest

from in_reach.app.script_preprocess import Env
from in_reach.app.script_project.constants import base_constants, module_constants, resolve_value
from in_reach.app.script_project.diagnostics import ProjectDiagnostic
from in_reach.app.script_project.manifests import ModuleManifest, ParamSpec, ProjectManifest, read_manifest
from in_reach.app.script_project.ordering import Edge, order_blocks
from in_reach.app.script_project.toml_positions import locate, positions

# -- toml_positions -------------------------------------------------------------------------------------

_SAMPLE = """[project]
name = "x"

[blocks]
order = ["A", "B"]

[[modules]]
name = "one"
params = { a = 1 }

[[modules]]
name = "two"

[pins]
"p_hud" = "player.number[0]"
a.b.c = 1
"""


def test_every_table_and_key_is_found_at_its_line() -> None:
    found = positions(_SAMPLE)

    assert found[("project",)] == (1, 0)
    assert found[("project", "name")] == (2, 0)
    assert found[("blocks", "order")] == (5, 0)


def test_the_entries_of_an_array_of_tables_are_told_apart_by_index() -> None:
    found = positions(_SAMPLE)

    assert found[("modules", 0, "name")] == (8, 0)
    assert found[("modules", 1, "name")] == (12, 0)


def test_quoted_and_dotted_keys_are_found() -> None:
    found = positions(_SAMPLE)

    assert found[("pins", "p_hud")] == (15, 0)
    assert found[("pins", "a", "b", "c")] == (16, 0)


def test_a_key_inside_an_inline_table_is_found_at_the_line_of_the_table() -> None:
    assert locate(positions(_SAMPLE), ("modules", 0, "params", "a")) == (9, 0)


def test_an_unknown_path_falls_back_to_its_nearest_known_prefix_and_then_to_the_file() -> None:
    found = positions(_SAMPLE)

    assert locate(found, ("blocks", "nonesuch")) == (4, 0)
    assert locate(found, ("nonesuch",)) == (0, 0)
    assert locate(found, ()) == (0, 0)


def test_indentation_is_the_column() -> None:
    assert positions("[t]\n   key = 1\n")[("t", "key")] == (2, 3)


# -- manifests ------------------------------------------------------------------------------------------


def test_a_complete_project_manifest_is_read() -> None:
    text = """[project]
name = "hill_rush"
env = "dev"

[constants]
SCORE = 5

[blocks]
order = ["SETUP", "WIN"]

[[modules]]
name = "hill_score"
params = { score_interval = 2 }

[kinds.hill]
reached_by = ["label:hill"]
"""
    manifest, problems = read_manifest(text, ProjectManifest, "project.toml")

    assert problems == []
    assert manifest.project.name == "hill_rush" and manifest.project.dialect == "mgl/1"
    assert manifest.blocks.order == ["SETUP", "WIN"]
    assert manifest.modules[0].params == {"score_interval": 2}
    assert manifest.kinds["hill"].reached_by == ["label:hill"]


def test_an_empty_project_manifest_is_fine() -> None:
    manifest, problems = read_manifest("", ProjectManifest, "project.toml")

    assert problems == [] and manifest.modules == [] and manifest.blocks.order == []


def test_a_module_manifest_needs_a_name() -> None:
    manifest, problems = read_manifest("[order]\nafter = []\n", ModuleManifest, "modules/x/module.toml")

    assert manifest is None
    assert [(p.code, p.message) for p in problems] == [("manifest-missing-key", "module: is required")]


def test_a_toml_syntax_error_is_located() -> None:
    manifest, problems = read_manifest("[project]\nname = \n", ProjectManifest, "project.toml")

    assert manifest is None
    assert problems[0].code == "toml-syntax" and problems[0].severity == "error"
    assert problems[0].line == 2 and "(at line" not in problems[0].message


def test_a_wrong_value_is_reported_at_its_line() -> None:
    manifest, problems = read_manifest('[project]\nname = 5\ndialect = "mgl/2"\n', ProjectManifest, "project.toml")

    assert manifest is None
    assert [(p.line, p.code) for p in problems] == [(2, "manifest-invalid-value"), (3, "manifest-invalid-value")]
    assert "project.name" in problems[0].message


def test_a_missing_required_key_is_reported_at_its_table() -> None:
    _, problems = read_manifest("[[modules]]\nparams = {}\n", ProjectManifest, "project.toml")

    assert [(p.code, p.line, p.message) for p in problems] == [("manifest-missing-key", 1, "modules.0.name: is required")]


def test_unknown_keys_are_warnings_and_the_manifest_still_loads() -> None:
    text = '[project]\nname = "x"\nnope = 1\n\n[[modules]]\nname = "m"\ncolor = "red"\n\n[strange]\na = 1\n'

    manifest, problems = read_manifest(text, ProjectManifest, "project.toml")

    assert manifest is not None
    assert [(p.severity, p.line) for p in problems] == [("warning", 3), ("warning", 7), ("warning", 9)]
    assert "unknown key 'nope' in [project]" in problems[0].message


@pytest.mark.parametrize("table", ["requires", "provides"])
def test_the_dropped_module_tables_get_an_explanation_not_just_an_unknown_key(table: str) -> None:
    text = f'[module]\nname = "x"\n\n[{table}]\nplayer_timer = 1\n'

    manifest, problems = read_manifest(text, ModuleManifest, "modules/x/module.toml")

    assert manifest is not None
    assert [(p.code, p.line) for p in problems] == [("manifest-dropped-table", 4)]
    assert "inferred from its `@` annotations" in problems[0].message


def test_module_params_kinds_and_shared_items_are_read() -> None:
    text = """[module]
name = "hill_score"
version = "1.0.0"
tags = ["hill"]

[order]
after = ["SETUP"]
phase = "live"

[params]
interval = { type = "number", default = 2, doc = "seconds" }
label = { type = "string" }

[shared]
traits = ["t_freeze"]

[kinds]
hill = { reached_by = ["label:hill"] }
"""
    manifest, problems = read_manifest(text, ModuleManifest, "m.toml")

    assert problems == []
    assert manifest.order.after == ["SETUP"] and manifest.order.phase == "live"
    assert manifest.params["interval"] == ParamSpec(type="number", default=2, doc="seconds")
    assert manifest.params["label"].default is None
    assert manifest.shared.traits == ["t_freeze"]
    assert manifest.kinds["hill"].reached_by == ["label:hill"]


def test_a_diagnostic_prints_like_a_compiler_message() -> None:
    diagnostic = ProjectDiagnostic(severity="error", code="x", message="bad", file="a/b.toml", line=3)

    assert str(diagnostic) == "a/b.toml:3: error: bad [x]"
    assert str(ProjectDiagnostic(severity="warning", code="y", message="hm", file="a.toml")) == "a.toml: warning: hm [y]"


# -- constants ------------------------------------------------------------------------------------------

_DEV = Env("dev", frozenset({"DEV"}), {"PHASE_TIMER": "2"})


def test_project_constants_are_defaults_and_the_profile_overrides_them() -> None:
    constants, problems = base_constants({"PHASE_TIMER": 6, "SCORE": 50}, _DEV)

    assert problems == []
    assert constants == {"PHASE_TIMER": "2", "SCORE": "50"}


def test_without_a_profile_the_project_constants_stand() -> None:
    assert base_constants({"PHASE_TIMER": 6}, None) == ({"PHASE_TIMER": "6"}, [])


def test_a_constant_defined_in_terms_of_another_follows_its_final_value() -> None:
    """So an env that changes PHASE_TIMER changes everything defined from it."""
    constants, _ = base_constants({"PHASE_TIMER": 6, "ROUND": "${PHASE_TIMER}"}, _DEV)

    assert constants["ROUND"] == "2"
    assert base_constants({"PHASE_TIMER": 6, "ROUND": "${PHASE_TIMER}"}, None)[0]["ROUND"] == "6"


def test_a_constant_may_be_a_percentage_a_name_or_a_string() -> None:
    constants, problems = base_constants({"RATE": "-100%", "LABEL": '"hill"', "WHO": "current_player"}, None)

    assert problems == [] and constants == {"RATE": "-100%", "LABEL": '"hill"', "WHO": "current_player"}


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("nope nope", "constant-value"),
        (40000, "constant-value"),
        ("${GHOST}", "constant-undefined"),
    ],
)
def test_an_unusable_constant_is_reported_and_left_out(value, code: str) -> None:
    constants, problems = base_constants({"BAD": value, "GOOD": 1}, None)

    assert [(p.name, p.code, p.source) for p in problems] == [("BAD", code, "project")]
    assert constants == {"GOOD": "1"}


def test_constants_defined_in_a_circle_are_reported() -> None:
    _, problems = base_constants({"A": "${B}", "B": "${A}"}, None)

    assert sorted((p.name, p.code) for p in problems) == [("A", "constant-cycle"), ("B", "constant-cycle")]


def test_a_bad_default_the_profile_overrides_is_not_a_problem() -> None:
    constants, problems = base_constants({"X": "nope nope"}, Env("p", frozenset(), {"X": "5"}))

    assert problems == [] and constants == {"X": "5"}


def test_an_invalid_constant_name_is_reported() -> None:
    _, problems = base_constants({"9lives": 1}, None)

    assert [p.code for p in problems] == ["constant-name"]


def test_resolve_value_looks_up_a_whole_placeholder() -> None:
    assert resolve_value("${A}", {"A": "7"}) == "7"
    assert resolve_value(3, {}) == "3"
    assert resolve_value("plain", {}) == "plain"
    with pytest.raises(KeyError):
        resolve_value("${A}", {})


_BASE = {"SCORE_INTERVAL": "1"}


def test_a_parameter_takes_the_importers_value_else_its_default() -> None:
    specs = {"interval": ParamSpec(default="${SCORE_INTERVAL}"), "goal": ParamSpec(default=10)}

    constants, problems = module_constants(_BASE, specs, {"goal": 25})

    assert problems == []
    assert constants == {"SCORE_INTERVAL": "1", "interval": "1", "goal": "25"}


def test_a_parameter_shadows_a_project_constant_of_the_same_name() -> None:
    constants, _ = module_constants({"goal": "1"}, {"goal": ParamSpec(default=9)}, {})

    assert constants["goal"] == "9"


@pytest.mark.parametrize(
    ("specs", "given", "code", "source"),
    [
        ({}, {"ghost": 1}, "param-unknown", "importer"),
        ({"need": ParamSpec()}, {}, "param-missing", "importer"),
        ({"n": ParamSpec(type="number", default="hello")}, {}, "param-type", "default"),
        ({"n": ParamSpec(type="number")}, {"n": "hello"}, "param-type", "importer"),
        ({"n": ParamSpec(type="string", default=5)}, {}, "param-type", "default"),
        ({"n": ParamSpec(type="number", default="${GHOST}")}, {}, "param-undefined", "default"),
        ({"n": ParamSpec(type="number", default=99999)}, {}, "param-value", "default"),
        ({"9n": ParamSpec(default=1)}, {}, "param-name", "default"),
    ],
)
def test_parameter_problems_say_whose_value_it_was(specs, given, code: str, source: str) -> None:
    _, problems = module_constants(_BASE, specs, given)

    assert [(p.code, p.source) for p in problems] == [(code, source)]


def test_every_parameter_type_accepts_its_kind_of_value() -> None:
    specs = {
        "n": ParamSpec(type="number", default=-5),
        "p": ParamSpec(type="percent", default="-100%"),
        "w": ParamSpec(type="name", default="current_player"),
        "s": ParamSpec(type="string", default='"hill"'),
    }

    constants, problems = module_constants({}, specs, {})

    assert problems == [] and constants == {"n": "-5", "p": "-100%", "w": "current_player", "s": '"hill"'}


def test_a_bad_parameter_is_left_out_and_the_rest_are_kept() -> None:
    constants, problems = module_constants({}, {"bad": ParamSpec(default="x y"), "good": ParamSpec(default=1)}, {})

    assert "bad" not in constants and constants["good"] == "1" and len(problems) == 1


# -- ordering -------------------------------------------------------------------------------------------


def _edge(before: str, after: str, source: str = "test") -> Edge:
    return Edge(before, after, source)


def test_a_listed_chain_is_kept() -> None:
    blocks = ["SETUP", "HILL_PASS", "WIN_CHECK"]

    order, cycle = order_blocks(blocks, blocks, [_edge("SETUP", "HILL_PASS"), _edge("HILL_PASS", "WIN_CHECK")])

    assert (order, cycle) == (blocks, None)


def test_edges_place_blocks_the_list_does_not() -> None:
    order, cycle = order_blocks(["A", "B", "C"], [], [_edge("C", "A"), _edge("A", "B")])

    assert (order, cycle) == (["C", "A", "B"], None)


def test_unconstrained_blocks_fall_back_to_the_list_then_first_seen_order() -> None:
    order, _ = order_blocks(["X", "Y", "A", "B"], ["B", "A"], [])

    assert order == ["B", "A", "X", "Y"]


def test_a_module_can_pull_a_block_ahead_of_where_the_list_would_put_it() -> None:
    order, _ = order_blocks(["A", "B", "C"], ["A", "B", "C"], [_edge("C", "A")])

    assert order.index("C") < order.index("A")


def test_the_same_input_always_gives_the_same_order() -> None:
    blocks = ["D", "C", "B", "A"]

    assert {tuple(order_blocks(blocks, [], [])[0]) for _ in range(5)} == {("D", "C", "B", "A")}


def test_a_cycle_is_reported_with_the_edges_that_form_it() -> None:
    edges = [_edge("A", "B", "x"), _edge("B", "C", "y"), _edge("C", "A", "z")]

    order, cycle = order_blocks(["A", "B", "C", "D"], ["D"], edges)

    assert cycle is not None and {(e.before, e.after, e.source) for e in cycle} == {("A", "B", "x"), ("B", "C", "y"), ("C", "A", "z")}
    assert order[0] == "D" and sorted(order) == ["A", "B", "C", "D"]  # a best-effort order is still returned


def test_a_block_that_must_come_before_itself_is_a_cycle() -> None:
    _, cycle = order_blocks(["A"], [], [_edge("A", "A", "self")])

    assert [(e.before, e.after) for e in cycle] == [("A", "A")]


def test_a_cycle_reports_only_the_circle_not_the_blocks_waiting_on_it() -> None:
    edges = [_edge("A", "B"), _edge("B", "A"), _edge("B", "C")]

    _, cycle = order_blocks(["A", "B", "C"], [], edges)

    assert {e.before for e in cycle} == {"A", "B"}


def test_a_cycle_is_found_even_when_the_lowest_ranked_stuck_block_is_only_downstream_of_it() -> None:
    """Blocks waiting on a cycle are stuck too. Starting the search at one of them (here Z, ranked first) used to
    crash, because Z has nowhere to go; a mistaken ``before = ["SETUP"]`` in a module produces exactly this."""
    edges = [_edge("A", "B", "x"), _edge("B", "A", "y"), _edge("A", "Z", "z")]

    order, cycle = order_blocks(["Z", "A", "B"], ["Z"], edges)

    assert {e.before for e in cycle} == {"A", "B"}
    assert sorted(order) == ["A", "B", "Z"]


def test_a_cycle_with_several_blocks_hanging_off_it_is_still_found() -> None:
    edges = [_edge("A", "B"), _edge("B", "A"), _edge("B", "X"), _edge("X", "Y"), _edge("Y", "Z")]

    _, cycle = order_blocks(["Z", "Y", "X", "A", "B"], ["Z", "Y", "X"], edges)

    assert {e.before for e in cycle} == {"A", "B"}
