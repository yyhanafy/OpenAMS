# Optimization launch manifest

## Purpose

This slice adds the stable CLI-facing artifact for one optimization launch:

```text
optimization_launch_manifest.json
```

The manifest links existing artifacts without duplicating their contents.

## Top-level artifact graph

```text
optimization_launch_manifest.json
        ├── optimization_run_plan.json
        ├── optimization_session.json
        ├── candidate_evaluation.json
        └── workflow_result.json
```

The manifest is an index, not a copy of the lower-level documents.

## Launch status

The supported states are:

```text
planned
running
completed
failed
```

A failed launch must carry an error message.

A non-failed launch must not carry an error message.

## Manifest contents

```json
{
  "schema_version": 1,
  "artifact_type": "optimization_launch_manifest",
  "launch": {
    "launch_id": "launch_0001",
    "status": "completed",
    "route": "direct_simulation",
    "reason_code": "ALL_ASSIGNMENTS_FULLY_RESOLVED",
    "error": null,
    "artifacts": {
      "run_plan": "plan/optimization_run_plan.json",
      "session": "session/optimization_session.json",
      "evaluation": "evaluation/candidate_evaluation.json",
      "workflow": "workflow/workflow_result.json"
    },
    "metadata": {}
  }
}
```

Artifact paths are stored relative to the manifest directory when possible.

## Builder

`OptimizationLaunchManifestBuilder` creates:

```text
completed(...)
failed(...)
```

The completed builder collects artifact paths from
`PersistedRunPlanExecutionResult` and the cycle artifact container.

The failed builder requires only the already-persisted run-plan path and the
error message.

## Reconstruction

`OptimizationLaunchManifestPersistence.load(...)` reconstructs a typed
manifest and resolves relative links against the manifest directory.

Malformed artifacts and unsupported schema versions are rejected.

## Architectural role

The launch manifest is the first document a CLI, developer, or LLM should open
after a run.

It answers:

- which route was selected;
- why it was selected;
- whether execution completed;
- where every primary artifact is located;
- whether an execution error occurred.

## Next slice

The next layer should add an atomic launch service that performs:

```text
select route
    ↓
persist and execute run plan
    ↓
write completed or failed launch manifest
```

It should catch execution failures only to persist the failed manifest, then
re-raise the original exception.
