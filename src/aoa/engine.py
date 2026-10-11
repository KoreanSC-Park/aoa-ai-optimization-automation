"""Single-writer run coordinator for deterministic DOE + Optuna TPE workflows."""

from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import optuna
from optuna.trial import TrialState

from aoa.expressions import evaluate_expression
from aoa.models import WorkflowConfig
from aoa.solvers import MOCK_SOLVER_VERSION, solve_mock
from aoa.storage import Repository


class TransientSolverError(RuntimeError):
    """An explicitly retryable solver launch/connection error."""


def solve_with_retry(solver: Callable[[], dict[str, float]], max_attempts: int = 2) -> dict[str, float]:
    """Retry only the narrow transient error type, with a bounded attempt count."""
    attempts = max(1, min(int(max_attempts), 3))
    for attempt in range(attempts):
        try:
            return solver()
        except TransientSolverError:
            if attempt + 1 == attempts:
                raise
    raise AssertionError("unreachable")


def _solver_cache_key(kind: str, parameters: dict[str, float]) -> str:
    payload = json.dumps(
        {"kind": kind, "version": MOCK_SOLVER_VERSION, "parameters": parameters},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _constraint_violations(workflow: WorkflowConfig, values: dict[str, float]) -> list[float]:
    violations = []
    for constraint in workflow.constraints:
        observed = evaluate_expression(constraint.expression, values)
        violation = observed - constraint.bound if constraint.relation == "<=" else constraint.bound - observed
        violations.append(float(violation))
    return violations


def run_workflow(repository: Repository, run_id: str, workflow: WorkflowConfig) -> None:
    """Execute one immutable workflow snapshot, committing each evaluation and event."""
    repository.update_run(run_id, "running")
    repository.add_event(run_id, "run.started", {"name": workflow.name})
    evaluations: list[dict[str, Any]] = []
    sequence = 0

    def evaluate(parameters: dict[str, float], source: str) -> dict[str, Any]:
        nonlocal sequence
        sequence += 1
        evaluation_id = f"eval-{uuid.uuid4().hex[:12]}"
        repository.add_event(
            run_id,
            "evaluation.started",
            {"evaluation_id": evaluation_id, "sequence": sequence, "source": source},
        )
        started = time.perf_counter()
        cache_key = _solver_cache_key(workflow.solver.kind, parameters)
        metrics = repository.get_cached_metrics(cache_key)
        cache_hit = metrics is not None
        if metrics is None:
            metrics = solve_with_retry(
                lambda: solve_mock(workflow.solver.kind, parameters),
                max_attempts=workflow.solver.retry_attempts,
            )
            if any(not math.isfinite(value) for value in metrics.values()):
                raise ValueError("Mock solver returned a non-finite metric")
            repository.cache_metrics(cache_key, metrics)

        values = {**parameters, **metrics}
        objective_value = evaluate_expression(workflow.objective.expression, values)
        violations = _constraint_violations(workflow, values)
        feasible = all(value <= 0 for value in violations)
        evaluation = {
            "evaluation_id": evaluation_id,
            "sequence": sequence,
            "source": source,
            "status": "succeeded",
            "parameters": parameters,
            "metrics": metrics,
            "objective_value": objective_value,
            "constraint_violations": violations,
            "feasible": feasible,
            "cache_hit": cache_hit,
            "duration_seconds": time.perf_counter() - started,
            "error": None,
        }
        repository.add_evaluation(run_id, evaluation)
        repository.add_event(
            run_id,
            "evaluation.completed",
            {
                "evaluation_id": evaluation_id,
                "sequence": sequence,
                "status": "succeeded",
                "objective_value": objective_value,
                "feasible": feasible,
                "cache_hit": cache_hit,
            },
        )
        evaluations.append(evaluation)
        return evaluation

    try:
        from aoa.doe import generate_design

        for parameters in generate_design(workflow.doe, workflow.variables):
            evaluate(parameters, "doe")

        if workflow.optimizer.trials:
            storage_url = f"sqlite:///{Path(repository.database).as_posix()}"
            sampler = optuna.samplers.TPESampler(
                seed=workflow.optimizer.seed,
                constraints_func=lambda trial: trial.user_attrs.get("constraint_violations", ()),
            )
            study = optuna.create_study(
                study_name=f"aoa-{run_id}",
                direction=workflow.objective.direction,
                sampler=sampler,
                storage=storage_url,
                load_if_exists=True,
            )
            for _ in range(workflow.optimizer.trials):
                trial = study.ask()
                parameters = {
                    variable.name: trial.suggest_float(variable.name, variable.lower, variable.upper)
                    for variable in workflow.variables
                }
                try:
                    result = evaluate(parameters, "optimizer")
                    trial.set_user_attr("constraint_violations", result["constraint_violations"])
                    study.tell(trial, result["objective_value"])
                except TransientSolverError as error:
                    study.tell(trial, state=TrialState.FAIL)
                    repository.add_event(run_id, "evaluation.failed", {"sequence": sequence, "error": str(error)})
                except Exception:
                    study.tell(trial, state=TrialState.FAIL)
                    raise

        successful = [evaluation for evaluation in evaluations if evaluation["status"] == "succeeded"]
        feasible_results = [evaluation for evaluation in successful if evaluation["feasible"]]
        pool = feasible_results or successful
        if not pool:
            raise RuntimeError("The run completed without a successful evaluation")
        best = min(pool, key=lambda item: item["objective_value"])
        if workflow.objective.direction == "maximize":
            best = max(pool, key=lambda item: item["objective_value"])
        summary = {
            "evaluation_count": len(evaluations),
            "successful_count": len(successful),
            "failed_count": len(evaluations) - len(successful),
            "feasible_count": len(feasible_results),
            "cache_hit_count": sum(1 for evaluation in evaluations if evaluation["cache_hit"]),
            "best_evaluation_id": best["evaluation_id"],
            "best_parameters": best["parameters"],
            "best_objective": best["objective_value"],
            "best_metrics": best["metrics"],
            "best_feasible": bool(feasible_results),
            "objective_direction": workflow.objective.direction,
        }
        repository.update_run(run_id, "completed", result=summary)
        repository.add_event(run_id, "run.completed", summary)
    except Exception as error:
        repository.update_run(run_id, "failed", error=f"{type(error).__name__}: {error}")
        repository.add_event(run_id, "run.failed", {"error": f"{type(error).__name__}: {error}"})
