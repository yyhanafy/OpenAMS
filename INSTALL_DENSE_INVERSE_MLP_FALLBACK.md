# OpenAMS Dense Inverse + Targeted MLP Fallback

This patch adds:

1. `--technology-csv` override for generic Step 5.
2. Dense inverse-feasible lookup as the primary provider.
3. Exact-request MLP fallback only after an inverse-table miss.
4. A persistent adaptive cache separate from the canonical dense CSV.
5. Provider hit/fallback/cache statistics in `complete_assignments.json`.

## Install

```bash
cd ~/AMS-Tutorial/openams

cp -a src/openams/synthesis/generic_complete_step5.py \
  src/openams/synthesis/generic_complete_step5.py.before_dense_inverse_fallback
cp -a src/openams/synthesis/inverse_feasible_provider.py \
  src/openams/synthesis/inverse_feasible_provider.py.before_dense_inverse_fallback
cp -a tools/validation/validate_assignment_step_05_complete_assignments.py \
  tools/validation/validate_assignment_step_05_complete_assignments.py.before_dense_inverse_fallback

tar -xzf ~/Downloads/openams_dense_inverse_mlp_fallback_v1.tgz

export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
python -m py_compile \
  src/openams/synthesis/inverse_feasible_provider.py \
  src/openams/synthesis/mlp_step5_provider.py \
  src/openams/synthesis/generic_complete_step5.py \
  tools/validation/validate_assignment_step_05_complete_assignments.py

pytest -q \
  tests/synthesis/test_inverse_feasible_provider.py \
  tests/synthesis/test_generic_complete_step5.py \
  tests/synthesis/test_complete_assignments.py
```

## Required MLP environment

Use the same trained checkpoints used by the two-stage scan:

```bash
export OPENAMS_MLP_NMOS=/absolute/path/to/nmos_checkpoint.pt
export OPENAMS_MLP_PMOS=/absolute/path/to/pmos_checkpoint.pt
```

## First smoke: dense inverse only

This checks whether the dense dataset alone resolves the characterized widths.

```bash
rm -rf runtime/folded_inverse_dense_only_smoke

python tools/validation/validate_assignment_step_05_complete_assignments.py \
  --compiled-model examples/folded_cascode/generated/compiled_circuit_model.json \
  --independent-regions examples/folded_cascode/generated/assignment_synthesis/independent_regions.json \
  --dependent-regions examples/folded_cascode/generated/assignment_synthesis/dependent_regions.json \
  --output-json runtime/folded_inverse_dense_only_smoke/complete_assignments.json \
  --output-csv runtime/folded_inverse_dense_only_smoke/complete_assignments.csv \
  --report runtime/folded_inverse_dense_only_smoke/REPORT.md \
  --mode generic \
  --provider inverse \
  --technology-csv technology/sky130_tt_27c_mlp_dense.csv \
  --continuous-samples w_m1_um=3 \
  --range w_m1_um=40:50 \
  --max-device-candidates 16 \
  --max-group-choices 32 \
  --max-solutions-per-point 32
```

## Second smoke: dense inverse plus MLP fallback

```bash
rm -rf runtime/folded_inverse_mlp_fallback_smoke
mkdir -p runtime/folded_inverse_mlp_fallback_smoke

python tools/validation/validate_assignment_step_05_complete_assignments.py \
  --compiled-model examples/folded_cascode/generated/compiled_circuit_model.json \
  --independent-regions examples/folded_cascode/generated/assignment_synthesis/independent_regions.json \
  --dependent-regions examples/folded_cascode/generated/assignment_synthesis/dependent_regions.json \
  --output-json runtime/folded_inverse_mlp_fallback_smoke/complete_assignments.json \
  --output-csv runtime/folded_inverse_mlp_fallback_smoke/complete_assignments.csv \
  --report runtime/folded_inverse_mlp_fallback_smoke/REPORT.md \
  --mode generic \
  --provider inverse \
  --technology-csv technology/sky130_tt_27c_mlp_dense.csv \
  --mlp-fallback \
  --adaptive-cache runtime/folded_inverse_mlp_fallback_smoke/adaptive_inverse_cache.csv \
  --continuous-samples w_m1_um=3 \
  --range w_m1_um=41.8333333333:50 \
  --max-device-candidates 16 \
  --max-group-choices 32 \
  --max-solutions-per-point 32
```

## Inspect provider statistics

```bash
python - <<'PY'
import json
from pathlib import Path
p = Path("runtime/folded_inverse_mlp_fallback_smoke/complete_assignments.json")
d = json.loads(p.read_text())
for key in (
    "technology_source",
    "technology_provider_query_count",
    "technology_provider_primary_hit_count",
    "technology_provider_cache_hit_count",
    "technology_provider_fallback_request_count",
    "technology_provider_fallback_query_count",
    "technology_provider_fallback_result_count",
    "adaptive_cache_path",
    "complete_assignment_count",
    "rejected_combination_count",
):
    print(f"{key}: {d.get(key)}")
print("rejections:", d.get("rejection_counts"))
PY
```

## Full 14,175-point run

Run only after the smoke produces sensible provider statistics and at least reaches later groups:

```bash
rm -rf examples/folded_cascode/generated/assignment_synthesis/complete_assignments_inverse_mlp
mkdir -p examples/folded_cascode/generated/assignment_synthesis/complete_assignments_inverse_mlp

python tools/validation/validate_assignment_step_05_complete_assignments.py \
  --compiled-model examples/folded_cascode/generated/compiled_circuit_model.json \
  --independent-regions examples/folded_cascode/generated/assignment_synthesis/independent_regions.json \
  --dependent-regions examples/folded_cascode/generated/assignment_synthesis/dependent_regions.json \
  --output-json examples/folded_cascode/generated/assignment_synthesis/complete_assignments_inverse_mlp/complete_assignments.json \
  --output-csv examples/folded_cascode/generated/assignment_synthesis/complete_assignments_inverse_mlp/complete_assignments.csv \
  --report examples/folded_cascode/generated/assignment_synthesis/complete_assignments_inverse_mlp/REPORT.md \
  --mode generic \
  --provider inverse \
  --technology-csv technology/sky130_tt_27c_mlp_dense.csv \
  --mlp-fallback \
  --adaptive-cache examples/folded_cascode/generated/assignment_synthesis/complete_assignments_inverse_mlp/adaptive_inverse_cache.csv \
  --continuous-samples w_m1_um=25 \
  --range w_m1_um=1:50 \
  --max-device-candidates 16 \
  --max-group-choices 32 \
  --max-solutions-per-point 32
```

The canonical dense dataset is read-only. Fallback results are stored only in the adaptive cache.
