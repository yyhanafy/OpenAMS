# Backend-neutral raw simulation results

## Purpose

This layer converts simulator-specific artifacts into backend-neutral records
without applying design specifications.

```text
NgspiceRunResult
        ↓
NgspiceRawResultParser
        ↓
RawSimulationCaseResult
        ├── RawAnalysisResult
        └── ScalarMeasurement
```

## Responsibilities

The raw-results layer records:

- simulator execution success;
- convergence evidence;
- per-analysis status;
- declared scalar measurements;
- missing and malformed measurements;
- source artifact paths;
- parser diagnostics;
- case and execution provenance.

## Measurement declarations

The parser only extracts explicitly declared scalar measurements.

```python
MeasurementDeclaration(
    name="gain_db",
    analysis="ac",
    source="log",
    aliases=("av_db",),
    required=True,
    unit="dB",
)
```

This prevents the parser from guessing the semantic meaning of arbitrary
simulator output.

## Analysis status

Each analysis is classified as:

```text
succeeded
failed
incomplete
not_run
```

- `failed` indicates explicit convergence failure.
- `incomplete` indicates successful execution but missing or malformed required
  measurements.
- `not_run` indicates the simulator process itself did not succeed.
- `succeeded` means execution succeeded, no convergence failure was detected,
  and all required measurements were present.

## Separation from specification evaluation

This layer does not decide whether:

- gain satisfies a target;
- phase margin is acceptable;
- power exceeds a limit;
- transistor operating regions pass;
- a candidate should be retained.

Those decisions belong to a later screening layer that consumes these raw
records.

## Current ngspice sources

The ngspice parser recognizes these standard artifact aliases:

```text
log     → ngspice.log
stdout  → stdout.txt
stderr  → stderr.txt
```

A declaration may also name a case-local artifact directly.

## Next slice

The next layer should define specification rules and evaluate raw measurements
into explicit pass/fail/unknown screening records while preserving the raw
simulation results unchanged.
