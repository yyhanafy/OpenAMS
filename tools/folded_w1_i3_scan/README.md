# Folded-cascode W1/I3 full scan

This migration removes `vnb1_v` from the independent grid and derives it from
M3's inverse-feasible realization. The resulting full grid is:

- 25 samples of `w_m1_um`
- 81 characterized values of `i_m3_a`
- total: 2,025 independent points

The package also adds progress output and a live `progress.json` file.
