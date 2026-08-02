# OpenAMS Frozen Benchmark

- Benchmark: `two_stage_opamp_deterministic_constructor_v1`
- Status: **FROZEN**
- Rows: **10,000**
- Constructed: **6,555**
- Rejected: **3,445**
- MLP queries: **24,643,554**
- Git commit at freeze: `c0599e243d912c45c07b858c9fcf319ae5c13d15`
- Git dirty at freeze: `True`

## Integrity verification

```bash
cd "/home/yhanafy/AMS-Tutorial/openams/benchmarks/two_stage_opamp_deterministic_constructor_v1"
sha256sum -c SHA256SUMS
sha256sum -c MANIFEST_SHA256SUMS
```

## Policy

Never modify this directory in place. Create a new version for any code, model, technology, estimator, grid, schema, or tolerance change.
