# SKY130 MOS Technology Characterization

This directory contains the generator used to create the OpenAMS SKY130 MOS
technology dataset consumed by the MLP training flow.

## Generator

    technology/characterization/characterize_sky130_mlp_dataset.py

The script characterizes the SKY130 1.8-V NMOS and PMOS devices using ngspice
operating-point quantities.

## Requirements

- SKY130 PDK / open_pdks
- ngspice
- Python 3

Set the SKY130 ngspice library path, for example:

    export SKY130_LIB="$HOME/pdks/open_pdks/sky130/sky130A/libs.tech/ngspice/sky130.lib.spice"

## Probe

Verify the PDK/ngspice device-vector interface first:

    python technology/characterization/characterize_sky130_mlp_dataset.py \
        --library "$SKY130_LIB" \
        --corner tt \
        --temperature-c 27 \
        --profile smoke \
        --output /tmp/sky130_mlp_smoke.csv \
        --probe-only

## Dense dataset

Generate the canonical dense OpenAMS dataset:

    python technology/characterization/characterize_sky130_mlp_dataset.py \
        --library "$SKY130_LIB" \
        --corner tt \
        --temperature-c 27 \
        --profile dense \
        --workers 12 \
        --batch-size 128 \
        --output technology/sky130_tt_27c_mos_characterization.csv \
        --resume

The generator also writes:

    technology/sky130_tt_27c_mos_characterization.csv.metadata.json

The dense CSV is stored in Git LFS.

## Next stage

The generated technology dataset is used by:

    technology/mlp/train_sky130_mos_mlp.py

to produce the canonical NMOS and PMOS MLP checkpoints.
