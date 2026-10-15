import json
import math

import pytest
from fastapi.testclient import TestClient

from aoa.api import create_app
from aoa.models import NodePosition, WorkflowConfig
from test_api_runs import wait_for_run


def test_validated_document_round_trips_and_is_preserved_in_run_snapshot(tmp_path):
    workflow = WorkflowConfig().model_dump(mode="json")
    workflow["doe"]["samples"] = 2
    workflow["optimizer"]["trials"] = 0
    for index, node in enumerate(workflow["graph"]["nodes"]):
        node["position"] = {"x": index * 230.5, "y": -75.25}
    with TestClient(create_app(tmp_path)) as client:
        validated = client.post("/api/v1/workflows/validate", json=workflow)
        assert validated.status_code == 200
        saved = validated.json()["workflow"]
        assert saved == workflow
        assert validated.json()["node_count"] == 6
        assert client.post("/api/v1/workflows/validate", json=saved).json()["workflow"] == saved
        created = client.post("/api/v1/runs", json={"workflow": saved})
        assert created.status_code == 202
        run_id = created.json()["run_id"]
        assert wait_for_run(client, run_id)["workflow"] == saved
    with TestClient(create_app(tmp_path)) as client:
        assert client.get(f"/api/v1/runs/{run_id}").json()["workflow"] == saved


def test_old_v1_workflows_without_node_version_or_position_remain_valid(tmp_path):
    workflow = WorkflowConfig().model_dump(mode="json")
    for node in workflow["graph"]["nodes"]:
        node.pop("version")
        node.pop("position")
    with TestClient(create_app(tmp_path)) as client:
        response = client.post("/api/v1/workflows/validate", json=workflow)
        assert response.status_code == 200
        assert all(node["version"] == 1 and node["position"] is None for node in response.json()["workflow"]["graph"]["nodes"])


@pytest.mark.parametrize("bad_part", ["schema", "node_version", "position", "port", "cycle", "missing_node", "missing_edge"])
def test_invalid_documents_are_rejected_before_runs_are_created(tmp_path, bad_part):
    workflow = WorkflowConfig().model_dump(mode="json")
    if bad_part == "schema":
        workflow["schema_version"] = 99
    elif bad_part == "node_version":
        workflow["graph"]["nodes"][0]["version"] = 2
    elif bad_part == "position":
        workflow["graph"]["nodes"][0]["position"] = {"x": "NaN", "y": 1}
    elif bad_part == "port":
        workflow["graph"]["edges"][0]["source_handle"] = "solver_result"
    elif bad_part == "cycle":
        workflow["graph"]["edges"].append({"source": "results", "target": "variables", "source_handle": "out", "target_handle": "in"})
    elif bad_part == "missing_node":
        workflow["graph"]["nodes"].pop()
    else:
        workflow["graph"]["edges"].pop()
    with TestClient(create_app(tmp_path)) as client:
        assert client.post("/api/v1/workflows/validate", json=workflow).status_code == 422
        assert client.post("/api/v1/runs", json={"workflow": workflow}).status_code == 422
        assert client.get("/api/v1/runs").json()["runs"] == []


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_node_positions_must_be_finite(value):
    with pytest.raises(ValueError):
        NodePosition(x=value, y=0)


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_nonfinite_json_returns_validation_error_instead_of_server_error(tmp_path, literal):
    workflow = WorkflowConfig().model_dump(mode="json")
    workflow["graph"]["nodes"][0]["position"] = {"x": "NONFINITE", "y": 0}
    with TestClient(create_app(tmp_path)) as client:
        for path, body in [("/api/v1/workflows/validate", workflow), ("/api/v1/runs", {"workflow": workflow})]:
            content = json.dumps(body).replace('"NONFINITE"', literal)
            response = client.post(path, content=content, headers={"Content-Type": "application/json"})
            assert response.status_code == 422
            assert "finite" in response.json()["detail"][0]["msg"].lower()
        assert client.get("/api/v1/runs").json()["runs"] == []
