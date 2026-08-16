# OpenAMS Witness Generation Pipeline — Final ngspice Validation

# 53. STEP 14 — Validate Circuit Witnesses with ngspice

## Purpose

The hierarchical witness engine produces a set of complete correlated circuit realizations:

```text
examples/two_stage_opamp/generated/assignment_synthesis/
    hierarchical_witnesses.csv
```

These witnesses have passed:

```text
component-MLP feasibility
        ↓
exact device-MLP realization
        ↓
component interface joining
```

The final validation step independently evaluates those circuit realizations using ngspice.

The purpose is to answer:

> Does the transistor sizing and operating point predicted by OpenAMS correspond to the operating point obtained from an independent SPICE simulation?

The validation flow is:

```text
hierarchical_witnesses.csv
          │
          ▼
select candidate witnesses
          │
          ▼
substitute witness dimensions
into parameterized netlist
          │
          ▼
construct ngspice validation deck
          │
          ▼
DC operating point
          │
          ├── compare internal node voltages
          │
          ├── measure supply current
          │
          └── determine DC PASS/FAIL
          │
          ▼
optional AC analysis
          │
          ├── gain
          ├── 3-dB bandwidth
          ├── UGB
          └── phase margin
          │
          ▼
ngspice_validation.csv
```

The validation implementation is:

```text
src/openams/validation/ngspice_witness.py
```

and the user-facing wrapper is:

```text
scripts/validate_witnesses.sh
```

The wrapper invokes `openams.validation.ngspice_witness` with the selected validation plan.

---

# 54. ngspice Validation Metadata

The two-stage validation plan is:

```text
examples/two_stage_opamp/inputs/ngspice_validation.yaml
```

This is a separate metadata file from:

```text
two_stage_mlp_witness_plan.yaml
```

The distinction is important.

```text
two_stage_mlp_witness_plan.yaml
        │
        └── controls device-MLP witness realization


ngspice_validation.yaml
        │
        └── controls independent SPICE validation
```

---

# 55. Current Two-Stage Validation Plan

The current validation metadata defines:

```yaml
schema_version: 1
name: two_stage_opamp_witness_validation
```

and specifies:

```text
input witness CSV
output validation CSV
source SPICE netlist
witness selection policy
DC tolerance
PDK/corner
simulation constants
netlist parameter bindings
testbench circuit
nodes to compare
AC analysis
measurements
power calculation
```

The current file uses:

```text
temperature = 27 °C
corner      = tt
VDD         = 1.8 V
VIN         = 0.9 V
Cmiller     = 4 pF
Cload       = 10 pF
DC tolerance = 0.05 V
```

and enables an AC sweep from 1 Hz to 1 GHz with 100 points per decade.

---

# 56. Required Cleanup — Update the Witness Input

The current validation plan still contains:

```yaml
input_csv: examples/two_stage_opamp/generated/assignment_synthesis/two_stage_all_2025_mlp_witnesses_full.csv
```

That belongs to the previous witness-generation flow.

For the new hierarchical pipeline, change it to:

```yaml
input_csv: examples/two_stage_opamp/generated/assignment_synthesis/hierarchical_witnesses.csv
```

The output can remain:

```yaml
output_csv: examples/two_stage_opamp/generated/ngspice_validation.csv
```

Therefore the beginning of the cleaned validation plan should be:

```yaml
schema_version: 1
name: two_stage_opamp_witness_validation

input_csv: examples/two_stage_opamp/generated/assignment_synthesis/hierarchical_witnesses.csv
output_csv: examples/two_stage_opamp/generated/ngspice_validation.csv

source_netlist: examples/two_stage_opamp/inputs/netlist.spice
```

This is one of the concrete metadata changes required to align the repository with the latest hierarchical pipeline.

---

# 57. Witness Selection

The validation engine does not necessarily simulate every row immediately.

The plan specifies:

```yaml
status_column: generation_status
status_value: WITNESS

rank_by:
  - max_abs_residual
  - rms_residual

top_n: 100
```

The validator first selects rows satisfying:

```text
generation_status == WITNESS
```

It then sorts them using:

```text
max_abs_residual
rms_residual
```

and selects the first:

```text
top_n = 100
```

unless `--top-n` overrides that value on the command line.

Therefore:

```text
hierarchical_witnesses.csv
          │
          ▼
generation_status == WITNESS
          │
          ▼
sort by residual
          │
          ▼
top 100
          │
          ▼
ngspice
```

This is a **selection policy**, not part of the definition of witness feasibility.

---

# 58. Source-Netlist Parameterization

The validation engine does not construct an unrelated SPICE circuit.

It starts from:

```yaml
source_netlist:
  examples/two_stage_opamp/inputs/netlist.spice
```

and substitutes the selected witness dimensions into that source.

The current bindings are:

```yaml
source_bindings:
  l_default_um: '0.15'

  w_m1_um: w_m1_um
  w_m2_um: w_m1_um

  w_m3_um: w_m3_um
  w_m4_um: w_m3_um

  w_m5_um: w_m5_um
  w_m6_um: w_m6_um
  w_m7_um: w_m7_um

  c_miller: c_miller
```

The validation implementation evaluates these expressions using the witness row plus the constants defined by the plan and renders a temporary source netlist.

This preserves the matching assumptions:

```text
W2 = W1
W4 = W3
```

while using the witness values for:

```text
W1
W3
W5
W6
W7
```

---

# 59. Validation Testbench

The validation plan creates the following testbench around the parameterized two-stage op-amp:

```text
VDD = 1.8 V
VSS = 0 V

VBIAS = witness vbias_v

VINP = 0.9 V DC
VINN = 0.9 V DC

differential AC excitation:
    VINP AC = 0.5
    VINN AC = 0.5 ∠180°

load capacitor:
    CL = 10 pF
```

The instantiated circuit is:

```text
XU1 inp inn out vdd vss vbias two_stage_opamp
```

The validation plan therefore tests each witness under a common electrical environment rather than changing the testbench for each witness.

---

# 60. PDK Selection

The plan contains:

```yaml
pdk:
  library: AUTO
  corner: tt
```

When `library: AUTO` is used, the validator searches for the SKY130 ngspice library.

It first considers `PDK_ROOT` and then common system installation locations.

If it cannot find:

```text
sky130.lib.spice
```

the validator raises:

```text
SKY130 ngspice library not found;
set PDK_ROOT or pdk.library
```



If required, set:

```bash
export PDK_ROOT=/usr/share/pdk
```

or the appropriate SKY130 installation root before running validation.

---

# 61. DC Operating-Point Validation

Every generated validation deck executes:

```text
op
```

before any AC analysis.

The plan compares five circuit voltages:

```text
VBIAS
VTAIL
VX
VY
VOUT
```

against the corresponding OpenAMS witness columns.

The mapping is:

| Circuit quantity | ngspice | Witness column |
|---|---|---|
| VBIAS | `v(vbias)` | `vbias_v` |
| VTAIL | `v(xu1.ntail)` | `vtail_v` |
| VX | `v(xu1.n1)` | `vx_v` |
| VY | `v(xu1.n2)` | `vy_v` |
| VOUT | `v(out)` | `vout_v` |



For each node the output records:

```text
mlp_<node>_v
ng_<node>_v
delta_<node>_v
```

For example:

```text
mlp_vy_v
ng_vy_v
delta_vy_v
```

where conceptually:

```text
delta = Vngspice - VOpenAMS
```

The validator also records:

```text
max_abs_voltage_delta_v
```

across the compared nodes.

---

# 62. DC Tolerance

The current plan specifies:

```yaml
dc_tolerance_v: 0.05
```

Therefore the OpenAMS and ngspice operating points are intended to agree within:

```text
50 mV
```

for the node-voltage validation.

This tolerance is metadata and can therefore be changed without modifying the validation engine.

The result is reported through:

```text
dc_validation_status
```

in the output CSV.

---

# 63. Supply Current and Power

The validation plan measures:

```yaml
measurements:
  supply_current_a:
    ngspice: vdd_src#branch
    absolute: true
```

Therefore:

```text
supply_current_a
    =
| current through VDD source |
```

The plan also declares:

```yaml
power:
  supply_voltage_v: 1.8
  current_measurement: supply_current_a
```

so the validator can report:

```text
power_w
```

using the measured supply current.



---

# 64. AC Characterization

The same validation run can also perform AC characterization.

The current plan enables:

```yaml
ac:
  enabled: true
  output: v(out)

  sweep:
    points_per_decade: 100
    start_hz: 1.0
    stop_hz: 1.0e9

  transfer_sign: -1
```

The validator writes the AC result to a temporary raw file and parses the transfer response.

The output CSV contains:

```text
ac_gain_db
ac_bandwidth_3db_hz
ac_phase_low_frequency_deg
ac_ugb_hz
ac_phase_at_ugb_deg
ac_phase_margin_deg
```

Thus one validation run provides both:

```text
DC witness verification
+
basic AC circuit characterization
```

---

# 65. Run a Small Validation Test

Before validating a large witness set, validate a small number.

The wrapper syntax is:

```bash
scripts/validate_witnesses.sh \
  NGSPICE_PLAN.yaml \
  [additional validator arguments]
```

because the wrapper passes all arguments after the plan directly to `openams.validation.ngspice_witness`.

Run:

```bash
cd ~/AMS-Tutorial/openams
source .venv-openams/bin/activate

scripts/validate_witnesses.sh \
  examples/two_stage_opamp/inputs/ngspice_validation.yaml \
  --top-n 10
```

This validates the ten highest-ranked witnesses selected by the plan.

---

# 66. Validate the Default 100 Witnesses

The validation plan already contains:

```yaml
top_n: 100
```

so the normal command is simply:

```bash
scripts/validate_witnesses.sh \
  examples/two_stage_opamp/inputs/ngspice_validation.yaml
```

Equivalent direct command:

```bash
python -m openams.validation.ngspice_witness \
  --root ~/AMS-Tutorial/openams \
  --plan examples/two_stage_opamp/inputs/ngspice_validation.yaml
```

The wrapper and direct invocation are equivalent.

---

# 67. Override the Output During Testing

The validator supports an output override.

For example:

```bash
scripts/validate_witnesses.sh \
  examples/two_stage_opamp/inputs/ngspice_validation.yaml \
  --top-n 10 \
  --output-csv /tmp/two_stage_ngspice_smoke.csv
```

This is useful for regression testing because it avoids replacing the production validation file.

---

# 68. Validation Output

With the current metadata, the production result is:

```text
examples/two_stage_opamp/generated/
    ngspice_validation.csv
```

The validator explicitly constructs columns for:

```text
selection_rank
point_index
witness_rank

ngspice_rc
ngspice_elapsed_s

OpenAMS node voltages
ngspice node voltages
voltage differences

supply_current_a
power_w

max_abs_voltage_delta_v
dc_validation_status

ac_gain_db
ac_bandwidth_3db_hz
ac_phase_low_frequency_deg
ac_ugb_hz
ac_phase_at_ugb_deg
ac_phase_margin_deg

validation_status
```



---

# 69. Inspect the Validation Results

After the run:

```bash
head -5 \
examples/two_stage_opamp/generated/ngspice_validation.csv
```

A useful summary is:

```bash
python - <<'PY'
import pandas as pd

p = "examples/two_stage_opamp/generated/ngspice_validation.csv"
d = pd.read_csv(p)

print("rows:", len(d))

print("\nvalidation_status")
print(d["validation_status"].value_counts(dropna=False))

print("\ndc_validation_status")
print(d["dc_validation_status"].value_counts(dropna=False))

print("\nmaximum DC discrepancy:")
print(d["max_abs_voltage_delta_v"].max())

print("\nmedian DC discrepancy:")
print(d["max_abs_voltage_delta_v"].median())
PY
```

This provides a quick check of how well the OpenAMS operating-point predictions agree with ngspice.

---

# 70. Definition of the Final Valid Witness Pool

The validation CSV is a validation report.

It is useful to distinguish that from the actual final witness pool.

Conceptually:

```text
hierarchical_witnesses.csv
          │
          ├────────── witness dimensions
          │
          ▼
ngspice_validation.csv
          │
          ├────────── validation_status
          │
          ▼
filter PASS witnesses
          │
          ▼
valid_circuit_witnesses.csv
```

The final valid witness pool should preserve the **original complete hierarchical witness row**, not merely the validation metrics.

This means the final cleanup should provide a simple deterministic join using:

```text
point_index
witness_rank
```

between:

```text
hierarchical_witnesses.csv
```

and:

```text
ngspice_validation.csv
```

and retain only the accepted validation rows.

---

# 71. Current Pipeline Boundary

At this point the complete OpenAMS witness-generation process is:

```text
netlist.spice
      │
      ▼
topology extraction
      │
      ▼
metadata normalization
      │
      ▼
constraint compilation
      │
      ▼
independent design space
      │
      ▼
topology partition
      │
      ▼
component teacher datasets
      │
      ▼
component MLP training
      │
      ▼
component MLP validation
      │
      ▼
hierarchical contract
      │
      ▼
hierarchical MLP search
      │
      ▼
exact device realization
      │
      ▼
component witness join
      │
      ▼
hierarchical_witnesses.csv
      │
      ▼
ngspice DC/AC validation
      │
      ▼
VALID CIRCUIT WITNESSES
```

The valid circuit witness set is the appropriate handoff to the next OpenAMS phase:

```text
valid witnesses
      │
      ▼
large-scale SPICE characterization
      │
      ▼
pre-layout circuit-performance dataset
      │
      ▼
circuit-level MLP
      │
      ▼
optimization / physical design
```

---

# 72. Metadata Summary

The complete pipeline now depends on a relatively small set of human-readable metadata.

| Metadata | Main purpose |
|---|---|
| `netlist.spice` | Circuit topology and parameterized transistor definitions |
| `specs.yaml` | Desired circuit-level performance |
| `design_rules.yaml` | Electrical/design constraints |
| `design_intent.yaml` | Independent variables, dependencies, component partition and hierarchical interfaces |
| `simulation.yaml` | General simulation configuration |
| `two_stage_mlp_witness_plan.yaml` | Device-MLP exact-realization/search configuration |
| `ngspice_validation.yaml` | Independent SPICE validation and characterization configuration |
| `hierarchical_component_contract.json` | Generated executable hierarchical-search contract |

Only the first seven are source/input metadata.

```text
hierarchical_component_contract.json
```

is generated from the design intent and should not normally be edited manually.

---

# 73. Final Important Cleanup Item

The existing `ngspice_validation.yaml` is structurally suitable for the new pipeline, but its input still points to:

```text
two_stage_all_2025_mlp_witnesses_full.csv
```

rather than:

```text
hierarchical_witnesses.csv
```

That should be corrected when the hierarchical pipeline is promoted to the canonical production path.

The second cleanup item is to add an explicit final filtering/join step that creates:

```text
valid_circuit_witnesses.csv
```

from the hierarchical witness table and the ngspice validation result.

That gives OpenAMS one unambiguous final artifact:

> **A table of complete correlated circuit witnesses that have also passed independent ngspice validation.**