# Gate 4B Constraint Compiler Report

## Summary

- **Status:** PASS
- **Input constraints:** 5
- **Compiled constraints:** 5
- **Diagnostics:** 5
- **Retained rows:** 2

## Checks

```json
{
  "five_constraints_loaded": true,
  "five_constraints_compiled": true,
  "five_diagnostics_emitted": true,
  "all_diagnostics_compiled": true,
  "two_expected_rows_retained": true,
  "retained_rows_match_expected": true,
  "invalid_rows_rejected": true
}
```

## Retained Current Combinations

```json
[
  {
    "M1": 2e-05,
    "M2": 2e-05,
    "M3": 2e-05,
    "M4": 2e-05,
    "M5": 4e-05,
    "M6": 1e-05,
    "M7": 1e-05
  },
  {
    "M1": 3e-05,
    "M2": 3e-05,
    "M3": 3e-05,
    "M4": 3e-05,
    "M5": 6e-05,
    "M6": 1e-05,
    "M7": 1e-05
  }
]
```

## Compiler Classes

```json
[
  "FieldRelationConstraint",
  "FieldRelationConstraint",
  "FieldRelationConstraint",
  "FieldRelationConstraint",
  "FieldRelationConstraint"
]
```

## Exit Criterion

Gate 4B passes when all five canonical constraints generated from the official
two-stage design intent compile through `CircuitConstraintCompiler`, every
diagnostic reports `compiled`, and execution retains exactly the two intended
current combinations while rejecting all deliberately invalid candidate rows.
