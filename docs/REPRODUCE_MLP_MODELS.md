# Reproducing the OpenAMS SKY130 MLP Models

This document summarizes the complete reproducibility path from SKY130/ngspice characterization to the MLP models used by the OpenAMS witness engine.

## Pipeline

    SKY130 PDK + ngspice
            |
            v
    MOS CHARACTERIZATION
            |
            v
    dense technology CSV
            |
            v
       MLP TRAINING
            |
       +----+----+
       |         |
       v         v
      NMOS      PMOS
       MLP       MLP
       +----+----+
            |
            v
         MlpOracle
            |
            v
    generic witness engine

---

## 1. Environment

From the OpenAMS repository:

    cd ~/AMS-Tutorial/openams
    source .venv-openams/bin/activate
    export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

Install the Python package if necessary:

    pip install -e .

ngspice and the SKY130 PDK must also be installed.

---

## 2. Generate the Technology Dataset

Characterization generator:

    technology/characterization/characterize_sky130_mlp_dataset.py

Set the SKY130 ngspice library path, for example:

    export SKY130_LIB="$HOME/pdks/open_pdks/sky130/sky130A/libs.tech/ngspice/sky130.lib.spice"

### Probe the installation

    python technology/characterization/characterize_sky130_mlp_dataset.py \
      --library "$SKY130_LIB" \
      --corner tt \
      --temperature-c 27 \
      --profile smoke \
      --output /tmp/sky130_mlp_smoke.csv \
      --probe-only

### Generate the canonical dense dataset

    python technology/characterization/characterize_sky130_mlp_dataset.py \
      --library "$SKY130_LIB" \
      --corner tt \
      --temperature-c 27 \
      --profile dense \
      --workers 12 \
      --batch-size 128 \
      --output technology/sky130_tt_27c_mlp_dense.csv \
      --resume

Outputs:

    technology/sky130_tt_27c_mlp_dense.csv
    technology/sky130_tt_27c_mlp_dense.csv.metadata.json

The large CSV is stored in Git LFS.

---

## 3. Train the MLP Models

Canonical trainer:

    technology/mlp/train_sky130_mos_mlp.py

The trainer provides:

    train
    evaluate
    predict
    inspect

Inspect the training interface with:

    python technology/mlp/train_sky130_mos_mlp.py train --help

### Train both NMOS and PMOS models

The required arguments are the technology CSV and output directory:

    python technology/mlp/train_sky130_mos_mlp.py train \
      --csv technology/sky130_tt_27c_mlp_dense.csv \
      --output-dir technology/mlp/models

The trainer also supports explicit control of:

    --polarities
    --targets
    --hidden-dims
    --activation
    --dropout
    --epochs
    --batch-size
    --learning-rate
    --weight-decay
    --patience
    --min-delta
    --grad-clip
    --validation-fraction
    --test-fraction
    --seed
    --report-every
    --device

Use explicit values for these options when exact training-run reproducibility is required.

Canonical reference outputs:

    technology/mlp/models/sky130_nmos_mlp.pt
    technology/mlp/models/sky130_pmos_mlp.pt
    technology/mlp/models/training_summary.json

---

## 4. Verify the Stored Reference Assets

Reference checksums are stored in:

    technology/mlp/SHA256SUMS

Verify them with:

    sha256sum -c technology/mlp/SHA256SUMS

The stored technology dataset, metadata, models, and training summary should report OK.

---

## 5. Runtime Use

Generic MLP interface:

    src/openams/technology/mlp_oracle.py

Witness plans reference the models as:

    mlp:
      nmos_checkpoint: technology/mlp/models/sky130_nmos_mlp.pt
      pmos_checkpoint: technology/mlp/models/sky130_pmos_mlp.pt
      length_um: 0.5

These are technology-level models, not topology-specific models.

The same NMOS and PMOS models are therefore used by the two-stage op-amp, folded cascode, and future SKY130 topologies operating inside the trained model domain.

---

## Reproducibility Summary

The repository preserves:

    characterization generator
            |
            v
    dense SKY130 technology dataset
            |
            v
    dataset metadata
            |
            v
    canonical MLP trainer
            |
            v
    NMOS + PMOS reference checkpoints
            |
            v
    training summary
            |
            v
    SHA256 checksums
            |
            v
    generic OpenAMS MlpOracle

This provides a reproducible path from the SKY130 PDK and ngspice to the device models used by OpenAMS.
