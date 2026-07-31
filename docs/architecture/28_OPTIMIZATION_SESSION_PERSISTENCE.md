# Optimization-session persistence

## Purpose

This layer persists and reconstructs optimizer-neutral session state so an optimization run can be inspected, transferred, and resumed.

```text
OptimizationSessionState
        ↓
OptimizationSessionPersistence
        ├── optimization_session.json
        ├── proposal_history.csv
        └── feedback_history.csv
```

## Stable schema

Current schema identifier:

```text
openams.optimization_session.v1
```

The canonical JSON stores the session route, immutable iteration history, candidate proposals, proposal status, optimizer feedback, objective components, metadata, and an optional link to the candidate-evaluation artifact.

## Typed reconstruction

`load_state()` reconstructs `OptimizationSessionState`, iterations, proposal records, candidate proposals, optimizer feedback, and objective components. Enum types, tuple boundaries, metadata, identifiers, and the next iteration index are preserved.

This allows a caller to construct a new `OptimizationSession` from the restored state and continue with the next iteration.

## CSV artifacts

`proposal_history.csv` contains one row per candidate-parameter pair, deterministically ordered by iteration, proposal index, and parameter name.

`feedback_history.csv` contains one row per evaluated candidate-objective component while retaining three-state feasibility, aggregate objective value, failure reasons, and unknown reasons.

## Resume boundary

OpenAMS reconstructs the shared optimizer-neutral history. A concrete optimizer may persist its private model checkpoint separately. This layer does not instantiate an optimizer, run a simulation, or generate the next proposal.

## Next slice

The next layer should add deterministic reference proposers for fully resolved fixed assignments and bounded contract search, providing reusable integration-test implementations without embedding optimizer-specific logic in session orchestration.
