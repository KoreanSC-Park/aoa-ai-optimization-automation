import time
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from aoa.api import create_app
from aoa.models import WorkflowGraph
from aoa.storage import Repository


def payload(samples=4, trials=5, constraints=None):
    return {
        "workflow": {
            "name": "API smoke",
            "variables": [{"name": "x", "lower": -5, "upper": 5}, {"name": "y", "lower": -5, "upper": 5}],
            "doe": {"method": "lhs", "samples": samples, "seed": 42},
            "solver": {"kind": "sphere"},
            "objective": {"name": "objective", "expression": "sphere", "direction": "minimize"},
            "constraints": constraints or [],
            "optimizer": {"engine": "optuna_tpe", "trials": trials, "seed": 43},
        }
    }


def wait_for_run(client, run_id, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = client.get(f"/api/v1/runs/{run_id}").json()
        if result["status"] in {"completed", "failed"}:
            return result
        time.sleep(0.02)
    raise AssertionError("Run did not finish within the test timeout")


def test_mock_run_persists_results_events_and_csv(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/v1/health").json()["status"] == "ok"
        response = client.post("/api/v1/runs", json=payload(), headers={"Idempotency-Key": "test-run-1"})
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        run = wait_for_run(client, run_id)
        assert run["status"] == "completed", run.get("error")
        assert run["summary"]["evaluation_count"] == 9
        assert len(run["evaluations"]) == 9
        assert run["summary"]["best_objective"] >= 0
        events = client.get(f"/api/v1/runs/{run_id}/events").json()["events"]
        assert events[0]["type"] == "run.queued"
        assert events[-1]["type"] == "run.completed"
        assert client.get(f"/api/v1/runs/{run_id}/results.csv").text.startswith("sequence,source,x,y,objective")
        retry = client.post("/api/v1/runs", json=payload(), headers={"Idempotency-Key": "test-run-1"})
        assert retry.json()["run_id"] == run_id
        assert retry.json()["created"] is False


def test_solver_cache_reuses_raw_outputs_across_runs(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        first = client.post("/api/v1/runs", json=payload(samples=5, trials=0)).json()
        first_run = wait_for_run(client, first["run_id"])
        assert first_run["status"] == "completed"
        second = client.post("/api/v1/runs", json=payload(samples=5, trials=0)).json()
        second_run = wait_for_run(client, second["run_id"])
        assert second_run["status"] == "completed"
        assert all(evaluation["cache_hit"] for evaluation in second_run["evaluations"])
        assert second_run["summary"]["cache_hit_count"] == 5


def test_objective_change_reuses_solver_results_but_solver_change_invalidates_cache(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        first_payload = payload(samples=4, trials=0)
        first = client.post("/api/v1/runs", json=first_payload).json()
        first_run = wait_for_run(client, first["run_id"])

        changed_objective = payload(samples=4, trials=0)
        changed_objective["workflow"]["objective"]["expression"] = "sphere + 1"
        second = client.post("/api/v1/runs", json=changed_objective).json()
        second_run = wait_for_run(client, second["run_id"])
        assert all(evaluation["cache_hit"] for evaluation in second_run["evaluations"])
        assert second_run["summary"]["best_objective"] == first_run["summary"]["best_objective"] + 1

        different_solver = payload(samples=4, trials=0)
        different_solver["workflow"]["solver"]["kind"] = "rosenbrock"
        different_solver["workflow"]["objective"]["expression"] = "rosenbrock"
        third = client.post("/api/v1/runs", json=different_solver).json()
        third_run = wait_for_run(client, third["run_id"])
        assert not any(evaluation["cache_hit"] for evaluation in third_run["evaluations"])


def test_invalid_workflow_is_rejected_without_starting_a_run(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        bad = payload()
        bad["workflow"]["objective"]["expression"] = "__import__('os')"
        response = client.post("/api/v1/runs", json=bad)
        assert response.status_code == 422
        assert client.get("/api/v1/runs").json()["runs"] == []


def test_invalid_graph_is_rejected_and_does_not_run(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        bad = payload()
        bad["workflow"]["graph"] = WorkflowGraph().model_dump()
        bad["workflow"]["graph"]["edges"].pop()
        response = client.post("/api/v1/runs", json=bad)
        assert response.status_code == 422
        assert client.get("/api/v1/runs").json()["runs"] == []


def test_idempotency_key_conflicts_if_configuration_changes(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        first = client.post("/api/v1/runs", json=payload(samples=2, trials=0), headers={"Idempotency-Key": "same-key"})
        assert first.status_code == 202
        wait_for_run(client, first.json()["run_id"])
        changed = payload(samples=3, trials=0)
        conflict = client.post("/api/v1/runs", json=changed, headers={"Idempotency-Key": "same-key"})
        assert conflict.status_code == 409


def test_concurrent_idempotent_create_inserts_only_one_run(tmp_path):
    repository = Repository(tmp_path)
    config = payload(samples=2, trials=0)["workflow"]
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: repository.create_run(config, "parallel-key"), range(24)))
    assert len({run_id for run_id, _ in results}) == 1
    assert sum(created for _, created in results) == 1


def test_concurrent_different_payloads_share_one_key_and_conflict(tmp_path):
    repository = Repository(tmp_path)
    configs = [payload(samples=2 + index, trials=0)["workflow"] for index in range(12)]

    def create(config):
        try:
            return repository.create_run(config, "racing-key")
        except ValueError:
            return "conflict", False

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(create, configs))
    assert sum(created for _, created in results) == 1
    assert sum(run_id == "conflict" for run_id, _ in results) == len(configs) - 1


def test_completed_runs_are_available_after_api_restart(tmp_path):
    with TestClient(create_app(tmp_path)) as first_client:
        created = first_client.post("/api/v1/runs", json=payload(samples=3, trials=0)).json()
        run = wait_for_run(first_client, created["run_id"])
        assert run["status"] == "completed"
    with TestClient(create_app(tmp_path)) as restarted_client:
        restored = restarted_client.get(f"/api/v1/runs/{created['run_id']}").json()
        assert restored["status"] == "completed"
        assert len(restored["evaluations"]) == 3


def test_live_fluent_is_explicitly_not_configured(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        health = client.get("/api/v1/health").json()
        assert health["fluent"]["available"] is False
        assert "license" in health["fluent"]["reason"].lower()
