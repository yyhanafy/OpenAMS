# Gate 3 Metadata Validation Report

## Summary

- **Gate:** 3
- **Status:** PASS
- **Input directory:** `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/inputs`
- **PyYAML:** `6.0.3`

## Serialization

```json
{
  "specifications_loaded": true,
  "specifications_root_is_mapping": true,
  "design_intent_loaded": true,
  "design_intent_root_is_mapping": true,
  "design_rules_loaded": true,
  "design_rules_root_is_mapping": true,
  "simulation_loaded": true,
  "simulation_root_is_mapping": true
}
```

## Document Root Keys

```json
{
  "specifications": [
    "circuit",
    "conditions",
    "dc_validity",
    "metrics",
    "reporting_targets"
  ],
  "design_intent": [
    "schema_version",
    "circuit_intent",
    "synthesis_parameterization",
    "assignment_synthesis",
    "dependent_derivation_contract"
  ],
  "design_rules": [
    "schema_version",
    "operating_conditions",
    "device_constraints",
    "technology_intersection",
    "assignment_rules",
    "simulation_constraints",
    "active_technology_source",
    "technology_sources",
    "derived_node_domains"
  ],
  "simulation": [
    "deck_template",
    "pdk",
    "backends",
    "analyses",
    "ngspice"
  ]
}
```

## Technology Schema Migration

```json
{
  "performed": false,
  "reason": "not_requested",
  "backup": null
}
```

## Semantic Normalization

- **Error:** `None`

## Normalized Technology

```json
{
  "active_source": "sky130_laygo2_tt_27c",
  "provider": "mos_inverse_table",
  "source": "../../../technology/sky130_laygo2_tt_27c.csv",
  "options": {
    "corner": "tt",
    "temperature_c": 27.0,
    "models": {
      "nmos": "sky130_fd_pr__nfet_01v8_lvt",
      "pmos": "sky130_fd_pr__pfet_01v8"
    }
  }
}
```

## Exit Criterion

Gate 3 passes when all four YAML documents load as mappings and
`normalize_project_inputs()` returns an immutable `ProjectInputs` object using
the current technology metadata schema.
