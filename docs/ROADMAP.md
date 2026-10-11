# AOA Roadmap & Acceptance Criteria

Status: planning only. No phase is claimed complete.

## Product vision
Build a local-first Windows optimization environment comparable in **workflow intent**, not full scope, to optiSLang. Provide GUI-authored DOE -> CFD -> objectives/constraints -> optimizer -> results loops; record every candidate, failure and artifact.

## Delivery strategy

### P0 — Reliable scaffolding
- [ ] Review existing `src/aoa/` entry points and `frontend/` Vite scripts.
- [ ] Add FastAPI server under existing Python package with /health.
- [ ] Connect React GUI with typed client; validate localhost security policy.
- [ ] Add React Flow canvas, palette, inspector, save/load.
- [ ] Create versioned JSON/Pydantic node schemas, typed ports and DAG validator.
- [ ] Establish unit tests, formatting, typing and Windows CI.
**Acceptance:** saved flow round-trip, invalid edges/cycles rejected and backend health visible in GUI.

### P1 — End-to-end mock optimization (MVP slice)
- [ ] Add design variables (continuous), DOE LHS/Sobol/Random and deterministic seeds.
- [ ] Add mathematical mock solver (Branin/Rosenbrock).
- [ ] Implement objective/constraint numeric expression evaluation with safe AST.
- [ ] Add Optuna TPE adapter (`ask/tell`); leave pymoo/BoTorch interface stubs.
- [ ] Add run coordinator, SQLite models, immutable workflow snapshots and file manifests.
- [ ] Stream run/evaluation events and display history/chart/export CSV.
- [ ] Add SHA256 cache keyed to model and inputs; retry transient failures; resume checkpoint.
**Acceptance:** 20-point DOE + 50 optimizer evaluations launched in GUI, restart/resume consistent, duplicate evaluation executes once and produces same stored outputs.

### P2 — Fluent/PyFluent MVP
- [ ] Detect configured Fluent installation/license; pin supported version pair.
- [ ] Implement SolverAdapter around one approved baseline case + parameter/report mappings.
- [ ] Use unique evaluation directories and record convergence/metrics/logs.
- [ ] Worker subprocess supervision with timeout/cleanup; distinguish divergence from launch failures.
- [ ] Lock execution to one Fluent worker until validated.
- [ ] Test against a small version-controlled case where licensing permits.
**Acceptance:** unattended 10-run Fluent DOE, complete parameter/metric/log manifests, corrupted or nonfinite outputs rejected, interrupted run recoverable.

### P3 — Multiobjective / parallel
- [ ] pymoo NSGA-II adapter with cohort/generation-based ask/tell.
- [ ] Objective vector, normalized constraints and feasibility-aware Pareto analysis.
- [ ] Local resource manager (CPU/RAM/license/session) and two isolated Fluent workers.
- [ ] Extend dashboard to Pareto plots and status summaries.
**Acceptance:** constrained two-objective demo with reproducible nondominated front; simultaneous workers never clobber files.

### P4 — Surrogates and adaptive BO
- [ ] BoTorch GP + GPyTorch and configurable acquisition function.
- [ ] Warm-start with stored DOE results; uncertainty and validation plots.
- [ ] New-candidate -> Fluent -> GP-update loop with checkpoint state versioning.
- [ ] Clearly separate expensive CFD budget from surrogate fitting iterations.
**Acceptance:** BO warm-start and restart demonstrate reproducible dataset handling, pending candidate bookkeeping and improvement over a fixed baseline in a defined benchmark.

### P5 — Productization (deferred)
- [ ] Tauri installer and controlled backend lifecycle.
- [ ] More solver adapters (Python scripts, Mechanical, OpenFOAM).
- [ ] Remote workers / server deployment.
- [ ] ROM/AI surrogate plugin and advanced sensitivity analysis.

## Mandatory test matrix
| ID | Case | Expected |
|---|---|---|
| T01 | wrong typed edge, cycle, missing input | validation fails |
| T02 | DOE with same seed | same sample table |
| T03 | Branin/Rosenbrock | optimizer passes defined accuracy threshold |
| T04 | duplicate candidate and same model | no duplicate Fluent solve |
| T05 | model/case/settings changed | cache invalidated |
| T06 | transient error and numerical divergence | bounded retry only for transient |
| T07 | coordinator forced restart | durable states and checkpoint restored |
| T08 | missing, NaN or failed Fluent output | not accepted as success |
| T09 | two workers | separate directories and resource limits |
| T10 | GUI lost WS connection | REST/event replay yields consistent state |
| T11 | objective expression changed only | reuse raw solver results, recompute objective |
| T12 | same Idempotency-Key | one run created |

## Decisions / open risks
1. MVP backend should be native Python with React/Vite dev UI; defer Tauri packaging.
2. Local SQLite is sufficient under **single writer ownership**. Multi-writer/distributed experiments would require a stronger storage plan (e.g. PostgreSQL).
3. BoTorch and pymoo are **not needed for first running vertical slice**; keep adapters decoupled.
4. Clarify exact installed Fluent/PyFluent versions and availability of a redistributable small test case before implementing solver automation.
5. Fluent is not open source; PyFluent is the open-source interface, and solver licensing remains the operator's responsibility.
6. Keep default worker count 1 until resource, license and crash-recovery checks pass.
7. Planned dates are estimates; use acceptance criteria and test evidence as the release gate.
