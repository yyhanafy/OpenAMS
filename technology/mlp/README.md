# SKY130 MOS MLP Models

## Purpose

OpenAMS uses separate continuous MLP surrogate models for SKY130 NMOS and PMOS devices.

The generic runtime interface is:

    src/openams/technology/mlp_oracle.py

The same trained device models are used by all circuit topologies.

## Source technology data

Training starts from:

    technology/sky130_tt_27c_mos_characterization.csv

Dataset metadata:

    technology/sky130_tt_27c_mos_characterization.csv.metadata.json

The dense CSV is stored using Git LFS.

## Canonical training script

    technology/mlp/train_sky130_mos_mlp.py

An older reference implementation is retained at:

    technology/mlp/reference/train_sky130_mlp.py

The reference script is preserved only for reproducibility of the earlier MVP work.

## Trained models

Canonical model files:

    technology/mlp/models/sky130_nmos_mlp.pt
    technology/mlp/models/sky130_pmos_mlp.pt
    technology/mlp/models/training_summary.json

## Runtime use

Witness plans reference the models as:

    mlp:
      nmos_checkpoint: technology/mlp/models/sky130_nmos_mlp.pt
      pmos_checkpoint: technology/mlp/models/sky130_pmos_mlp.pt
      length_um: 0.5

The models are loaded through:

    src/openams/technology/mlp_oracle.py

## Reproducing the models

Create the environment:

    python3 -m venv .venv-openams
    source .venv-openams/bin/activate
    pip install -e .

Inspect the canonical trainer interface:

    python technology/mlp/train_sky130_mos_mlp.py --help

Training starts from:

    technology/sky130_tt_27c_mos_characterization.csv

The generated model checkpoints should be stored under:

    technology/mlp/models/

## Verification

Verify the technology data and trained models with:

    sha256sum -c technology/mlp/SHA256SUMS
