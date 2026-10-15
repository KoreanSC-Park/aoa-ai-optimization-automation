# AOA implementation status

Checked against the original [P0–P5 plan (PR #1)](https://github.com/KoreanSC-Park/aoa-ai-optimization-automation/pull/1), the runnable [mock MVP (PR #2)](https://github.com/KoreanSC-Park/aoa-ai-optimization-automation/pull/2), and this checkout on 2026-10-16 (Asia/Seoul).

`main` is still the initial scaffold. PR #1 contains proposed architecture/API/roadmap documents; PR #2 contains the first runnable implementation. This continuation builds on `feat/mock-optimization-mvp`; it does not imply either earlier PR has been merged.

## P0 — Reliable scaffolding

- [x] Python CLI, FastAPI `/api/v1/health`, typed React client, visible backend health.
- [x] React Flow canvas and shared workflow configuration inspector.
- [x] Supported-node palette: select nodes, restore a deleted node without duplicating it, restore pipeline connections.
- [x] Versioned JSON workflow and node schemas, typed edges, cycle/missing-input rejection in backend; incompatible/duplicate connections blocked while editing.
- [x] Validated browser save/load and portable JSON export/import, preserving configuration, connections and positions.
- [x] Read older browser envelopes and v1 run snapshots without node positions/version fields.
- [x] Reject invalid documents before changing the current editor or creating a run; show browser storage failures.
- [x] Python tests and frontend component/contract tests; TypeScript build and frontend lint.
- [x] Add Windows CI for Python 3.11/3.13 and Node 22 tests/lint/build. Remote CI execution must be checked separately.
- [ ] Finish local API security policy: desktop session token/Host validation, in addition to current loopback binding and restricted CORS.
- [ ] Establish Python formatting/static typing conventions and checks.

The editor supports exactly the six-node mock pipeline. The palette restores those nodes; it is not an arbitrary graph compiler. An incomplete graph can be edited, but save/export/run require the complete valid pipeline. Save/load/import/export require the local engine for authoritative validation. Browser storage holds one workflow; JSON files provide portable copies. Project/revision APIs and a node-schema registry remain proposed API features.

## P1 — Mock optimization

- [x] Continuous variables with finite bounds; seeded LHS and random DOE.
- [x] Deterministic Sphere, Branin and Rosenbrock mock solvers.
- [x] Restricted numeric AST expressions and normalized constraints.
- [x] Optuna TPE ask/tell; a single queued worker.
- [x] SQLite run/evaluation/event history, immutable configuration/layout snapshots, event replay by REST polling, chart/CSV export.
- [x] Raw mock solver cache; recompute objectives when expressions change; bounded transient-error retry.
- [x] Numeric CSV and the documented OpenFOAM `.dat` import subset (additional usable MVP functionality).
- [ ] Sobol DOE.
- [ ] Durable optimizer checkpoints, pause/resume/cancel and interrupted-run recovery. Completed history persistence is not active-run recovery.
- [ ] Per-evaluation attempts/artifact manifests and environment fingerprints.
- [ ] WebSocket progress stream; polling/replay exists today.
- [ ] Optimizer accuracy acceptance thresholds and a forced-restart recovery test.

P1 acceptance is **not complete** until restart/resume and interrupted evaluation reconciliation work.

## P2–P5 — Remaining scope

| Phase | Remaining planned work | Prerequisite |
| --- | --- | --- |
| P2 | Fluent discovery/version profile, approved case bindings, isolated evaluation directories, supervised timeout/cleanup, convergence/metrics/log collection | Confirm Fluent/PyFluent version pair, solver license and a small permitted case; finish recovery first |
| P3 | pymoo NSGA-II, objective vectors, feasibility-aware Pareto analysis, resource limits, isolated parallel workers | Validated single-worker Fluent pipeline |
| P4 | BoTorch/GPyTorch GP, acquisitions, DOE warm-start, uncertainty/validation plots, versioned checkpoints | Reliable stored datasets and recovery |
| P5 | Tauri lifecycle/installer, more solver adapters, remote workers, surrogate/sensitivity plugins | Core workflows accepted |

## Next implementation order

1. Finish the remaining P0 local API security and Python quality checks.
2. Add reproducible Sobol DOE with explicit powers-of-two sample validation.
3. Add durable single-worker run control/recovery and checkpoint acceptance tests.
4. Add artifact/attempt manifests, reproducibility metadata and the remaining P1 acceptance tests.
5. Verify the actual Fluent environment before P2; keep worker count at one until its recovery checks pass.

Do not advance into parallel licensed solves while P1 recovery is incomplete. Keep P3/P4/P5 separate from the current editor/save-load change.

## Verification for this continuation

- Windows local: Python 3.13.15 / Node 22.23.2.
- Backend: 39 tests passed, including old v1 documents, layout snapshot persistence across API restart, invalid node/schema versions/ports/cycles, and nonfinite JSON returning 422 rather than 500.
- Frontend: 10 tests passed; lint and TypeScript/production build passed.
- Chromium on Windows: node drag -> save/load -> JSON download/import, rejected schema-v99 import preserving edits, node deletion/palette restoration, 20 DOE + 50 TPE evaluations, immutable result columns and CSV download passed.
- A second identical run reused all 70 raw solver results; downloaded CSV contains 20 DOE and 50 optimizer rows.
- Loopback smoke checks exposed intermittent truncated responses with short-lived connections. Vite now reuses backend connections; all 30 repeated proxied health requests passed after the change.
- Live Fluent/OpenFOAM execution and active-run crash recovery remain unimplemented/unverified. The Optuna constraints callback produces its existing upstream experimental-feature warning.
