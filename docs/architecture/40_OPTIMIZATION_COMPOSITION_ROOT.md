# Optimization repository composition root

## Purpose

This slice adds a repository-owned composition root for the optimization
application stack.

The CLI no longer requires a project-specific launch-service factory.

```text
runtime composition JSON
        ↓
OptimizationCompositionRoot
        ↓
OptimizationRunPlanExecutor
        ↓
PersistedOptimizationRunPlanExecutor
        ↓
OptimizationLaunchService
```

## Runtime configuration

```json
{
  "schema_version": 1,
  "composition": {
    "run_plan_executor_factory": "openams_runtime:create_run_plan_executor",
    "plan_subdirectory": "plan",
    "require_session_artifact": true
  }
}
```

The referenced factory supplies the infrastructure-aware
`OptimizationRunPlanExecutor`.

All higher application layers are assembled by the repository.

## Why the leaf factory remains

The run-plan executor depends on concrete infrastructure such as:

- ngspice simulation workflow;
- raw-result parsing;
- specification screening;
- persistence directories;
- direct-assignment proposer;
- contract-search proposer.

Those objects may require topology-specific files and environment paths.

The repository composition root owns the application wiring while the leaf
factory owns only infrastructure construction.

## CLI use

```bash
python -m openams.cli.launch_optimization \
  --input launch_input.json \
  --runtime-config optimization_runtime.json
```

Alternatively:

```bash
export OPENAMS_OPTIMIZATION_RUNTIME_CONFIG=optimization_runtime.json

python -m openams.cli.launch_optimization \
  --input launch_input.json
```

The prior `--factory module:function` option remains available as an explicit
override.

## Validation

The composition root rejects:

- unsupported runtime schema versions;
- missing composition objects;
- malformed factory references;
- non-callable factories;
- factories returning the wrong component type;
- invalid plan-subdirectory or strictness settings.

## Architectural boundary

The repository now owns:

```text
route selection
run-plan persistence
plan execution
session linking
launch-manifest persistence
CLI adaptation
```

Only the simulator/topology infrastructure leaf remains externally
constructed.

## Next slice

The next slice should add the concrete ngspice infrastructure leaf factory
using the current repository simulation, evaluation, persistence, and reference
proposer implementations.
