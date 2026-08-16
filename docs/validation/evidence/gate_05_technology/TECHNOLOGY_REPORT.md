# Gate 5 Technology Validation Report

## Summary

- **Status:** PASS
- **Source:** `/home/yhanafy/AMS-Tutorial/openams/technology/sky130_laygo2_tt_27c.csv`
- **Provider:** `mos_inverse_table`
- **Rows:** 29400

## Checks

```json
{
  "source_exists": true,
  "provider_is_inverse_table": true,
  "row_count_nonzero": true,
  "both_polarities_supported": true,
  "required_quantities_supported": true,
  "nmos_lookup_saturated": true,
  "pmos_lookup_saturated": true,
  "nmos_exact_lookup": true,
  "pmos_exact_lookup": true
}
```

## NMOS Exact Lookup

```json
{
  "model": "sky130_fd_pr__nfet_01v8_lvt",
  "polarity": "nmos",
  "length_m": 1.5e-07,
  "width_m": 1e-06,
  "vgs_v": 0.5,
  "vds_v": 0.15,
  "vbs_v": 0.0,
  "region": "saturation",
  "values": {
    "gds": 1.7375234829101998e-07,
    "gm": 1.994263607900103e-06,
    "vdsat": 0.0482620290659575,
    "id": 8.580433650651198e-08,
    "vth": 0.6367745402287533
  },
  "diagnostics": {
    "lookup_method": "exact_table_match",
    "source": "/home/yhanafy/AMS-Tutorial/openams/technology/sky130_laygo2_tt_27c.csv"
  }
}
```

## PMOS Exact Lookup

```json
{
  "model": "sky130_fd_pr__pfet_01v8",
  "polarity": "pmos",
  "length_m": 1.5e-07,
  "width_m": 2e-06,
  "vgs_v": 0.5,
  "vds_v": 0.15,
  "vbs_v": 0.0,
  "region": "saturation",
  "values": {
    "gds": 7.302683914547651e-08,
    "gm": 5.533114312356013e-07,
    "vdsat": 0.0480366068456485,
    "id": 3.9987452136106135e-08,
    "vth": 0.7502839966488674
  },
  "diagnostics": {
    "lookup_method": "exact_table_match",
    "source": "/home/yhanafy/AMS-Tutorial/openams/technology/sky130_laygo2_tt_27c.csv"
  }
}
```

## Exit Criterion

Gate 5 passes when the active metadata source resolves to the real SKY130 CSV,
the CSV adapter constructs a validated `CharacterizationTable`, and exact
saturated NMOS and PMOS lookups return ID, GM, GDS, VTH, and VDSAT through the
production `TableTechnologyBackend`.
