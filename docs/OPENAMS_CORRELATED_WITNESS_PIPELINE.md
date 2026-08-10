# OpenAMS Correlated-Witness Pipeline

## Purpose

This document defines the target OpenAMS pipeline that starts from the
circuit description and design metadata, uses the SKY130 technology data
and trained MLP device models to generate **correlated DC witnesses**,
and ends with a witness CSV ready for ngspice verification.

The main principle is:

> The technology model determines device feasibility; the compiled
> circuit/design determines how device solutions are connected; the
> witness engine finds complete correlated operating points; ngspice
> verifies them.

## Main Pipeline

``` text
                         OPENAMS FRONTEND
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
       SPICE             design_rules.yaml    design_intent.yaml
   simulation.yaml             etc.           witness/design plan
          │                    │                    │
          └────────────────────┴────────────────────┘
                               │
                               ▼
                    compiled circuit/design
                               │
                               ▼
                   independent design space
                               │
                               ▼
                  correlated MLP witness plan
                               │
                               ▼
                   GENERIC WITNESS ENGINE
                               │
                               ▼
                         witnesses.csv
                               │
                               ▼
                    GENERIC NGSPICE VALIDATOR
```

### Pipeline stages

1.  **OpenAMS frontend**\
    Reads the SPICE netlist and YAML design files, extracts the
    topology, normalizes the project inputs, compiles the design rules
    and intent, and determines the independent design variables and
    constraints.

2.  **Independent design space**\
    Generates the independent circuit points that must be explored. The
    exact independent quantities are circuit-dependent and are declared
    by the design metadata/plan rather than hard-coded into the witness
    engine.

3.  **Correlated MLP witness plan**\
    Describes how the independent point is expanded into a complete
    operating point: device stages, shared-node relationships,
    current/width relationships, saturation constraints, candidate
    selection, residual calculations, and final witness fields.

4.  **Generic witness engine**\
    Executes the witness plan using the trained NMOS/PMOS MLP models. It
    joins device solutions through their shared electrical quantities
    and retains complete mutually compatible paths rather than unrelated
    per-node voltage ranges.

5.  **`witnesses.csv`**\
    Each output row is a complete proposed DC operating point containing
    the independent quantities and the required derived widths,
    currents, bias voltages, node voltages, residuals, and feasibility
    information.

6.  **Generic ngspice validator**\
    Instantiates a witness in the original circuit, runs ngspice,
    compares the predicted DC operating point against `.op`, and then
    performs the required AC/transient/specification verification.

------------------------------------------------------------------------

## Target Source Organization

The current experimental implementation should be consolidated toward
the following production structure:

``` text
src/openams/
    ...
    synthesis/
        witness_engine.py

    technology/
        mlp_oracle.py

    validation/
        ngspice_witness.py
```

### Responsibilities

-   `synthesis/witness_engine.py`\
    Generic execution of the correlated witness plan. It must not
    contain two-stage-op-amp or folded-cascode-specific topology logic.

-   `technology/mlp_oracle.py`\
    Generic interface to the trained MOS MLP models, including batched
    device evaluation and model-domain checks.

-   `validation/ngspice_witness.py`\
    Generic witness-to-ngspice verification infrastructure.
    Circuit-specific node/device mapping should be supplied through
    configuration rather than hard-coded validator families.

------------------------------------------------------------------------

## Circuit Inputs

### Two-stage op amp

``` text
examples/two_stage_opamp/inputs/
    netlist.spice
    design_rules.yaml
    design_intent.yaml
    simulation.yaml
    two_stage_mlp_witness_plan.yaml
```

The exact SPICE filename may follow the existing example naming
convention; `netlist.spice` above denotes the circuit's top-level SPICE
input.

### Folded cascode

``` text
examples/folded_cascode/inputs/
    folded_cascode.spice
    design_rules.yaml
    design_intent.yaml
    simulation.yaml
    folded_cascode_mlp_witness_plan.yaml
```

The two circuits use the same generic witness engine. Their
topology-specific search sequence and equations belong in their
witness-plan YAML files.

------------------------------------------------------------------------

## Technology Data and MLP Model Generation

The witness pipeline depends on a SKY130 MOS technology dataset and
trained NMOS/PMOS MLP models.

The technology-data path should be documented as a separate upstream
preparation stage:

``` text
SKY130 / ngspice device characterization
                │
                ▼
technology-table generation script(s)
                │
                ▼
technology/sky130_tt_27c_mlp_dense.csv
                │
                ▼
MOS MLP training script
                │
                ▼
sky130_nmos_mlp.pt
sky130_pmos_mlp.pt
                │
                ▼
OpenAMS MLP oracle
```

### Technology dataset

Current dense technology dataset used by the recent pipeline:

``` text
technology/
    sky130_tt_27c_mlp_dense.csv
    sky130_tt_27c_mlp_dense.csv.metadata.json
```

The CSV is the characterized MOS dataset from which the MLP training
data are obtained. The metadata file records information associated with
that dataset.

The exact canonical technology-table generation script still needs to be
frozen during cleanup. It should be kept alongside the technology
preparation flow and documented as the reproducible producer of
`sky130_tt_27c_mlp_dense.csv`.

------------------------------------------------------------------------

## MLP Training

The snapshot contains the current training entry point:

``` text
technology/
    train_sky130_mos_mlp.py
```

Historical MVP training artifacts/scripts that should be retained until
the training flow is consolidated are:

``` text
MVP_archive_July_30/
    runtime/
        mlp_validation/
            sky130_pmos_mlp.pt
            sky130_nmos_mlp.pt

    technology/
        train_sky130_mos_mlp.py

    tools/
        technology/
            train_sky130_mlp.py
```

The current pipeline snapshot also contains trained dense-model
artifacts under:

``` text
runtime/
    mlp_dense_validation/
        sky130_pmos_mlp.pt
        sky130_nmos_mlp.pt
        training_summary.json
```

The cleanup goal is to retain **one canonical MLP-training command** and
**one canonical model-output location**, while preserving the older MVP
scripts/models as reference until equivalence is established.

------------------------------------------------------------------------

## Target Repository View

After cleanup, the important pipeline files should be easy to identify:

``` text
technology/
    <technology_table_generator>.py
    sky130_tt_27c_mlp_dense.csv
    sky130_tt_27c_mlp_dense.csv.metadata.json
    train_sky130_mos_mlp.py

runtime/
    mlp_dense_validation/
        sky130_nmos_mlp.pt
        sky130_pmos_mlp.pt
        training_summary.json

src/openams/
    synthesis/
        witness_engine.py
    technology/
        mlp_oracle.py
    validation/
        ngspice_witness.py

examples/
    two_stage_opamp/
        inputs/
            <top-level netlist>.spice
            design_rules.yaml
            design_intent.yaml
            simulation.yaml
            two_stage_mlp_witness_plan.yaml

    folded_cascode/
        inputs/
            folded_cascode.spice
            design_rules.yaml
            design_intent.yaml
            simulation.yaml
            folded_cascode_mlp_witness_plan.yaml
```

## Final Interface

The intended boundary between synthesis and simulation is:

``` text
compiled design
      +
independent point
      +
trained technology MLP
      +
correlated witness plan
          │
          ▼
    witness_engine
          │
          ▼
     witnesses.csv
          │
          ▼
  ngspice_witness
```

A row in `witnesses.csv` must represent **one complete correlated
candidate operating point**, not an arbitrary combination of
independently computed node-voltage ranges.

This CSV is the canonical handoff from OpenAMS witness synthesis to
circuit-level ngspice verification.
