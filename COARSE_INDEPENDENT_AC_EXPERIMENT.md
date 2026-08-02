# 10,000-Point Coarse Independent-Variable AC Experiment

## Grid

- 40 I5 values selected across the supported I5 point set
- 25 W1 values uniformly spanning 1–50 µm
- 10 Vout values uniformly spanning 0.6–1.5 V
- Total: 10,000 points

## Construction policy

- N1 = 0.6 V
- Vbias = 0.6 V

## Technology roles

- Dense MLP: continuous DC construction, gm, gds, VDSAT
- Dense CSV: nearest-bias width-normalized Cgs/Cgd/Cdb/Csb
- Reduced circuit matrix: estimated gain, UGB, phase margin

The AC values are estimates to rank and map the design space before ngspice.

## First bounded check

```bash
MAX_POINTS=10 PROGRESS_EVERY=1 \
bash scripts/run_coarse_independent_ac_scan.sh
```

## Full experiment

```bash
bash scripts/run_coarse_independent_ac_scan.sh
```

## Resume

```bash
RESUME=1 bash scripts/run_coarse_independent_ac_scan.sh
```

The CSV is checkpointed regularly, so an interrupted run can resume.
