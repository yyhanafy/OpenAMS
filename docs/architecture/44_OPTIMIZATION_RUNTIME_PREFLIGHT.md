# Optimization runtime preflight

## Purpose

The launch stack now has a non-executing validation boundary.

```text
composition JSON
        ↓
path normalization
        ↓
factory import and signature validation
        ↓
ngspice runtime JSON validation
        ↓
leaf dependency import validation
        ↓
preflight report
```

No simulator is launched. No component factory is executed. No optimization
artifacts are written unless an explicit report path is requested.

## CLI

```bash
python -m openams.cli.validate_optimization_runtime \
  --runtime-config config/optimization_composition.json
```

Optional persisted report:

```bash
python -m openams.cli.validate_optimization_runtime \
  --runtime-config config/optimization_composition.json \
  --output runtime/optimization_preflight.json
```

Success returns exit code `0` and prints:

```json
{
  "schema_version": 1,
  "status": "valid",
  "composition_path": "/absolute/config/optimization_composition.json",
  "run_plan_executor_factory":
    "openams.optimization.ngspice_runtime:create_run_plan_executor",
  "run_plan_executor_kwargs": {
    "config_path": "/absolute/config/ngspice_optimization.json"
  },
  "ngspice_runtime_path":
    "/absolute/config/ngspice_optimization.json",
  "assignment_workflow_factory":
    "project_runtime:create_assignment_workflow",
  "objectives_factory":
    "project_runtime:create_objectives",
  "screening_results_getter_factory": null,
  "proposer": "grid",
  "points_per_dimension": 3
}
```

Invalid configuration returns exit code `2` and a structured error.

## Validations

The preflight checks:

- composition JSON readability and schema version;
- composition object structure;
- path-valued factory argument resolution;
- run-plan executor factory import and callability;
- configured factory keyword compatibility;
- explicit ngspice runtime configuration path;
- ngspice runtime JSON readability and schema version;
- ngspice runtime object structure;
- assignment-workflow factory import and callability;
- objectives factory import and callability;
- optional screening-result getter factory import and callability;
- proposer name and grid density.

## Non-execution guarantee

Preflight imports referenced callables but never invokes them.

This makes it suitable for:

- CI checks;
- installation validation;
- developer handoff;
- LLM-driven execution planning;
- runtime configuration audits before expensive simulation.

## Launch sequence

The recommended execution sequence is now:

```text
validate_optimization_runtime
        ↓
launch_optimization
        ↓
optimization_run_plan.json
        ↓
workflow/evaluation/session artifacts
        ↓
optimization_launch_manifest.json
```
