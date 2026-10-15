"""Local-only REST API for workflow validation and mock optimization runs."""

from __future__ import annotations

import csv
import io
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from aoa.engine import run_workflow
from aoa.importing import DatasetImportRequest, DatasetPreviewRequest, import_table, preview_table
from aoa.models import RunRequest, WorkflowConfig
from aoa.storage import Repository


def create_app(data_dir: Path | str | None = None) -> FastAPI:
    repository = Repository(data_dir)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="aoa-run")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        executor.shutdown(wait=True, cancel_futures=False)

    app = FastAPI(
        title="AOA Local Optimization API",
        version="0.1.0",
        description="Loopback-only API for local DOE and mock optimization workflows.",
        lifespan=lifespan,
    )
    app.state.repository = repository
    app.state.executor = executor

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, error: RequestValidationError) -> JSONResponse:
        # Nonfinite request values cannot be echoed in a JSON error response.
        details = [{key: item[key] for key in ("type", "loc", "msg")} for item in error.errors()]
        return JSONResponse(status_code=422, content={"detail": details})

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Idempotency-Key"],
    )

    @app.get("/api/v1/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "aoa-local-api",
            "available_solvers": ["sphere", "rosenbrock", "branin"],
            "available_optimizers": ["optuna_tpe"],
            "fluent": {"available": False, "reason": "Configure and validate a supported Fluent/PyFluent version pair and a valid commercial solver license before enabling live CFD."},
        }

    @app.get("/api/v1/system/solvers")
    def solvers() -> dict[str, Any]:
        return {
            "available": [
                {"id": "sphere", "label": "Sphere (mock)", "license_required": False},
                {"id": "rosenbrock", "label": "Rosenbrock (mock)", "license_required": False},
                {"id": "branin", "label": "Branin (mock)", "license_required": False},
            ],
            "deferred": [
                {"id": "fluent", "label": "ANSYS Fluent / PyFluent", "reason": "Requires a locally verified Fluent/PyFluent version pair and a valid commercial solver license."}
            ],
        }

    @app.post("/api/v1/datasets/preview")
    def preview_dataset(request: DatasetPreviewRequest) -> dict[str, Any]:
        try:
            return preview_table(request.filename, request.content, request.format)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/v1/datasets/import")
    def import_dataset(request: DatasetImportRequest) -> dict[str, Any]:
        try:
            dataset = import_table(request.model_copy(deep=True))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        dataset_id = repository.create_dataset(dataset)
        return {"dataset_id": dataset_id, **dataset}

    @app.get("/api/v1/datasets")
    def list_datasets(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
        return {"datasets": repository.list_datasets(limit)}

    @app.get("/api/v1/datasets/{dataset_id}")
    def get_dataset(dataset_id: str) -> dict[str, Any]:
        dataset = repository.get_dataset(dataset_id)
        if dataset is None:
            raise HTTPException(status_code=404, detail="Dataset not found")
        return dataset

    @app.get("/api/v1/datasets/{dataset_id}/results.csv")
    def export_dataset(dataset_id: str) -> Response:
        dataset = repository.get_dataset(dataset_id)
        if dataset is None:
            raise HTTPException(status_code=404, detail="Dataset not found")
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        parameter_names = dataset["parameter_columns"]
        metric_names = dataset["metric_columns"]
        writer.writerow(["sequence", "source", *parameter_names, *metric_names, "objective", "feasible", "constraint_violations"])
        for evaluation in dataset["evaluations"]:
            writer.writerow(
                [
                    evaluation["sequence"],
                    "imported",
                    *(evaluation["parameters"].get(name, "") for name in parameter_names),
                    *(evaluation["metrics"].get(name, "") for name in metric_names),
                    evaluation["objective_value"],
                    evaluation["feasible"],
                    ";".join(str(value) for value in evaluation["constraint_violations"]),
                ]
            )
        return Response(
            content=output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="aoa-{dataset_id}.csv"'},
        )

    @app.post("/api/v1/workflows/validate")
    def validate_workflow(workflow: WorkflowConfig) -> dict[str, Any]:
        return {
            "valid": True,
            "schema_version": workflow.schema_version,
            "node_count": len(workflow.graph.nodes),
            "workflow": workflow.model_dump(mode="json"),
        }

    @app.post("/api/v1/runs", status_code=status.HTTP_202_ACCEPTED)
    def create_run(
        request: RunRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=200),
    ) -> dict[str, Any]:
        config = request.workflow.model_dump(mode="json")
        try:
            run_id, created = repository.create_run(config, idempotency_key)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        run = repository.get_run(run_id)
        if created:
            try:
                executor.submit(run_workflow, repository, run_id, request.workflow)
            except RuntimeError as error:
                repository.update_run(run_id, "failed", error="Run queue is unavailable")
                raise HTTPException(status_code=503, detail="Run queue is unavailable") from error
        return {
            "run_id": run_id,
            "status": run["status"] if run else "queued",
            "created": created,
            "status_url": f"/api/v1/runs/{run_id}",
            "events_url": f"/api/v1/runs/{run_id}/events",
        }

    @app.get("/api/v1/runs")
    def list_runs(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
        return {"runs": repository.list_runs(limit)}

    @app.get("/api/v1/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        run = repository.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

    @app.get("/api/v1/runs/{run_id}/events")
    def get_run_events(run_id: str, after: int = Query(default=0, ge=0)) -> dict[str, Any]:
        if repository.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return {"events": repository.get_events(run_id, after)}

    @app.get("/api/v1/runs/{run_id}/results.csv")
    def export_results(run_id: str) -> Response:
        run = repository.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        if not run["evaluations"]:
            raise HTTPException(status_code=409, detail="Run has no evaluations yet")
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        parameter_names = [variable["name"] for variable in run["workflow"]["variables"]]
        metric_names = sorted({name for evaluation in run["evaluations"] for name in evaluation["metrics"]})
        writer.writerow(["sequence", "source", *parameter_names, "objective", "feasible", "cache_hit", *metric_names])
        for evaluation in run["evaluations"]:
            writer.writerow(
                [
                    evaluation["sequence"],
                    evaluation["source"],
                    *(evaluation["parameters"].get(name, "") for name in parameter_names),
                    evaluation["objective_value"],
                    evaluation["feasible"],
                    evaluation["cache_hit"],
                    *(evaluation["metrics"].get(name, "") for name in metric_names),
                ]
            )
        return Response(
            content=output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="aoa-{run_id}.csv"'},
        )

    return app


app = create_app()
