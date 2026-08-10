# Running the OpenAMS Correlated Witness Pipeline

This document summarizes how to generate correlated MLP witnesses and pass them to the generic ngspice validation flow.

## Pipeline

    circuit/design inputs
            |
            v
    independent design space
            |
            v
    topology witness plan
            |
            v
    GENERIC WITNESS ENGINE
            |
            v
        witnesses.csv
            |
            v
    GENERIC NGSPICE VALIDATOR

The witness engine, MLP oracle, and ngspice validator are generic. A topology supplies its own circuit inputs, design space, witness plan, and ngspice configuration.

## Environment

From the OpenAMS repository:

    cd ~/AMS-Tutorial/openams
    source .venv-openams/bin/activate
    export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

Generic implementation:

    src/openams/synthesis/witness_engine.py
    src/openams/technology/mlp_oracle.py
    src/openams/validation/ngspice_witness.py

Wrappers:

    scripts/generate_witnesses.sh
    scripts/validate_witnesses.sh

Canonical MLP models:

    technology/mlp/models/sky130_nmos_mlp.pt
    technology/mlp/models/sky130_pmos_mlp.pt

---

## Two-Stage Op-Amp

Inputs:

    examples/two_stage_opamp/inputs/

Important files:

    netlist.spice
    design_rules.yaml
    design_intent.yaml
    simulation.yaml
    two_stage_mlp_witness_plan.yaml
    deck_template.spice
    ngspice_validation.yaml

Independent design space:

    examples/two_stage_opamp/generated/assignment_synthesis/two_stage_coverage_plan.csv

### Smoke test

    scripts/generate_witnesses.sh \
      examples/two_stage_opamp/inputs/two_stage_mlp_witness_plan.yaml \
      --max-points 5 \
      --output-csv /tmp/two_stage_test.csv

### Full witness generation

    scripts/generate_witnesses.sh \
      examples/two_stage_opamp/inputs/two_stage_mlp_witness_plan.yaml

Default output:

    examples/two_stage_opamp/generated/witnesses.csv

---

## Folded Cascode

Inputs:

    examples/folded_cascode/inputs/

Important files:

    folded_cascode.spice
    design_rules.yaml
    design_intent.yaml
    simulation.yaml
    folded_cascode_mlp_witness_plan.yaml
    deck_template.spice
    ngspice_validation.yaml

Independent design space:

    examples/folded_cascode/generated/assignment_synthesis/folded_cascode_design_space.csv

### Smoke test

    scripts/generate_witnesses.sh \
      examples/folded_cascode/inputs/folded_cascode_mlp_witness_plan.yaml \
      --max-points 5 \
      --output-csv /tmp/folded_test.csv

### Full witness generation

    scripts/generate_witnesses.sh \
      examples/folded_cascode/inputs/folded_cascode_mlp_witness_plan.yaml

Default output:

    examples/folded_cascode/generated/witnesses.csv

---

## Ngspice Validation

Validation uses the generic validator:

    src/openams/validation/ngspice_witness.py

through:

    scripts/validate_witnesses.sh

Each topology supplies:

    deck_template.spice
    ngspice_validation.yaml

The validator itself is topology-independent.

Inspect the wrapper for the exact invocation syntax:

    scripts/validate_witnesses.sh

---

## Adding Another Topology

A new topology should not require a new witness engine.

Provide:

    SPICE/netlist
    design_rules.yaml
    design_intent.yaml
    simulation.yaml
    independent design-space CSV
    <topology>_mlp_witness_plan.yaml
    deck_template.spice
    ngspice_validation.yaml

Then run the same:

    scripts/generate_witnesses.sh <topology_plan.yaml>

The same MLP oracle, witness engine, and ngspice validator are reused.
