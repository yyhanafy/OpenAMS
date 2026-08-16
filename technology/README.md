# Technology Assets

The production witness engine consumes trained NMOS/PMOS MLP checkpoints.  Reproducibility additionally requires the characterized technology dataset and the scripts that generated/trained it.

Expected canonical assets:

```text
technology/sky130_tt_27c_mos_characterization.csv
technology/sky130_tt_27c_mos_characterization.csv.metadata.json
technology/train_sky130_mos_mlp.py
runtime/mlp_models/sky130_nmos_mlp.pt
runtime/mlp_models/sky130_pmos_mlp.pt
runtime/mlp_models/training_summary.json
```

The uploaded review snapshot did **not** contain the dense CSV or a verified technology-table generator.  Therefore this bundle intentionally does not invent either.  Use `scripts/import_technology_assets.sh /path/to/current/openams` to copy the actual dataset and preserve the July-30 training references from the working repository.
