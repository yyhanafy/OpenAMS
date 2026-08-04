# OpenAMS Benchmark Extrema Analysis

- Total rows: **10000**
- Accepted rows: **6555**
- Top/bottom rows retained per metric: **10**

## Resolved columns

- `gain_db` → `gain_est_db`
- `ugb_hz` → `ugb_est_hz`
- `phase_margin_deg` → `phase_margin_est_deg`
- `power_w` → `power_est_w`
- `w_m1_um` → `w_m1_um`
- `w_m3_um` → `w_m3_um`
- `w_m6_um` → `w_m6_um`
- `i_m5_a` → `i_m5_a`
- `vout_v` → `vout_v`

## Absolute extrema

| Metric | Minimum | Maximum |
|---|---:|---:|
| gain_db | 49.43831281 | 64.47790124 |
| ugb_hz | 1250763.87 | 10454128.19 |
| phase_margin_deg | 24.24412845 | 73.58612353 |
| power_w | 2.428519925e-05 | 0.0001198660055 |
| w_m1_um | 1 | 50 |
| w_m3_um | 0.8139640804 | 6.061227321 |
| w_m6_um | 0.5310650997 | 4.365005411 |
| i_m5_a | 1.00164e-05 | 4.84558e-05 |
| vout_v | 0.6 | 1.5 |

## Important note

Phase-margin extrema are model extrema only. The present ngspice validation has identified a systematic phase-model disagreement.

## Generated files

- `extrema_full_rows.csv`
- `distribution_summary.csv`
- `correlation_matrix.csv`
- `extrema_summary.json`
