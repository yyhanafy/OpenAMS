# Gate 4B Constraint Compiler Report

## Summary

- **Status:** PASS
- **Mode:** `generic`
- **Input constraints:** 10
- **Compiled constraints:** 10
- **Diagnostics:** 10
- **Discovered devices:** M1, M2, M3, M4, M5, M6, M7, M8, M9, M10, M11
- **Retained rows:** 1

## Checks

```json
{
  "constraints_loaded": true,
  "all_constraints_compiled": true,
  "diagnostic_count_matches": true,
  "all_diagnostics_compiled": true,
  "all_canonical_devices_bound": true,
  "execution_completed": true,
  "at_least_one_row_retained": true
}
```

## Exit Criterion

Generic mode passes when all supplied canonical constraints compile, all discovered current variables are bound, every diagnostic reports `compiled`, execution completes, and at least one representative row is retained. Two-stage regression mode additionally checks the exact historical retained rows.
