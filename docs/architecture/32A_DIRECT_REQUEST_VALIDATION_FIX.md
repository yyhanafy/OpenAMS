# Direct-assignment request validation fix

## Problem

`DirectAssignmentProposer` owns the fully resolved assignment values. A direct
simulation request may therefore legitimately have neither unresolved bounds
nor shared fixed parameters.

The previous generic validation rejected that valid shape before the proposer
could emit its assignments.

## Correct route-specific invariant

```text
direct_simulation
    parameter_bounds must be empty
    fixed_parameters may be empty
    concrete values may be supplied by DirectAssignmentProposer

contract_search
    parameter_bounds must be non-empty
```

This keeps the direct-assignment bypass intact while preserving strict
contract-search validation.
