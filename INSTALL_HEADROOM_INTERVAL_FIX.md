# Generic Step-5 Vout interval fix

This patch removes the incorrect requirement that every topology provide an exact `vout_v`.

- If `vout_v` is independent/present, Step 5 validates that exact value.
- Otherwise, Step 5 derives and retains `vout_min_v` and `vout_max_v` from the declared topology-headroom expressions, intersected with the output specification window.
- Such results are emitted as `model_valid_dc_operating_region` and routed to `select_vout_within_feasible_window`.

Install from repository root:

```bash
cp src/openams/synthesis/generic_complete_step5.py \
  src/openams/synthesis/generic_complete_step5.py.before_vout_interval_fix
cp tools/validation/validate_assignment_step_05_complete_assignments.py \
  tools/validation/validate_assignment_step_05_complete_assignments.py.before_vout_interval_fix

tar -xzf ~/Downloads/openams_generic_vout_interval_fix_v1.tgz

export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
python -m py_compile \
  src/openams/synthesis/generic_complete_step5.py \
  tools/validation/validate_assignment_step_05_complete_assignments.py
```
