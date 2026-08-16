# Gate 2 Topology Validation Report

## Summary

- **Gate:** 2
- **Status:** PASS
- **Validator:** `generic_flat_spice_topology`
- **Netlist:** `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/inputs/netlist.spice`
- **Subcircuit:** `two_stage_opamp`
- **Ports:** `inp, inn, out, vdd, vss, vbias`
- **Devices:** 8
- **MOS devices:** 7
- **Nodes:** 9

## Device Coverage

- **Missing:** `None`
- **Unexpected:** `Cc, XM1, XM2, XM3, XM4, XM5, XM6, XM7`

## Checks

```json
{
  "parser_succeeded": true,
  "subcircuit_name_matches": true,
  "subcircuit_has_ports": true,
  "subcircuit_has_devices": true,
  "subcircuit_has_nodes": true,
  "all_devices_have_terminals": true
}
```

## Exit Criterion

Gate 2 passes when the requested named flat-SPICE subcircuit is parsed, its declared ports and devices are preserved, every parsed device has terminal connectivity, and all explicitly supplied expectations are satisfied.
