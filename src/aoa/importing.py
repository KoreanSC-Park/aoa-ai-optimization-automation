"""Solver-neutral import for numeric CSV datasets and a narrow OpenFOAM .dat subset."""

from __future__ import annotations

import csv
import io
import math
import re
import statistics
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aoa.expressions import evaluate_expression, validate_expression
from aoa.models import ConstraintConfig

MAX_IMPORT_CHARS = 2_000_000
MAX_IMPORT_ROWS = 100_000
MAX_CSV_FIELD_CHARS = 128 * 1024
ImportFormat = Literal["csv", "openfoam_dat"]
Aggregation = Literal["all", "last", "mean"]


class DatasetPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=255)
    content: str = Field(max_length=MAX_IMPORT_CHARS)
    format: ImportFormat | None = None

    @field_validator("content")
    @classmethod
    def nonempty_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("The selected file is empty")
        return value


class DatasetImportRequest(DatasetPreviewRequest):
    parameter_columns: list[str] = Field(default_factory=list, max_length=32)
    metric_columns: list[str] = Field(min_length=1, max_length=32)
    aggregation: Aggregation = "all"
    objective_expression: str = Field(min_length=1, max_length=200)
    objective_direction: Literal["minimize", "maximize"] = "minimize"
    constraints: list[ConstraintConfig] = Field(default_factory=list, max_length=8)


def detect_format(filename: str, requested: ImportFormat | None = None) -> ImportFormat:
    if requested:
        return requested
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    return "openfoam_dat" if suffix == "dat" else "csv"


def _safe_header(header: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", header.strip()).strip("_")
    if not safe:
        raise ValueError("Column names must contain at least one letter or number")
    if safe[0].isdigit():
        safe = f"c_{safe}"
    return safe


def _validate_headers(raw_headers: list[str]) -> tuple[list[str], dict[str, str]]:
    headers = [_safe_header(header) for header in raw_headers]
    if not headers or len(headers) > 128:
        raise ValueError("The file must have between 1 and 128 columns")
    if len(set(headers)) != len(headers):
        raise ValueError("Column names become ambiguous after normalization; rename duplicate columns")
    return headers, dict(zip(headers, raw_headers, strict=True))


def parse_numeric_table(content: str, file_format: ImportFormat) -> dict[str, Any]:
    """Parse CSV or OpenFOAM's whitespace/tabular .dat output with a header row.

    The OpenFOAM subset expects a `# Time ...` header followed by rows containing
    one finite numeric value per header. This covers common forceCoeffs tables;
    it intentionally does not parse OpenFOAM field, vector, or VTK formats.
    """
    if len(content) > MAX_IMPORT_CHARS:
        raise ValueError(f"Files are limited to {MAX_IMPORT_CHARS // 1_000_000} MB of text")
    if file_format == "csv":
        reader = csv.reader(io.StringIO(content.lstrip("\ufeff")))
        try:
            raw_headers = next(reader)
        except StopIteration as error:
            raise ValueError("CSV file is empty") from error
        except csv.Error as error:
            raise ValueError(f"CSV fields are limited to {MAX_CSV_FIELD_CHARS:,} characters") from error
        if len(raw_headers) > 128 or not raw_headers:
            raise ValueError("The file must have between 1 and 128 columns")
        if any(not header.strip() for header in raw_headers):
            raise ValueError("CSV column headers cannot be blank")
        headers, raw_to_safe = _validate_headers([header.strip() for header in raw_headers])
        records: list[dict[str, Any]] = []
        try:
            for row_number, row in enumerate(reader, start=2):
                if not row or all(not cell.strip() for cell in row):
                    continue
                if len(row) != len(headers):
                    raise ValueError(f"Row {row_number} has {len(row)} cells; expected {len(headers)}")
                if len(records) >= MAX_IMPORT_ROWS:
                    raise ValueError(f"Import is limited to {MAX_IMPORT_ROWS:,} data rows")
                records.append({column: cell.strip() for column, cell in zip(headers, row, strict=True)})
        except csv.Error as error:
            raise ValueError(f"CSV fields are limited to {MAX_CSV_FIELD_CHARS:,} characters") from error
    else:
        raw_headers = []
        data_rows: list[list[float]] = []
        for line_number, raw_line in enumerate(content.lstrip("\ufeff").splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#"):
                candidate = line.lstrip("# ").strip()
                candidate_columns = re.split(r"[\t, ]+", candidate)
                if candidate_columns and candidate_columns[0].lower() == "time" and len(candidate_columns) >= 2:
                    raw_headers = candidate_columns
                continue
            # Non-comment text before a recognizable header is not part of this supported subset.
            if not raw_headers:
                continue
            cells = re.split(r"[\t, ]+", line)
            if len(cells) != len(raw_headers):
                raise ValueError(f"OpenFOAM .dat row {line_number} has {len(cells)} values; expected {len(raw_headers)}")
            try:
                numbers = [float(cell) for cell in cells]
            except ValueError as error:
                raise ValueError(f"OpenFOAM .dat row {line_number} contains a non-numeric value") from error
            if any(not math.isfinite(number) for number in numbers):
                raise ValueError(f"OpenFOAM .dat row {line_number} contains a missing or non-finite value")
            data_rows.append(numbers)
            if len(data_rows) > MAX_IMPORT_ROWS:
                raise ValueError(f"Import is limited to {MAX_IMPORT_ROWS:,} data rows")
        if not raw_headers:
            raise ValueError("OpenFOAM .dat import expects a comment header beginning `# Time` and numeric rows")
        headers, raw_to_safe = _validate_headers(raw_headers)
        records = [dict(zip(headers, row, strict=True)) for row in data_rows]

    if not records:
        raise ValueError("The selected file has no numeric data rows")
    return {
        "format": file_format,
        "columns": headers,
        "labels": raw_to_safe,
        "rows": records,
    }


def preview_table(filename: str, content: str, requested_format: ImportFormat | None = None) -> dict[str, Any]:
    file_format = detect_format(filename, requested_format)
    table = parse_numeric_table(content, file_format)
    numeric_candidates = []
    for column in table["columns"]:
        try:
            numbers = [float(row[column]) for row in table["rows"]]
        except (TypeError, ValueError):
            continue
        if all(math.isfinite(number) for number in numbers):
            numeric_candidates.append(column)
    metric_candidates = [column for column in numeric_candidates if column.lower() not in {"time", "iteration", "step"}]
    return {
        "filename": filename,
        "format": file_format,
        "row_count": len(table["rows"]),
        "columns": [
            {"name": column, "source_name": table["labels"][column], "example": table["rows"][0][column]}
            for column in table["columns"]
        ],
        "metric_candidates": metric_candidates,
        "parameter_candidates": numeric_candidates,
        "sample_rows": table["rows"][:10],
    }


def import_table(request: DatasetImportRequest) -> dict[str, Any]:
    file_format = detect_format(request.filename, request.format)
    table = parse_numeric_table(request.content, file_format)
    columns = set(table["columns"])
    selected = request.parameter_columns + request.metric_columns
    if len(selected) != len(set(selected)):
        raise ValueError("A column cannot be mapped as both a parameter and a metric")
    unknown = [column for column in selected if column not in columns]
    if unknown:
        raise ValueError(f"Unknown column mapping: {unknown[0]}")
    if not request.metric_columns:
        raise ValueError("Select at least one output metric column")
    if file_format == "openfoam_dat" and request.aggregation == "all":
        raise ValueError("OpenFOAM time-series imports require last-value or mean reduction")

    source_rows = table["rows"]
    numeric_rows: list[dict[str, float]] = []
    for row_number, row in enumerate(source_rows, start=1):
        numeric_row: dict[str, float] = {}
        for column in selected:
            try:
                number = float(row[column])
            except (TypeError, ValueError) as error:
                raise ValueError(f"Row {row_number}, selected column {table['labels'][column]!r} is not numeric") from error
            if not math.isfinite(number):
                raise ValueError(f"Row {row_number}, selected column {table['labels'][column]!r} is missing or non-finite")
            numeric_row[column] = number
        numeric_rows.append(numeric_row)
    if request.aggregation == "all":
        selected_rows = numeric_rows
    else:
        reduced: dict[str, float] = {}
        for column in request.metric_columns:
            samples = [row[column] for row in numeric_rows]
            reduced[column] = samples[-1] if request.aggregation == "last" else statistics.fmean(samples)
        for column in request.parameter_columns:
            reduced[column] = numeric_rows[-1][column]
        selected_rows = [reduced]

    expression_names = set(request.parameter_columns) | set(request.metric_columns)
    validate_expression(request.objective_expression, expression_names)
    constraint_names = [constraint.name for constraint in request.constraints]
    if len(constraint_names) != len(set(constraint_names)):
        raise ValueError("Constraint names must be unique")
    for constraint in request.constraints:
        validate_expression(constraint.expression, expression_names)

    evaluations: list[dict[str, Any]] = []
    for index, row in enumerate(selected_rows, start=1):
        parameters = {column: row[column] for column in request.parameter_columns}
        metrics = {column: row[column] for column in request.metric_columns}
        values = {**parameters, **metrics}
        try:
            objective_value = evaluate_expression(request.objective_expression, values)
            violations = []
            for constraint in request.constraints:
                observed = evaluate_expression(constraint.expression, values)
                violations.append(
                    observed - constraint.bound if constraint.relation == "<=" else constraint.bound - observed
                )
        except ValueError as error:
            raise ValueError(f"Could not evaluate imported row {index}: {error}") from error
        evaluations.append(
            {
                "sequence": index,
                "parameters": parameters,
                "metrics": metrics,
                "objective_value": objective_value,
                "constraint_violations": violations,
                "feasible": all(violation <= 0 for violation in violations),
            }
        )
    feasible = [row for row in evaluations if row["feasible"]]
    best_pool = feasible or evaluations
    best = min(best_pool, key=lambda row: row["objective_value"])
    if request.objective_direction == "maximize":
        best = max(best_pool, key=lambda row: row["objective_value"])
    return {
        "filename": request.filename,
        "source_format": file_format,
        "aggregation": request.aggregation,
        "objective_expression": request.objective_expression,
        "objective_direction": request.objective_direction,
        "row_count": len(evaluations),
        "source_row_count": len(source_rows),
        "parameter_columns": request.parameter_columns,
        "metric_columns": request.metric_columns,
        "source_columns": table["labels"],
        "best_objective": best["objective_value"],
        "best_parameters": best["parameters"],
        "best_metrics": best["metrics"],
        "best_feasible": bool(feasible),
        "feasible_count": len(feasible),
        "evaluations": evaluations,
    }
