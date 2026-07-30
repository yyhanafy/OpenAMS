# Simulation workflow orchestration

## Purpose

This slice composes the existing simulation layers without collapsing their
responsibilities.

```text
SimulationRunRequest
        ↓
SimulationRunner
        ↓
backend execution result
        ↓
RawResultParser
        ↓
RawSimulationCaseResult[]
        ↓
SpecificationScreeningEngine
        ↓
ScreeningSummary
```

The workflow preserves every intermediate object in one immutable
`SimulationWorkflowResult`.

## Preserved artifacts

The workflow result contains:

- the original run request;
- the concrete backend execution result;
- every successfully parsed raw case result;
- the complete screening summary;
- workflow diagnostics;
- provenance counts.

No layer replaces the output of the previous layer.

## Configuration consistency

At workflow construction time, every specification rule must reference a
declared measurement using the same analysis and measurement name.

This prevents a screening rule from silently depending on a value that the
parser was never instructed to extract.

## Failure boundaries

Execution infrastructure failures are raised as `WorkflowError` because no
backend result exists to preserve.

Per-case parser failures are recorded as structured diagnostics. Other cases
continue through parsing and screening.

Known simulation failures represented inside a concrete execution result are
not orchestration exceptions. They remain normal data for the raw parser and
screening layers.

## Success meaning

A workflow is successful only when:

- no workflow diagnostics were emitted;
- no screened case failed;
- no screened case remained unknown.

This is stricter than simulator process success.

## Dependency direction

```text
workflow
    imports runner/parser/screening protocols and models

screening
    does not import workflow

raw results
    do not import workflow

ngspice adapter
    does not import workflow

synthesis
    does not import workflow
```

The orchestration layer is therefore the first location where the complete
direct-simulation execution path is assembled.

## Next slice

The next layer should add persistence for the complete workflow result:

- canonical JSON output;
- stable schema version;
- manifest and case-relative artifact references;
- deterministic summary CSV;
- reload support for later ranking or optimization feedback.
