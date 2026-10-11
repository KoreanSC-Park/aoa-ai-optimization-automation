import pytest

from aoa.doe import generate_design
from aoa.expressions import ExpressionError, evaluate_expression, validate_expression
from aoa.models import DoeConfig, VariableSpec, WorkflowConfig, WorkflowGraph
from aoa.solvers import solve_mock
from aoa.engine import TransientSolverError, solve_with_retry


def variables():
    return [VariableSpec(name="x", lower=-2, upper=2), VariableSpec(name="y", lower=0, upper=4)]


def test_latin_hypercube_is_repeatable_and_stratified():
    config = DoeConfig(method="lhs", samples=12, seed=123)
    first = generate_design(config, variables())
    assert first == generate_design(config, variables())
    assert len(first) == 12
    for variable in variables():
        values = sorted(row[variable.name] for row in first)
        assert all(variable.lower <= value <= variable.upper for value in values)
        width = (variable.upper - variable.lower) / config.samples
        strata = {int((value - variable.lower) / width) for value in values}
        assert strata == set(range(config.samples))


def test_expression_subset_evaluates_numeric_math_only():
    validate_expression("sqrt(x*x) + max(Cd, 1) - 2**2", {"x", "Cd"})
    assert evaluate_expression("sqrt(x*x) + max(Cd, 1) - 2**2", {"x": -3, "Cd": 0.5}) == 0.0
    with pytest.raises(ExpressionError):
        validate_expression("__import__('os').system('whoami')", {"x"})
    with pytest.raises(ExpressionError):
        evaluate_expression("1 / 0", {})


def test_workflow_rejects_duplicate_variables_unknown_names_and_bad_bounds():
    with pytest.raises(ValueError):
        WorkflowConfig.model_validate({"variables": [{"name": "x", "lower": 0, "upper": 1}, {"name": "x", "lower": 0, "upper": 2}]})
    with pytest.raises(ValueError):
        WorkflowConfig.model_validate({"objective": {"expression": "unknown_metric"}})
    with pytest.raises(ValueError):
        VariableSpec(name="alpha", lower=1, upper=1)


@pytest.mark.parametrize("kind", ["rosenbrock", "branin"])
def test_two_variable_benchmarks_reject_one_variable_workflows(kind):
    with pytest.raises(ValueError, match="at least two variables"):
        WorkflowConfig(variables=[VariableSpec(name="x", lower=-1, upper=1)], solver={"kind": kind}, objective={"expression": kind})


def test_graph_rejects_missing_typed_edges_and_cycles():
    graph = WorkflowGraph()
    graph_data = graph.model_dump()
    graph_data["edges"] = graph_data["edges"][:-1]
    with pytest.raises(ValueError, match="missing the required connection"):
        WorkflowGraph.model_validate(graph_data)

    graph_data = graph.model_dump()
    graph_data["edges"][0]["source_handle"] = "wrong_port"
    with pytest.raises(ValueError, match="missing the required connection"):
        WorkflowGraph.model_validate(graph_data)

    graph_data = graph.model_dump()
    graph_data["edges"].append({"source": "results", "target": "variables", "source_handle": "out", "target_handle": "in"})
    with pytest.raises(ValueError, match="cycle"):
        WorkflowGraph.model_validate(graph_data)


def test_branin_mock_has_known_near_optimum():
    value = solve_mock("branin", {"x": 3.141592653589793, "y": 2.275})["branin"]
    assert value == pytest.approx(0.397887, abs=1e-5)


def test_retry_is_bounded_and_only_for_explicit_transient_errors():
    calls = 0

    def eventually_works():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise TransientSolverError("temporary worker start failure")
        return {"ok": 1.0}

    assert solve_with_retry(eventually_works, max_attempts=3) == {"ok": 1.0}
    assert calls == 3
    calls = 0

    def never_works():
        nonlocal calls
        calls += 1
        raise TransientSolverError("still unavailable")

    with pytest.raises(TransientSolverError):
        solve_with_retry(never_works, max_attempts=2)
    assert calls == 2

    calls = 0

    def invalid_result():
        nonlocal calls
        calls += 1
        raise ValueError("numerical issue is not retryable")

    with pytest.raises(ValueError):
        solve_with_retry(invalid_result, max_attempts=3)
    assert calls == 1
