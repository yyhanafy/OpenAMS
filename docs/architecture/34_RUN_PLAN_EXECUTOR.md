# Optimization run-plan executor

## Purpose

This layer connects the route-selection decision to the optimization
application service.

```text
OptimizationRunPlan
        +
RunPlanExecutionRequest
        ↓
OptimizationRunPlanExecutor
        ├── run_direct_assignments(...)
        └── run_contract_search_iteration(...)
```

## Direct-plan execution

A direct plan must contain resolved assignments and must not supply:

- a candidate proposer;
- an existing optimization session;
- unresolved parameter bounds.

The executor creates a new direct-simulation session and forwards the
assignments unchanged.

```text
direct plan
    ↓
DirectAssignmentRunRequest
    ↓
OptimizationApplicationService.run_direct_assignments
```

## Contract-search execution

A contract-search plan must contain parameter bounds and requires a
`CandidateProposer`.

The executor either:

- creates a new contract-search session; or
- continues a supplied session whose identifier and route match.

```text
contract-search plan
    ↓
create or resume session
    ↓
ContractSearchIterationRequest
    ↓
OptimizationApplicationService.run_contract_search_iteration
```

## Route-decision provenance

The executor records the route decision in both session and iteration metadata.

```text
route
resolution_state
route_reason_code
route_reason
requires_contract
```

For a new session, synthesis metadata, caller session metadata, and decision
metadata are merged.

For every iteration, caller iteration metadata and decision metadata are
merged.

This makes the route decision auditable after persistence.

## Separation of responsibilities

The route selector decides:

```text
direct_simulation or contract_search
```

The plan executor decides:

```text
which application operation to invoke
```

The application service decides:

```text
how to assemble and run one optimization cycle
```

The cycle orchestrator decides:

```text
proposal → execution → evaluation → feedback → persistence ordering
```

## Invalid combinations rejected

The executor rejects:

- direct plan plus proposer;
- direct plan plus existing session;
- direct plan without assignments;
- contract-search plan without proposer;
- contract-search plan without bounds;
- supplied session with mismatched identifier;
- supplied session with the wrong route.

## Next slice

The next layer should add run-plan persistence and reconstruction:

```text
optimization_run_plan.json
```

This artifact should capture the route decision before simulation begins and
link forward to the resulting optimization session artifact.
