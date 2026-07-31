# Atomic optimization launch service

## Purpose

This slice adds the top-level application service for one optimization launch.

```text
SynthesisRunInput
        ↓
OptimizationRouteSelector
        ↓
OptimizationRunPlan
        ↓
PersistedOptimizationRunPlanExecutor
        ↓
OptimizationLaunchManifest
```

The service is the first complete application boundary that starts from
synthesis output and ends with a CLI-facing artifact index.

## Launch request

`OptimizationLaunchRequest` contains:

```text
launch_id
synthesis input
execution request
launch metadata
```

The execution request must contain an output directory.

## Successful launch ordering

```text
select route
    ↓
persist run plan
    ↓
execute direct simulation or contract search
    ↓
link session artifact into run plan
    ↓
build completed launch manifest
    ↓
persist optimization_launch_manifest.json
```

The successful result returns:

```text
plan
persisted execution result
typed launch manifest
launch-manifest artifact paths
```

## Failure behavior

Execution failures are handled narrowly:

1. determine whether the run-plan artifact was already persisted;
2. when present, write a failed launch manifest;
3. re-raise the original exception object unchanged.

The service does not wrap or replace the original exception.

If failure occurs before the run-plan artifact exists, no incomplete launch
manifest is fabricated.

## Failure manifest

A failed manifest contains:

```text
status = failed
route
reason_code
error
run-plan artifact link
```

Session, evaluation, and workflow links remain absent unless a future recovery
layer explicitly discovers them.

## Atomic meaning

The service is atomic at the application-provenance level:

- a completed run produces a completed launch manifest;
- a failed execution with a persisted plan produces a failed manifest;
- the original failure still propagates to the caller.

It does not claim filesystem transactionality across every artifact.

## Top-level execution path

```text
topology and technology synthesis
        ↓
SynthesisRunInput
        ↓
OptimizationLaunchService
        ├── direct_simulation
        └── contract_search
        ↓
optimization_launch_manifest.json
```

## Next slice

The next layer should add a CLI adapter that reads a normalized synthesis-input
JSON document, launches the workflow, and prints only the launch-manifest path
plus a concise route/status summary.
