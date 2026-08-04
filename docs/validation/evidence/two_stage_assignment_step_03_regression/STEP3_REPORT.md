# Assignment Synthesis Step 3 Report

## Status

**PASS**

- **Mode:** `two_stage_regression`
- **Circuit:** `two_stage_opamp`
- **Independent variables:** 3

## Independent Domains

```json
{
  "i_m5_a": {
    "kind": "current",
    "device": "M5",
    "domain_type": "technology_supported_point_set",
    "design_intent_minimum": 1e-05,
    "design_intent_maximum": 0.0001,
    "technology_minimum": 1.00164e-05,
    "technology_maximum": 8.33163e-05,
    "candidate_count": 81,
    "supporting_row_count": 81,
    "source_node": null,
    "source_voltage_v": null,
    "device_terminal": null,
    "nf_min": null,
    "nf_max": null,
    "finger_width_min_um": null,
    "finger_width_max_um": null
  },
  "w_m1_um": {
    "kind": "total_width",
    "device": "M1",
    "domain_type": "technology_realizable_continuous_total_width",
    "design_intent_minimum": 1.0,
    "design_intent_maximum": 100.0,
    "technology_minimum": 1.0,
    "technology_maximum": 100.0,
    "candidate_count": 0,
    "supporting_row_count": null,
    "source_node": null,
    "source_voltage_v": null,
    "device_terminal": null,
    "nf_min": 1,
    "nf_max": 1,
    "finger_width_min_um": 0.42,
    "finger_width_max_um": 100.0
  },
  "vout_v": {
    "kind": "node_voltage",
    "device": null,
    "domain_type": "technology_supported_continuous_interval",
    "design_intent_minimum": 0.5,
    "design_intent_maximum": 1.6,
    "technology_minimum": 0.6,
    "technology_maximum": 1.5,
    "candidate_count": 0,
    "supporting_row_count": null,
    "source_node": null,
    "source_voltage_v": null,
    "device_terminal": null,
    "nf_min": null,
    "nf_max": null,
    "finger_width_min_um": null,
    "finger_width_max_um": null
  }
}
```

## Per-Variable Checks

```json
{
  "i_m5_a": {
    "domain_present": true,
    "kind_matches": true,
    "declared_bounds_valid": true,
    "technology_support_valid": true,
    "technology_provenance_present": true
  },
  "w_m1_um": {
    "domain_present": true,
    "kind_matches": true,
    "declared_bounds_valid": true,
    "technology_support_valid": true,
    "technology_provenance_present": true
  },
  "vout_v": {
    "domain_present": true,
    "kind_matches": true,
    "declared_bounds_valid": true,
    "technology_support_valid": true,
    "technology_provenance_present": true
  }
}
```

## Global Checks

```json
{
  "status_pass": true,
  "declared_variables_present": true,
  "all_variable_checks_pass": true,
  "next_stage_correct": true,
  "two_stage_variable_set_matches": true,
  "two_stage_current_domain_nonempty": true,
  "two_stage_width_nf_realizable": true,
  "two_stage_vout_continuous": true
}
```

## Meaning

- Every independent variable declared in the compiled model must have a generated technology-backed domain.
- Point-set domains must contain at least one candidate.
- Continuous node-voltage domains must have a nonempty technology-supported interval.
- Total-width domains must have at least one legal integer-finger realization.
- Bias-voltage domains are absolute terminal-voltage domains derived from device technology data and resolved source voltage.
- No dependent circuit quantity is derived in Step 3.
