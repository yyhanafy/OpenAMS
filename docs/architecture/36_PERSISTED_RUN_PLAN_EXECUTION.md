# Persisted optimization run-plan execution

## Purpose

This slice closes the artifact-provenance loop around run-plan execution.

```text
OptimizationRunPlan
        ↓
persist optimization_run_plan.json
        ↓
OptimizationRunPlanExecutor
        ↓
OptimizationCycleOrchestrator
        ↓
optimization_session.json
        ↓
link session artifact into run plan
```

## Fixed ordering

`PersistedOptimizationRunPlanExecutor` enforces:

1. persist the route decision before simulation;
2. execute the selected route;
3. obtain the resulting session artifact path;
4. write the forward link into the run-plan artifact.

The initial route decision therefore survives even when execution later fails
outside this boundary.

## Inputs

The executor receives:

- a typed `OptimizationRunPlan`;
- a `RunPlanExecutionRequest`;
- an `OptimizationRunPlanExecutor`;
- optional run-plan persistence configuration.

An output directory is mandatory because this application operation is
explicitly persistence-oriented.

## Result

`PersistedRunPlanExecutionResult` returns:

```text
cycle_result
run_plan_artifacts
session_artifact_path
```

The primary run-plan artifact is available through:

```python
result.run_plan_json
```

## Session artifact resolution

The integration recognizes the canonical cycle artifact field:

```text
session_artifact_path
```

It also accepts compatibility aliases:

```text
session_json
session_path
```

This keeps the adapter narrow while allowing existing artifact DTOs to be
connected without changing their persistence behavior.

## Strict and non-strict modes

By default, the run-plan artifact remains valid even when cycle persistence is
disabled and no session artifact path is exposed.

Set:

```python
require_session_artifact=True
```

to enforce a complete persisted chain.

## Completed provenance chain

With all persistence ports enabled:

```text
optimization_run_plan.json
        ↓
optimization_session.json
        ↓
candidate_evaluation.json
        ↓
workflow_result.json
```

The run-plan artifact records why the route was selected before candidate
execution began.

## Next slice

The next layer should define a workflow-launch manifest that gathers the
top-level artifact paths and execution status into one stable CLI-facing
document:

```text
optimization_launch_manifest.json
```

It should link to the run plan, session, evaluation, and workflow artifacts
without duplicating their contents.
