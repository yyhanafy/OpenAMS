# Gate 2 Topology Validation Report

## Summary

- **Gate:** 2
- **Status:** PASS
- **Netlist:** `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/inputs/netlist.spice`
- **Subcircuit:** `two_stage_opamp`
- **Ports:** `inp, inn, out, vdd, vss, vbias`
- **Devices:** 8
- **Nodes:** 9

## Device Coverage

- **Missing:** `None`
- **Unexpected:** `None`

## Checks

```json
{
  "parser_succeeded": true,
  "subcircuit_name_matches": true,
  "ports_match": true,
  "expected_devices_present": true,
  "no_unexpected_devices": true,
  "all_devices_have_terminals": true,
  "m1_connectivity": true,
  "m6_connectivity": true,
  "compensation_capacitor_connectivity": true
}
```

## Exit Criterion

Gate 2 passes when the official named subcircuit is extracted directly from the
reference netlist, its declared ports are preserved in validation evidence, all
seven MOS primitive instances and the compensation capacitor are parsed, and
their structural connectivity matches the reference circuit.
