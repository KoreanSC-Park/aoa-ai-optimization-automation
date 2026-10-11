# AOA — AI Optimization Automation

AOA is a local-first optimization workflow prototype. This first runnable slice pairs a React Flow workflow canvas with a Python API, reproducible DOE, an Optuna TPE optimizer, and a license-free mathematical solver. It also imports selected existing numeric CFD results for objective/constraint analysis.

## Start on Windows

Use Python 3.11–3.13, Node.js 20.19+ or 22.12+, and npm. Run the backend and frontend in separate PowerShell terminals. Check installed Python versions with `py -0p`; the commands below use the launcher's default Python 3. If that default is outside 3.11–3.13, select an installed supported version with `py -3.11`, `py -3.12`, or `py -3.13` instead.

From a PowerShell terminal, clone this implementation branch (the default `main` branch is still the starter scaffold), then enter the checkout:

```powershell
git clone --branch feat/mock-optimization-mvp --single-branch https://github.com/KoreanSC-Park/aoa-ai-optimization-automation.git
cd aoa-ai-optimization-automation
```

Terminal 1, from the repository root:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe --version
$env:AOA_DATA_DIR = "$env:LOCALAPPDATA\AOA"
.\.venv\Scripts\aoa.exe serve --host 127.0.0.1 --port 8000
```

Terminal 2:

```powershell
cd frontend
npm ci
npm run dev
```

Open the local URL printed by Vite, usually `http://localhost:5173`. The sample workflow starts with a 20-point Latin-hypercube DOE followed by 50 Optuna TPE trials on the Sphere benchmark. Click **Run workflow**; results and a CSV export appear below the canvas.

## Import existing results

Choose a numeric CSV or OpenFOAM `.dat` file in **Use existing solver results**. Preview and map columns as design inputs, output metrics, or ignore; choose a safe objective expression; then import and analyze. Input parameters and solver metrics remain distinct. Imported rows can be checked against the same numeric constraints used for optimization.

The OpenFOAM support is intentionally narrow: a header line containing `# Time` followed by column names on the same line (for example, `# Time Cm Cd Cl Cl(f) Cl(r)`), then finite numeric whitespace/tab-separated rows. This covers common `postProcessing/.../forceCoeffs.dat` output; punctuation in names is normalized (`Cl(f)` becomes `Cl_f`). For that time-series format, choose the last row or mean across time. CSV keeps each row as an evaluation. Imports are limited to 2 MB of text and 100,000 rows.

OpenFOAM function objects write requested text/field data under the case's `postProcessing` directory, and `forceCoeffs` documents a `.dat` output. OpenFOAM output varies with function object and version, so this importer does not claim to support arbitrary output files. It does not read mesh fields, vector/tensor files, binary data, VTK, or launch OpenFOAM. See the official [function-object guide](https://doc.openfoam.com/2306/tools/post-processing/function-objects/) and [forceCoeffs output/API reference](https://api.openfoam.com/2306/forceCoeffs_8H_source.html).

Included fixtures:

- `examples/openfoam/forceCoeffs.dat` — representative tabular force-coefficient output
- `examples/parameter-sweep.csv` — numeric input/output sweep table

## Checks

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

From `frontend`:

```powershell
npm test
npm run lint
npm run build
```

## What's implemented

- Typed six-node React Flow canvas; only the supported pipeline topology is accepted by backend validation. The current graph is a predefined pipeline, not an arbitrary graph compiler. Dragging changes layout; changing connections to an unsupported flow fails before a run starts.
- Continuous design variables with bounds, seeded Latin-hypercube or random DOE.
- Deterministic mock Sphere, Rosenbrock, and Branin solvers; no Fluent/OpenFOAM installation or license needed for the smoke flow.
- Optuna TPE in minimize or maximize direction; safe arithmetic objective expressions and normalized `<= 0` constraint violations.
- SQLite run/evaluation/event history, idempotent run requests, solver-result caching keyed by mock model/version/inputs, CSV export, and bounded retry code for explicitly transient solver errors. The mock solver does not simulate transient failures.
- Numeric CSV and the headered OpenFOAM `.dat` subset above, stored as imported datasets rather than solver executions.
- Runs execute through one local worker. Later runs queue behind the current run.

## Current boundaries

- ANSYS Fluent/PyFluent live execution is not configured or tested. It needs the user's verified Fluent/PyFluent version pair and valid solver license.
- OpenFOAM execution and raw-field parsing are not implemented; only the documented numeric `.dat`/CSV import subset is available.
- BoTorch GP Bayesian optimization, pymoo multiobjective optimization, parallel evaluations/workers, pause/resume or crash recovery, arbitrary user-defined graph nodes, and desktop packaging are later work.
- The local UI is for development and smoke testing, not production deployment. The API binds to loopback (`127.0.0.1`) only.

## Local data

Run history and imported datasets are stored in `aoa.db` under `%LOCALAPPDATA%\AOA` on Windows. Set `AOA_DATA_DIR` before starting the backend to choose another folder. Restarting the backend preserves completed history. To start fresh, stop the server and remove that database folder.

No external AI API key is required to run this prototype.
