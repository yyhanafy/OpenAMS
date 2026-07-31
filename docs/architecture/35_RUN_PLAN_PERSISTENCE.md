# Optimization run-plan persistence

## Purpose

This slice persists the route decision before simulation begins.

```text
OptimizationRunPlan
        ↓
OptimizationRunPlanPersistence
        ↓
optimization_run_plan.json
```

The artifact can later be reconstructed into a typed
`OptimizationRunPlan`.

## Artifact contents

```json
{
  "schema_version": 1,
  "artifact_type": "optimization_run_plan",
  "plan": {
    "route": "...",
    "resolution_state": "...",
    "reason_code": "...",
    "reason": "...",
    "requires_contract": true,
    "candidate_count": 0,
    "assignments": [],
    "parameter_bounds": {},
    "fixed_parameters": {},
    "metadata": {}
  },
  "links": {
    "optimization_session": "session/optimization_session.json"
  }
}
```

## Pre-simulation provenance

The artifact captures:

- the selected route;
- the synthesis resolution state;
- the machine-readable route reason;
- the human-readable route explanation;
- resolved assignments;
- unresolved ranges;
- fixed parameters;
- synthesis metadata.

This information exists independently of simulation success or failure.

## Reconstruction

`load(...)` and `from_payload(...)` rebuild a typed plan.

Reconstruction validates route invariants:

```text
direct_simulation
    requires at least one assignment
    forbids parameter bounds

contract_search
    requires parameter bounds
```

Unsupported schema versions and malformed artifacts are rejected.

## Forward session link

After execution, the run-plan artifact can be updated with:

```text
links.optimization_session
```

using:

```python
link_session_artifact(...)
```

The helper stores a relative path when the session artifact is inside the
run-plan directory tree. Otherwise, it preserves the supplied path.

The link can be resolved with:

```python
read_session_artifact_link(...)
```

## Artifact chain

The persisted provenance chain is now:

```text
optimization_run_plan.json
        ↓
optimization_session.json
        ↓
candidate_evaluation.json
        ↓
workflow_result.json
```

The exact lower-level direction may also be represented by existing artifact
links, but the run plan always records the forward execution outcome.

## Next slice

The next layer should integrate run-plan persistence directly with
`OptimizationRunPlanExecutor`:

```text
persist plan
    ↓
execute plan
    ↓
persist session through cycle
    ↓
link session artifact back into plan
```

The integration result should return both the cycle result and the run-plan
artifact path.
