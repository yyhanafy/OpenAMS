# OpenAMS standalone MLP patch

This archive contains only the standalone MOS MLP implementation and its
training/testing utilities. It does not contain or modify characterization
CSV files, runtime outputs, model checkpoints, or existing OpenAMS modules.

Extract from the OpenAMS repository root:

```bash
tar -xzf openams_mlp_implementation_only.tgz
```

Added paths:

- `src/openams/technology/ml_surrogate/`
- `tools/technology/train_sky130_mlp.py`
- `tools/technology/test_sky130_mlp.py`
- `tests/technology/ml_surrogate/`

No pipeline integration is included.
