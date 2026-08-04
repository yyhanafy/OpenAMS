# Gate 5 Technology Validation Report

## Summary

- **Status:** PASS
- **Source:** `/home/yhanafy/AMS-Tutorial/openams/technology/sky130_tt_27c_inverse_smoke.csv`
- **Provider:** `mos_inverse_table`
- **Rows:** 3024

## Checks

```json
{
  "source_exists": true,
  "provider_is_inverse_table": true,
  "row_count_is_3024": true,
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
  "model": "sky130_fd_pr__nfet_01v8",
  "polarity": "nmos",
  "length_m": 5e-07,
  "width_m": 4.1999999999999995e-07,
  "vgs_v": 0.5,
  "vds_v": 0.15,
  "vbs_v": 0.0,
  "region": "saturation",
  "values": {
    "vth": 0.615506,
    "vdsat": 0.0432843,
    "id": 1.44188e-08,
    "gm": 3.24205e-07,
    "gds": 7.92464e-09
  },
  "diagnostics": {
    "lookup_method": "exact_table_match",
    "source": "/home/yhanafy/AMS-Tutorial/openams/technology/sky130_tt_27c_inverse_smoke.csv"
  }
}
```

## PMOS Exact Lookup

```json
{
  "model": "sky130_fd_pr__pfet_01v8",
  "polarity": "pmos",
  "length_m": 5e-07,
  "width_m": 4.1999999999999995e-07,
  "vgs_v": 0.5,
  "vds_v": 0.15,
  "vbs_v": 0.0,
  "region": "saturation",
  "values": {
    "vth": 0.881583,
    "vdsat": 0.0430148,
    "id": 1.55149e-10,
    "gm": 3.49228e-09,
    "gds": 5.74576e-11
  },
  "diagnostics": {
    "lookup_method": "exact_table_match",
    "source": "/home/yhanafy/AMS-Tutorial/openams/technology/sky130_tt_27c_inverse_smoke.csv"
  }
}
```

## Exit Criterion

Gate 5 passes when the active metadata source resolves to the real SKY130 CSV,
the CSV adapter constructs a validated `CharacterizationTable`, and exact
saturated NMOS and PMOS lookups return ID, GM, GDS, VTH, and VDSAT through the
production `TableTechnologyBackend`.
