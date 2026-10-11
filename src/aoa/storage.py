"""SQLite-backed run history, event journal, and solver-result cache."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def default_data_dir() -> Path:
    configured = os.environ.get("AOA_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if os.name == "nt" and local_app_data:
        return Path(local_app_data) / "AOA"
    home = Path.home()
    if os.access(home, os.W_OK):
        return home / ".aoa"
    return Path.cwd() / ".aoa"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository:
    """Owns application metadata in one local SQLite database."""

    def __init__(self, data_dir: Path | str | None = None) -> None:
        self.data_dir = Path(data_dir) if data_dir is not None else default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.database = self.data_dir / "aoa.db"
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    idempotency_key TEXT UNIQUE
                );
                CREATE TABLE IF NOT EXISTS evaluations (
                    evaluation_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    sequence INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    objective_value REAL,
                    constraint_violations_json TEXT NOT NULL,
                    feasible INTEGER NOT NULL,
                    cache_hit INTEGER NOT NULL DEFAULT 0,
                    duration_seconds REAL NOT NULL,
                    error TEXT,
                    UNIQUE(run_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS idx_evaluations_run ON evaluations(run_id, sequence);
                CREATE TABLE IF NOT EXISTS solver_cache (
                    cache_key TEXT PRIMARY KEY,
                    metrics_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run_events (
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    event_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, event_id)
                );
                CREATE TABLE IF NOT EXISTS imported_datasets (
                    dataset_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    source_format TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    evaluations_json TEXT NOT NULL
                );
                """
            )

    def create_run(self, config: dict[str, Any], idempotency_key: str | None = None) -> tuple[str, bool]:
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        now = utc_now()
        config_json = json.dumps(config, sort_keys=True)
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO runs(run_id, created_at, updated_at, status, config_json, idempotency_key) "
                "VALUES(?, ?, ?, 'queued', ?, ?) "
                "ON CONFLICT(idempotency_key) DO NOTHING",
                (run_id, now, now, config_json, idempotency_key),
            )
            if cursor.rowcount == 1:
                connection.execute(
                    "INSERT INTO run_events(run_id, event_id, event_type, payload_json, created_at) "
                    "VALUES(?, 1, 'run.queued', '{}', ?)",
                    (run_id, now),
                )
            else:
                existing = connection.execute(
                    "SELECT run_id, config_json FROM runs WHERE idempotency_key = ?", (idempotency_key,)
                ).fetchone()
                if existing is None:
                    raise RuntimeError("Run ID collision while creating a run")
                if existing["config_json"] != config_json:
                    raise ValueError("Idempotency-Key was already used for a different workflow")
                return str(existing["run_id"]), False
        return run_id, True

    def update_run(self, run_id: str, status: str, result: dict[str, Any] | None = None, error: str | None = None) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE runs SET status = ?, updated_at = ?, result_json = ?, error = ? WHERE run_id = ?",
                (status, utc_now(), json.dumps(result) if result is not None else None, error, run_id),
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if not row:
                return None
            evaluations = connection.execute(
                "SELECT * FROM evaluations WHERE run_id = ? ORDER BY sequence", (run_id,)
            ).fetchall()
        return {
            "run_id": row["run_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "status": row["status"],
            "workflow": json.loads(row["config_json"]),
            "summary": json.loads(row["result_json"]) if row["result_json"] else None,
            "error": row["error"],
            "evaluations": [self._evaluation_dict(evaluation) for evaluation in evaluations],
        }

    @staticmethod
    def _evaluation_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "evaluation_id": row["evaluation_id"],
            "sequence": row["sequence"],
            "source": row["source"],
            "status": row["status"],
            "parameters": json.loads(row["parameters_json"]),
            "metrics": json.loads(row["metrics_json"]),
            "objective_value": row["objective_value"],
            "constraint_violations": json.loads(row["constraint_violations_json"]),
            "feasible": bool(row["feasible"]),
            "cache_hit": bool(row["cache_hit"]),
            "duration_seconds": row["duration_seconds"],
            "error": row["error"],
        }

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT run_id, created_at, updated_at, status, config_json, result_json, error "
                "FROM runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "run_id": row["run_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "status": row["status"],
                "name": json.loads(row["config_json"]).get("name", "Untitled workflow"),
                "summary": json.loads(row["result_json"]) if row["result_json"] else None,
                "error": row["error"],
            }
            for row in rows
        ]

    def add_evaluation(self, run_id: str, evaluation: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO evaluations(evaluation_id, run_id, sequence, source, status, parameters_json, "
                "metrics_json, objective_value, constraint_violations_json, feasible, cache_hit, duration_seconds, error) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    evaluation["evaluation_id"],
                    run_id,
                    evaluation["sequence"],
                    evaluation["source"],
                    evaluation["status"],
                    json.dumps(evaluation["parameters"], sort_keys=True),
                    json.dumps(evaluation["metrics"], sort_keys=True),
                    evaluation["objective_value"],
                    json.dumps(evaluation["constraint_violations"]),
                    int(evaluation["feasible"]),
                    int(evaluation["cache_hit"]),
                    evaluation["duration_seconds"],
                    evaluation.get("error"),
                ),
            )

    def get_cached_metrics(self, key: str) -> dict[str, float] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT metrics_json FROM solver_cache WHERE cache_key = ?", (key,)).fetchone()
        return json.loads(row["metrics_json"]) if row else None

    def cache_metrics(self, key: str, metrics: dict[str, float]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO solver_cache(cache_key, metrics_json, created_at) VALUES(?, ?, ?)",
                (key, json.dumps(metrics, sort_keys=True), utc_now()),
            )

    def add_event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(event_id), 0) + 1 AS next_id FROM run_events WHERE run_id = ?", (run_id,)
            ).fetchone()
            event_id = int(row["next_id"])
            connection.execute(
                "INSERT INTO run_events(run_id, event_id, event_type, payload_json, created_at) VALUES(?, ?, ?, ?, ?)",
                (run_id, event_id, event_type, json.dumps(payload), utc_now()),
            )
        return event_id

    def get_events(self, run_id: str, after: int = 0) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT event_id, event_type, payload_json, created_at FROM run_events "
                "WHERE run_id = ? AND event_id > ? ORDER BY event_id",
                (run_id, after),
            ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def create_dataset(self, dataset: dict[str, Any]) -> str:
        dataset_id = f"data-{uuid.uuid4().hex[:12]}"
        now = utc_now()
        metadata = {key: value for key, value in dataset.items() if key != "evaluations"}
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO imported_datasets(dataset_id, created_at, filename, source_format, metadata_json, evaluations_json) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (
                    dataset_id,
                    now,
                    dataset["filename"],
                    dataset["source_format"],
                    json.dumps(metadata, sort_keys=True),
                    json.dumps(dataset["evaluations"], sort_keys=True),
                ),
            )
        return dataset_id

    def get_dataset(self, dataset_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM imported_datasets WHERE dataset_id = ?", (dataset_id,)
            ).fetchone()
        if not row:
            return None
        return {
            "dataset_id": row["dataset_id"],
            "created_at": row["created_at"],
            **json.loads(row["metadata_json"]),
            "evaluations": json.loads(row["evaluations_json"]),
        }

    def list_datasets(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT dataset_id, created_at, filename, source_format, metadata_json FROM imported_datasets "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "dataset_id": row["dataset_id"],
                "created_at": row["created_at"],
                "filename": row["filename"],
                "source_format": row["source_format"],
                "row_count": json.loads(row["metadata_json"]).get("row_count", 0),
            }
            for row in rows
        ]
