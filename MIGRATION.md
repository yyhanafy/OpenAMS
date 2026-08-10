# Migration from the Current Snapshot

## 1. Freeze the current pipeline

Before changing the working repository, create a timestamped archive containing the current source, tools, circuit inputs, technology/model artifacts, and known-good witness/validation outputs.

The uploaded review snapshot has also been preserved separately as `openams_pipeline_archive_20260810.tar.gz`.

## 2. Install the clean overlay

Copy the contents of this bundle into a clean branch/worktree.  Do **not** remove the existing frontend yet.  The existing frontend supplies the compiled design and independent design-space CSV.

## 3. Copy technology data missing from the review tarball

The review tarball did not contain:

```text
technology/sky130_tt_27c_mlp_dense.csv
MVP_archive_July_30/technology/train_sky130_mos_mlp.py
MVP_archive_July_30/tools/technology/train_sky130_mlp.py
```

Copy those exact files from the working repository/archive if they exist.  Also locate and preserve the actual technology-table generation script that produced `sky130_tt_27c_mlp_dense.csv`; its canonical filename could not be verified from the uploaded snapshot.

## 4. Regression order

1. Run the clean witness engine on a handful of two-stage points.
2. Compare schema and numerical behavior with `archive_manifest/two_stage_all_2025_mlp_witnesses.csv`.
3. Run the clean engine on folded cascode and compare with `archive_manifest/folded_cascode_all_2025_generic_mlp_witnesses.csv`.
4. Validate selected witnesses with the generic ngspice validator.
5. Only after these pass, archive the specialized scripts.

## 5. Archive candidates after equivalence

Examples include the `generate_two_stage_correlated_ranges*`, `generate_two_stage_sampled_*`, `generate_two_stage_mlp_*brent*`, debug-engine versions, and versioned topology-specific ngspice validators.  Keep the specialized all-2025 two-stage generator as a reference until generic equivalence has been demonstrated.
