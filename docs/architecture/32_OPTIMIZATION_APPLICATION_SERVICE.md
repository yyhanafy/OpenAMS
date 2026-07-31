# Optimization application service

## Purpose

This layer exposes the first high-level OpenAMS operations for candidate
execution.

```text
OptimizationApplicationService
        ├── run_direct_assignments(...)
        └── run_contract_search_iteration(...)
```

Both operations reuse the same `OptimizationCycleOrchestrator`.

## Direct-assignment operation

```text
fully resolved assignments
        ↓
DirectAssignmentRunRequest
        ↓
DirectAssignmentProposer
        ↓
direct_simulation session
        ↓
optimization-cycle orchestrator
```

This path is used after topology and technology synthesis have resolved every
required design variable.

It does not:

- create an executable optimization contract;
- create unresolved bounds;
- invoke an adaptive optimizer;
- reinterpret fixed assignments as search variables.

This preserves the OpenAMS architectural rule that fully resolved assignments
go directly to simulation, parsing, screening, evaluation, and persistence.

## Contract-search operation

```text
contract_search session
        +
unresolved parameter bounds
        +
CandidateProposer
        ↓
ContractSearchIterationRequest
        ↓
optimization-cycle orchestrator
```

The operation executes exactly one iteration and mutates only the
`OptimizationSession` wrapper by replacing its immutable state.

A caller can repeatedly invoke the operation to continue optimization.

## New-session and resume support

The service provides:

```python
create_contract_search_session(...)
resume_contract_search_session(...)
```

A restored `OptimizationSessionState` from session persistence can therefore
be wrapped and continued without rebuilding previous iterations.

## Request objects

### DirectAssignmentRunRequest

Carries:

- session identifier;
- fully resolved assignments;
- optional fixed parameters;
- optional output directory;
- session metadata;
- iteration metadata.

### ContractSearchIterationRequest

Carries:

- existing optimization session;
- candidate proposer;
- unresolved parameter bounds;
- batch size;
- optional fixed parameters;
- optional output directory;
- iteration metadata.

## Dependency assembly

`OptimizationApplicationServices` contains:

- `CandidateBatchExecutor`;
- `CandidateBatchEvaluator`;
- optional `OptimizationCyclePersistence`.

This keeps the application service independent of:

- ngspice;
- a specific topology;
- a specific optimizer;
- one persistence layout;
- CLI argument parsing.

## Application boundary achieved

The architecture now has a complete reusable path:

```text
application request
        ↓
route-specific proposer
        ↓
optimization cycle
        ↓
workflow execution
        ↓
candidate evaluation
        ↓
feedback
        ↓
session update
        ↓
artifact persistence
```

## Next slice

The next layer should add a CLI-facing run-plan model and route selector that
accepts synthesis output and decides:

```text
all assignments fully resolved
        → direct_simulation

one or more unresolved ranges
        → contract_search
```

The route selector must report the reason for the decision and must not infer
independent variables from simulator behavior.
