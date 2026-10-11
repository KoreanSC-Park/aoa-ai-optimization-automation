"""Versioned request models shared by the local API and optimizer."""

from __future__ import annotations

import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aoa.expressions import validate_expression


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VariableSpec(StrictModel):
    name: str = Field(min_length=1, max_length=48)
    lower: float
    upper: float

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", value):
            raise ValueError("Use a variable name beginning with a letter; letters, numbers, and _ are allowed")
        return value

    @model_validator(mode="after")
    def valid_bounds(self) -> "VariableSpec":
        if not math.isfinite(self.lower) or not math.isfinite(self.upper):
            raise ValueError("Bounds must be finite numbers")
        if self.lower >= self.upper:
            raise ValueError("Variable lower bound must be less than upper bound")
        return self


class DoeConfig(StrictModel):
    method: Literal["lhs", "random"] = "lhs"
    samples: int = Field(default=20, ge=0, le=500)
    seed: int = Field(default=42, ge=0, le=2**32 - 1)


class SolverConfig(StrictModel):
    kind: Literal["sphere", "rosenbrock", "branin"] = "sphere"
    retry_attempts: int = Field(default=1, ge=1, le=3)


class ObjectiveConfig(StrictModel):
    name: str = Field(default="objective", min_length=1, max_length=48)
    expression: str = Field(default="sphere", min_length=1, max_length=200)
    direction: Literal["minimize", "maximize"] = "minimize"


class ConstraintConfig(StrictModel):
    name: str = Field(min_length=1, max_length=48)
    expression: str = Field(min_length=1, max_length=200)
    relation: Literal["<=", ">="] = "<="
    bound: float

    @field_validator("bound")
    @classmethod
    def finite_bound(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("Constraint bound must be finite")
        return value


class OptimizerConfig(StrictModel):
    engine: Literal["optuna_tpe"] = "optuna_tpe"
    trials: int = Field(default=50, ge=0, le=500)
    seed: int = Field(default=43, ge=0, le=2**32 - 1)


class GraphNode(StrictModel):
    id: Literal["variables", "doe", "solver", "objective", "optimizer", "results"]
    type: Literal["design_variables", "doe", "mock_solver", "objective", "optuna_optimizer", "results"]


class GraphEdge(StrictModel):
    source: str
    target: str
    source_handle: str
    target_handle: str


class WorkflowGraph(StrictModel):
    nodes: list[GraphNode] = Field(
        default_factory=lambda: [
            GraphNode(id="variables", type="design_variables"),
            GraphNode(id="doe", type="doe"),
            GraphNode(id="solver", type="mock_solver"),
            GraphNode(id="objective", type="objective"),
            GraphNode(id="optimizer", type="optuna_optimizer"),
            GraphNode(id="results", type="results"),
        ],
        min_length=1,
        max_length=32,
    )
    edges: list[GraphEdge] = Field(
        default_factory=lambda: [
            GraphEdge(source="variables", target="doe", source_handle="design_space", target_handle="design_space"),
            GraphEdge(source="doe", target="solver", source_handle="candidate_batch", target_handle="candidate"),
            GraphEdge(source="solver", target="objective", source_handle="solver_result", target_handle="solver_result"),
            GraphEdge(source="objective", target="optimizer", source_handle="objective_vector", target_handle="evaluation_result"),
            GraphEdge(source="optimizer", target="results", source_handle="run_summary", target_handle="run_summary"),
        ],
        max_length=64,
    )

    @model_validator(mode="after")
    def validate_topology(self) -> "WorkflowGraph":
        expected_types = {
            "variables": "design_variables",
            "doe": "doe",
            "solver": "mock_solver",
            "objective": "objective",
            "optimizer": "optuna_optimizer",
            "results": "results",
        }
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Workflow graph node IDs must be unique")
        actual_types = {node.id: node.type for node in self.nodes}
        if actual_types != expected_types:
            missing = sorted(set(expected_types) - set(actual_types))
            if missing:
                raise ValueError(f"Workflow graph is missing required node: {missing[0]}")
            raise ValueError("Workflow graph nodes do not match the supported execution pipeline")
        edge_tuples = [(edge.source, edge.target, edge.source_handle, edge.target_handle) for edge in self.edges]
        if len(edge_tuples) != len(set(edge_tuples)):
            raise ValueError("Workflow graph edges must be unique")
        actual_pairs = [(edge.source, edge.target) for edge in self.edges]
        adjacency = {node_id: [] for node_id in expected_types}
        for source, target in actual_pairs:
            if source not in adjacency or target not in adjacency:
                raise ValueError("Workflow graph edge references an unknown node")
            adjacency[source].append(target)
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise ValueError("Workflow graph contains a cycle")
            if node_id in visited:
                return
            visiting.add(node_id)
            for target in adjacency[node_id]:
                visit(target)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in adjacency:
            visit(node_id)

        expected_edges = {
            ("variables", "doe", "design_space", "design_space"),
            ("doe", "solver", "candidate_batch", "candidate"),
            ("solver", "objective", "solver_result", "solver_result"),
            ("objective", "optimizer", "objective_vector", "evaluation_result"),
            ("optimizer", "results", "run_summary", "run_summary"),
        }
        actual_edges = set(edge_tuples)
        if actual_edges != expected_edges:
            missing = expected_edges - actual_edges
            unexpected = actual_edges - expected_edges
            if missing:
                source, target, _, _ = sorted(missing)[0]
                raise ValueError(f"Workflow graph is missing the required connection {source} → {target}")
            source, target, _, _ = sorted(unexpected)[0]
            raise ValueError(f"Unsupported workflow connection {source} → {target}; this version supports the six-node pipeline only")
        return self


class WorkflowConfig(StrictModel):
    schema_version: Literal[1] = 1
    name: str = Field(default="Untitled workflow", min_length=1, max_length=100)
    variables: list[VariableSpec] = Field(
        default_factory=lambda: [
            VariableSpec(name="x", lower=-5.0, upper=5.0),
            VariableSpec(name="y", lower=-5.0, upper=5.0),
        ],
        min_length=1,
        max_length=8,
    )
    doe: DoeConfig = Field(default_factory=DoeConfig)
    solver: SolverConfig = Field(default_factory=SolverConfig)
    objective: ObjectiveConfig = Field(default_factory=ObjectiveConfig)
    constraints: list[ConstraintConfig] = Field(default_factory=list, max_length=8)
    optimizer: OptimizerConfig = Field(default_factory=OptimizerConfig)
    graph: WorkflowGraph = Field(default_factory=WorkflowGraph)

    @model_validator(mode="after")
    def valid_workflow(self) -> "WorkflowConfig":
        names = [variable.name for variable in self.variables]
        if len(names) != len(set(names)):
            raise ValueError("Variable names must be unique")
        metric_names = {
            "sphere": {"sphere", "objective"},
            "rosenbrock": {"rosenbrock", "objective"},
            "branin": {"branin", "objective"},
        }[self.solver.kind]
        allowed_names = set(names) | metric_names
        validate_expression(self.objective.expression, allowed_names)
        constraint_names = [constraint.name for constraint in self.constraints]
        if len(constraint_names) != len(set(constraint_names)):
            raise ValueError("Constraint names must be unique")
        for constraint in self.constraints:
            if not math.isfinite(constraint.bound):
                raise ValueError(f"Constraint {constraint.name!r} needs a finite bound")
            validate_expression(constraint.expression, allowed_names)
        if self.solver.kind in {"rosenbrock", "branin"} and len(self.variables) < 2:
            raise ValueError(f"The {self.solver.kind.title()} mock solver requires at least two variables")
        return self


class RunRequest(StrictModel):
    workflow: WorkflowConfig = Field(default_factory=WorkflowConfig)

    @model_validator(mode="after")
    def has_evaluations(self) -> "RunRequest":
        if self.workflow.doe.samples + self.workflow.optimizer.trials == 0:
            raise ValueError("A run needs at least one DOE sample or optimizer trial")
        return self
