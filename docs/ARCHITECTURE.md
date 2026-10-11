# AOA Architecture — Windows CFD Optimization Studio

Status: proposed (2026-10-11). This document describes intended behavior, **not implemented functionality**.

## Scope and principles
AOA aims to provide an optiSLang-like local optimization workflow on Windows: design space -> DOE -> Fluent/PyFluent -> metric extraction -> objectives/constraints -> optimization -> analysis. Preserve existing `src/aoa/` Python package and `frontend/` Vite/React application. Add modules incrementally.

- **Frontend:** React, TypeScript, React Flow (`@xyflow/react`) for typed node editing, inspectors, run control, Plotly dashboards. It must never be the source of truth for execution state.
- **API:** FastAPI + Pydantic, served on loopback, with OpenAPI and WebSocket progress streams.
- **Coordinator:** one authoritative async run coordinator, persisted evaluation state machine, concurrency/resource limits and recovery. Keep this **in-house and minimal** for the local MVP; no Redis, Dask, Prefect or Celery required.
- **DOE:** `scipy.stats.qmc` (LHS, Sobol; use Sobol `random_base2` for balanced powers-of-two designs).
- **Optimization:** independent adapters for Optuna (TPE + ask/tell), pymoo (NSGA-II + generation-wise ask/tell), BoTorch/GPyTorch (GP-based BO + acquisition optimizer). All call the same Evaluation service; no optimizer directly launches Fluent.
- **CFD:** PyFluent adapter. Fluent itself requires a commercial license. Pin and test a supported Fluent/PyFluent version pair before enabling actual solves.
- **Storage:** SQLite WAL / SQLAlchemy + Alembic (application metadata), project-local immutable manifests and artifacts. Single coordinator controls DB writes, including Optuna updates; do not assume SQLite supports arbitrary parallel Optuna writers.
- **Distribution:** start with Python backend + Vite dev frontend, then evaluate Tauri Windows packaging after workflows are proven. Packaging is out of MVP.

## Logical components

```text
frontend/ (React Flow / inspector / results)
   | localhost REST + WebSocket
src/aoa/api/ (FastAPI / Pydantic)
   |
src/aoa/core/ (graph compiler / run coordinator / scheduler / cache / resources)
   |               |                   |
src/aoa/doe/   src/aoa/optimization/  src/aoa/solvers/
SciPy QMC       Optuna/BoTorch/pymoo     Fluent/PyFluent; mock solver
   |               |                   |
   +---------------+-------------------+
                   |
            src/aoa/storage/
          SQLite + per-evaluation files
```

## Workflow semantics

Workflow JSON stores `schemaVersion`, nodes, edges, node configs and GUI positions. Ports are typed; the backend validates node type/version, port compatibility, missing inputs and cycles. **The persisted graph is a DAG**, and the optimization loop is an internal coordinator construct, not a back-edge in React Flow. One DOE node yields `candidate_batch`; the coordinator fans out candidates as independent evaluations. Optimizer adapters propose candidates then receive committed evaluation outcomes.

MVP node types:
| Node | Inputs | Outputs | Configuration |
|---|---|---|---|
| design_variables | none | design_space | name, bounds, type, units |
| doe | design_space | candidate_batch | lhs/sobol/random, samples, seed |
| fluent_solver | candidate | solver_result | case template, parameter bindings, report mappings, resource limits |
| objective | solver_result | objective_vector | restricted numeric expression, min/max |
| constraint | solver_result | constraint_vector | expression, comparator, bound |
| optimizer | design_space + evaluation_result | candidate_batch | adapter, evaluation budget, seed |
| results | evaluation_dataset | plots/export | chart selections |

The compiler maps authoring edges to execution dependencies; it does **not** attempt to execute every graph node once. The runtime owns candidate fan-out and optimization iterations. MVP can use a deterministic mathematical/mock solver in place of Fluent.

## Common internal contracts

```python
@dataclass
class Candidate:
    id: str
    parameters: dict[str, float]
    metadata: dict[str, object]

@dataclass
class EvaluationResult:
    candidate_id: str
    status: str  # succeeded|failed|invalid
    metrics: dict[str, float]
    objectives: list[float]
    violations: list[float]  # feasible iff all <= 0
    source_evaluation_id: str | None = None

class OptimizerAdapter(Protocol):
    def suggest(self, max_candidates: int) -> list[Candidate]: ...
    def observe(self, results: list[EvaluationResult]) -> None: ...
    def is_finished(self) -> bool: ...
    def save_checkpoint(self, directory: Path) -> None: ...
    def load_checkpoint(self, directory: Path) -> None: ...

class SolverAdapter(Protocol):
    def validate(self, config: dict) -> None: ...
    def prepare(self, config: dict, params: dict, workdir: Path) -> None: ...
    def execute(self, workdir: Path, timeout_seconds: int) -> dict: ...
    def collect(self, workdir: Path) -> dict[str, float]: ...
    def cleanup(self, workdir: Path) -> None: ...
```

Adapter checkpoints are version-sensitive; do not assume arbitrary optimizer state can be safely round-tripped as JSON.

## Fluent and resource policy

Every candidate gets a unique working directory. Treat template case/mesh, UDFs, numerical settings, Fluent version, bindings and output extraction definition as model inputs. Do not allow user-supplied expressions to invoke arbitrary Python via `eval()`; parse a whitelisted arithmetic expression AST. A preapproved Fluent parameter/report mapping is preferred to arbitrary Fluent API path strings. Raw journals/scripts are trusted-local advanced features only.

Worker pool starts at one Fluent process; each reserves `processorsPerJob` CPUs, a RAM safety margin and one required Fluent license/session allowance. Later allow concurrent independent subprocess workers with file isolation, bounded process cleanup and resource accounting. Frontend closure must not silently orphan Fluent sessions.

## Cache / failures / recovery

Keep **solver result cache** separate from **objective/constraint evaluation cache**:
- Solver key: canonical parameter values + case/mesh/UDF hashes + Fluent/version + numeric settings + boundary bindings + report/extraction definition as applicable.
- Objective key: solver result ID + normalized objective/constraint expressions, units and evaluator version.
- Reuse only validated successful solver outputs with existing artifacts; never reuse non-finite, incomplete or failed results.
- Maintain `Candidate`, `Evaluation` and `Attempt` as separate records. Retry transient launch/license/connection faults with bounded backoff; do **not** blindly retry numerical divergence.
- Persist transitions: `created -> queued -> preparing -> running -> collecting -> validating -> succeeded/failed/invalid`, with `retry_pending` for retryable failures.
- `pause` means stop scheduling new jobs; `cancel` requests graceful worker shutdown and then process cleanup. Persist optimizer checkpoints and run snapshot for resume. After crash, reconcile in-flight process IDs/artifacts before scheduling retries.
- Writes to artifact files should use temporary file then atomic rename; record checksums/relative paths. Prevent two workers from committing the same cache key concurrently.

## Suggested incremental package layout

```text
src/aoa/
  api/{projects,workflows,runs,evaluations,events}.py
  schemas/{workflow,nodes,evaluation}.py
  core/{compiler,coordinator,scheduler,cache,resources,state_machine}.py
  doe/scipy_qmc.py
  optimization/{base,optuna_adapter,botorch_adapter,pymoo_adapter}.py
  solvers/{base,mock,fluent/adapter,fluent/worker,fluent/results}.py
  analysis/{objectives,constraints,pareto}.py
  storage/{models,repository,artifacts}.py
frontend/src/
  components/workflow/{WorkflowCanvas,NodePalette,NodeInspector}.tsx
  nodes/{DesignVariables,Doe,Fluent,Objective,Constraint,Optimizer,Results}Node.tsx
  api/ ; stores/ ; charts/ ; schemas/
tests/{unit,integration,fluent}/
docs/ ; examples/
```

This is a **target layout**; avoid moving current scaffold files until imports and scripts are updated with tests.

## Data / security / reproducibility

Tables: projects, workflows (revisions), runs (immutable snapshot), candidates, evaluations, attempts, metrics, artifacts, optimizer_states, events. The large Fluent case/data files live on disk, not inside DB. Every run manifest records random seeds, environment versions, solver executable/version, input fingerprints and canonical parameter definitions.

Local HTTP only (`127.0.0.1`), authenticated desktop-to-backend token, path containment checks, validation on backend, trusted-project gate before arbitrary script execution, and restrictive CORS. Versioned Pydantic schemas and database migrations are required; unit conversions must be explicit.

## Non-goals for MVP

Remote/distributed cluster execution, multiphysics coupling, arbitrary node Python scripting, GPU surrogate training, multiuser authentication, complex conditional variables, full sensitivity analysis, Windows installer and exact feature parity with optiSLang are deferred.
