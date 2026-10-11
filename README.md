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
