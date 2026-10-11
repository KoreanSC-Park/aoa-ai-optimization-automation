# AOA — AI Optimization Automation

AOA is a starter project for building AI-assisted optimization and automation tools.

## Stack

- **Python** for optimization logic, data processing, and automation.
- **TypeScript + React** for the web GUI.

## Project layout

```text
src/aoa/       Python package and command-line entry point
frontend/      React + TypeScript interface (Vite)
```

## Run the Python package (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
aoa
```

## Run the GUI

Install Node.js 20.19+ or 22.12+, then:

```powershell
cd frontend
npm ci
npm run dev
```

The GUI and Python package are starter scaffolds; optimization features and API connections can be added as the project requirements take shape.

## Optimization Studio development plan

AOA is planned as a **Windows-local, optiSLang-inspired CFD optimization GUI** using the existing React/Vite frontend and Python package. This is a roadmap, **not yet a working feature set**.

- [Architecture and package layout](docs/ARCHITECTURE.md): React Flow, FastAPI, coordinator, SciPy DOE, Optuna / pymoo / BoTorch adapters, Fluent/PyFluent integration, persistence, caching and failure recovery.
- [Proposed backend API](docs/API.md): typed workflow nodes, REST/WebSocket endpoints, sample request/response contracts.
- [Phased roadmap and acceptance tests](docs/ROADMAP.md): P0 scaffold -> P1 math-function optimization -> P2 Fluent integration -> P3 constrained multiobjective/parallel -> P4 GP Bayesian optimization -> P5 packaging/extensions.

**MVP focus:** deterministic DOE, one local evaluation worker, objective/constraint handling, Optuna TPE, immutable run history, result plots, safe cache and restart/retry. A Fluent license and verified PyFluent/Fluent version pair are required for live CFD. Distributed execution, BoTorch GP-BO, pymoo NSGA-II and Tauri installer are later phases.
