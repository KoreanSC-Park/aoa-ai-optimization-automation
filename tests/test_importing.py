from pathlib import Path

from fastapi.testclient import TestClient

from aoa.api import create_app
from aoa.importing import DatasetImportRequest, import_table, parse_numeric_table


def test_openfoam_forcecoeffs_subset_parses_and_reduces_fixture():
    content = Path("examples/openfoam/forceCoeffs.dat").read_text()
    preview = parse_numeric_table(content, "openfoam_dat")
    assert preview["columns"] == ["Time", "Cm", "Cd", "Cl", "Cl_f", "Cl_r"]
    request = DatasetImportRequest(
        filename="forceCoeffs.dat",
        content=content,
        format="openfoam_dat",
        metric_columns=["Cd", "Cl"],
        aggregation="mean",
        objective_expression="Cd",
    )
    dataset = import_table(request)
    assert dataset["row_count"] == 1
    assert dataset["source_row_count"] == 4
    assert dataset["best_metrics"]["Cd"] == 0.38675
    assert dataset["best_metrics"]["Cl"] == 0.499
    assert dataset["best_objective"] == 0.38675


def test_csv_keeps_inputs_and_outputs_separate_and_applies_constraints():
    content = "x,y,Cd,Cl\n-1,0,0.9,0.2\n0,1,0.6,0.8\n1,1,0.5,0.5\n"
    request = DatasetImportRequest(
        filename="results.csv",
        content=content,
        format="csv",
        parameter_columns=["x", "y"],
        metric_columns=["Cd", "Cl"],
        objective_expression="Cd",
        constraints=[{"name": "lift", "expression": "Cl", "relation": ">=", "bound": 0.6}],
    )
    dataset = import_table(request)
    assert dataset["row_count"] == 3
    assert dataset["best_objective"] == 0.6
    assert dataset["best_parameters"] == {"x": 0.0, "y": 1.0}
    assert dataset["best_feasible"] is True
    assert dataset["evaluations"][2]["feasible"] is False


def test_import_api_saves_dataset_and_csv_export(tmp_path):
    content = "# Time    Cm    Cd    Cl\n0 0.1 0.4 0.5\n1 0.2 0.3 0.6\n"
    with TestClient(create_app(tmp_path)) as client:
        preview = client.post("/api/v1/datasets/preview", json={"filename": "forceCoeffs.dat", "content": content})
        assert preview.status_code == 200
        assert preview.json()["format"] == "openfoam_dat"
        imported = client.post(
            "/api/v1/datasets/import",
            json={
                "filename": "forceCoeffs.dat",
                "content": content,
                "metric_columns": ["Cd", "Cl"],
                "aggregation": "last",
                "objective_expression": "Cd",
                "objective_direction": "maximize",
            },
        )
        assert imported.status_code == 200, imported.text
        dataset = imported.json()
        assert dataset["source_row_count"] == 2
        assert dataset["evaluations"][0]["metrics"] == {"Cd": 0.3, "Cl": 0.6}
        restored = client.get(f"/api/v1/datasets/{dataset['dataset_id']}")
        assert restored.status_code == 200
        assert restored.json()["objective_direction"] == "maximize"
        assert client.get(f"/api/v1/datasets/{dataset['dataset_id']}/results.csv").text.startswith("sequence,source,Cd,Cl")


def test_import_rejects_nan_missing_and_unsafe_expression(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        response = client.post(
            "/api/v1/datasets/import",
            json={"filename": "bad.csv", "content": "x,Cd\n1,nan\n", "parameter_columns": ["x"], "metric_columns": ["Cd"], "objective_expression": "Cd"},
        )
        assert response.status_code == 422
        unsafe = client.post(
            "/api/v1/datasets/import",
            json={"filename": "a.csv", "content": "Cd\n1\n", "metric_columns": ["Cd"], "objective_expression": "__import__('os')"},
        )
        assert unsafe.status_code == 422


def test_oversized_csv_field_is_a_bounded_validation_error(tmp_path):
    content = "case,Cd\n" + ("x" * (128 * 1024 + 1)) + ",0.4\n"
    with TestClient(create_app(tmp_path)) as client:
        response = client.post("/api/v1/datasets/preview", json={"filename": "wide.csv", "content": content})
    assert response.status_code == 422
    assert "fields are limited to 131,072 characters" in response.json()["detail"]
