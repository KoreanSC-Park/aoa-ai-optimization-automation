# AOA Proposed Backend API (v1)

Status: proposed; endpoints below are **not yet implemented**. Base: `http://127.0.0.1:<assigned-port>/api/v1`. The desktop launcher exchanges a session token securely; HTTP calls validate token. Prefer server-generated OpenAPI clients for TypeScript.

## Resource endpoints

| Verb | Path | Purpose |
|---|---|---|
| POST | /projects | create project |
| GET | /projects | list projects |
| GET | /projects/{project_id} | project detail |
| PUT | /projects/{project_id}/workflow | save workflow as new revision |
| POST | /workflows/validate | check schemas/typed edges/cycles |
| GET | /node-types | node registry and config JSON Schemas |
| POST | /projects/{project_id}/runs | create immutable run from revision; returns 202 |
| GET | /runs/{run_id} | current run snapshot/status |
| POST | /runs/{run_id}/pause | stop new evaluations (in-flight jobs continue) |
| POST | /runs/{run_id}/resume | restore checkpoint/reconcile and schedule |
| POST | /runs/{run_id}/cancel | request safe shutdown |
| GET | /runs/{run_id}/evaluations | paginated evaluations |
| GET | /runs/{run_id}/results | objective history, feasibility, summaries |
| GET | /evaluations/{evaluation_id}/artifacts | artifact manifest/download references |
| GET | /system/solvers | discovered Fluent installs and supported profiles |
| GET | /system/resources | available worker capacity |
| GET | /health | backend health |
| WS | /runs/{run_id}/events | progress stream |

### Run request

Use `Idempotency-Key` header to prevent duplicate runs.
```json
{
  "workflowRevision": 3,
  "execution": {
    "maxConcurrentEvaluations": 1,
    "cachePolicy": "reuse_success",
    "retry": {"maxAttempts": 2, "backoffSeconds": 10},
    "onEvaluationFailure": "continue",
    "seed": 42
  }
}
```

202:
```json
{"runId":"run-0001","status":"queued","snapshotId":"snapshot-0003","workflowRevision":3}
```

### Workflow example (minimal)

```json
{
  "schemaVersion": 1,
  "id": "wf-001",
  "revision": 1,
  "nodes": [
    {"id":"vars","type":"design_variables","version":1,"position":{"x":20,"y":20},"config":{"variables":[{"name":"inlet_velocity","type":"continuous","lower":0.1,"upper":2.0,"unit":"m/s"}]}},
    {"id":"doe","type":"doe","version":1,"position":{"x":200,"y":20},"config":{"method":"lhs","samples":32,"seed":42}},
    {"id":"solver","type":"fluent_solver","version":1,"position":{"x":400,"y":20},"config":{"caseFile":"models/base.cas.h5","adapter":"pyfluent","processorsPerJob":4,"maxIterations":500,"timeoutSeconds":3600,"parameterBindings":{"inlet_velocity":"inlet_velocity"},"outputMetrics":["pressure_drop"]}},
    {"id":"objective","type":"objective","version":1,"position":{"x":600,"y":20},"config":{"objectives":[{"name":"dp","expression":"pressure_drop","direction":"minimize"}]}}
  ],
  "edges": [
    {"id":"e1","source":"vars","sourceHandle":"design_space","target":"doe","targetHandle":"design_space"},
    {"id":"e2","source":"doe","sourceHandle":"candidate_batch","target":"solver","targetHandle":"candidate"},
    {"id":"e3","source":"solver","sourceHandle":"solver_result","target":"objective","targetHandle":"solver_result"}
  ]
}
```

The compiler must explicitly support `candidate_batch -> candidate` fan-out. A valid edge here is a declared compiler conversion, not an unrestricted type mismatch.

### Evaluation example

```json
{
  "id":"eval-0001",
  "runId":"run-0001",
  "status":"succeeded",
  "source":"solver",
  "attempt":1,
  "parameters":{"inlet_velocity":0.8},
  "metrics":{"pressure_drop":92.6},
  "objectives":[92.6],
  "constraintViolations":[-57.4],
  "feasible":true,
  "durationSeconds":185.4,
  "artifacts":["fluent.log","output.json"]
}
```

Normalize constraints as `g(x) <= 0`. A negative entry indicates margin, positive indicates violation. Missing or nonfinite outputs are invalid, **not zero**.

### WebSocket

```json
{"eventId":125,"timestamp":"2026-10-11T12:30:00Z","runId":"run-0001","type":"evaluation.completed","payload":{"evaluationId":"eval-0001","status":"succeeded","durationSeconds":185.4}}
```

Persist event IDs for reconnection; client obtains REST snapshot plus events after last received ID. Proposed events: run.started, run.paused, run.completed, evaluation.started, evaluation.progress, evaluation.completed, evaluation.failed, optimizer.updated. Never assume a WebSocket event is durable by itself.

### Error shape

```json
{"error":{"code":"INVALID_WORKFLOW","message":"Missing input: solver.candidate","details":{"nodeId":"solver"}}}
```

Use 400 for malformed request, 401/403 for auth, 404 for missing object, 409 for incompatible run state/revision conflict, 422 for schema validation, 202 for accepted async commands. Do not expose full filesystem paths or stack traces to the client.
