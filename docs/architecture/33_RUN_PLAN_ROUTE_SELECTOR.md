# Run-plan model and route selector

## Purpose

This layer turns assignment-synthesis output into an explicit execution plan.

```text
assignment synthesis output
        ↓
SynthesisRunInput
        ↓
OptimizationRouteSelector
        ↓
OptimizationRunPlan
```

The selector makes one architectural decision:

```text
no unresolved ranges
and at least one resolved assignment
        → direct_simulation

one or more unresolved ranges
        → contract_search
```

## No simulator-based inference

The selector does not inspect:

- ngspice convergence;
- DC operating-point results;
- AC metrics;
- optimization scores;
- prior candidate performance.

Independent and dependent variables must already have been classified by
synthesis metadata and topology/technology reasoning.

The simulator validates a candidate. It does not decide which variables are
independent.

## Synthesis input

`SynthesisRunInput` carries:

- zero or more resolved assignments;
- zero or more unresolved parameter ranges;
- shared fixed parameters;
- metadata.

The normalized resolution state is:

```text
FULLY_RESOLVED
PARTIALLY_RESOLVED
UNRESOLVED
```

## Direct route

The direct route requires:

- at least one assignment;
- no unresolved parameter ranges.

The selected reason code is:

```text
ALL_ASSIGNMENTS_FULLY_RESOLVED
```

No executable optimization contract is required.

## Contract-search route

Any explicit unresolved range selects contract search.

The selected reason code is:

```text
UNRESOLVED_PARAMETER_RANGES_PRESENT
```

This remains true when synthesis has also supplied partial assignments or fixed
parameters.

A degenerate range such as `[0.7, 0.7]` is preserved as an explicit unresolved
range because the selector must respect the synthesis declaration rather than
silently reclassifying variables.

## Execution plan

`OptimizationRunPlan` records:

- route;
- resolution state;
- machine-readable reason code;
- human-readable reason;
- assignments;
- parameter bounds;
- fixed parameters;
- metadata;
- whether an executable contract is required.

The plan can be serialized for CLI output, workflow manifests, and audit logs.

## Architectural significance

The complete route boundary is now explicit:

```text
topology + technology synthesis
        ↓
resolved assignments / unresolved ranges
        ↓
run-plan route selector
        ├── direct_simulation
        └── contract_search
```

This prevents fully resolved assignments from being forced through contract
generation and optimization.

## Next slice

The next layer should connect `OptimizationRunPlan` to
`OptimizationApplicationService` through a plan executor:

```text
direct plan
    → run_direct_assignments(...)

contract-search plan
    → create/resume session
    → run_contract_search_iteration(...)
```

The plan executor should reject missing proposers for contract search and
should preserve the route-selection reason in session and iteration metadata.
