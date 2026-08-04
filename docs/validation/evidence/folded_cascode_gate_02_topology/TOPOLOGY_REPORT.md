# Gate 2 Topology Validation Report

## Summary

- **Gate:** 2
- **Status:** PASS
- **Validator:** `generic_flat_spice_topology`
- **Netlist:** `examples/folded_cascode/inputs/folded_cascode.spice`
- **Subcircuit:** `folded_cascode_ota`
- **Ports:** `vip, vin, vout, vdd, vss`
- **Devices:** 16
- **MOS devices:** 11
- **Nodes:** 15

## Device Coverage

- **Missing:** `None`
- **Unexpected:** `None`

## Checks

```json
{
  "parser_succeeded": true,
  "subcircuit_name_matches": true,
  "subcircuit_has_ports": true,
  "subcircuit_has_devices": true,
  "subcircuit_has_nodes": true,
  "all_devices_have_terminals": true,
  "ports_match": true,
  "expected_devices_present": true,
  "no_unexpected_devices": true,
  "device_count_matches": true,
  "mos_count_matches": true
}
```

## Exit Criterion

Gate 2 passes when the requested named flat-SPICE subcircuit is parsed, its declared ports and devices are preserved, every parsed device has terminal connectivity, and all explicitly supplied expectations are satisfied.
