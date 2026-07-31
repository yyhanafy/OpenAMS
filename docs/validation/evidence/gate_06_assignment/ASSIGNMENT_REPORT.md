# Gate 6 Assignment Validation

- **Status:** PASS
- **Stages:** {'input_pair': 1, 'active_load': 1, 'output_stage': 1, 'full_circuit': 1}
- **Assignments:** 1
- **Route:** `direct_simulation`

## Checks

```json
{
  "four_stages_executed": true,
  "final_region_has_one_row": true,
  "one_assignment_emitted": true,
  "assignment_is_simulation_ready": true,
  "route_is_direct_simulation": true,
  "all_current_errors_within_tolerance": true,
  "width_relation_within_tolerance": true
}
```

## Relation Errors

```json
{
  "M3_vs_M1": 0.0005246905615909153,
  "M5_vs_2M1": 3.01051961568644e-05,
  "M6_vs_M7": 0.013688402190144219,
  "second_stage_width_relation": 0.0
}
```
