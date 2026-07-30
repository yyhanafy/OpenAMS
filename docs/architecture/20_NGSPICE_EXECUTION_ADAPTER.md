# Concrete ngspice execution adapter

## 1. Purpose

This slice implements the first concrete simulator backend for the clean
OpenAMS architecture.

It consumes the backend-neutral direct-simulation request created by the
simulation-manifest layer and produces deterministic case directories plus
immutable execution records.

It does not parse circuit metrics.

## 2. Architectural boundary

```text
SimulationRunRequest
        |
        v
NgspiceRunner
        |
        +-- render one SPICE deck per case
        +-- write case inputs and provenance
        +-- invoke ngspice in batch mode
        +-- capture process diagnostics
        |
        v
NgspiceRunResult
```

The synthesis layer does not import this adapter.  The adapter does not compile
constraints, select assignments, interpret topology, evaluate specifications,
or optimize a circuit.

## 3. Deterministic case directory

Each manifest case receives one directory named from its case identity:

```text
output/
  assignment_000001/
    rendered.spice
    parameters.json
    case.json
    ngspice.log
    stdout.txt
    stderr.txt
    result.json
  run_result.json
```

Existing directories are rejected unless overwrite behavior is explicitly
enabled.

## 4. Template rendering

The renderer supports only explicit scalar substitutions:

```text
{{PARAMETER}}
${PARAMETER}
@PARAMETER@
```

This is intentionally smaller than a general template language.  Missing
values are errors in strict mode.  Numeric values are rendered
deterministically with sufficient precision for round-trip recovery.

## 5. Process invocation

The default command is:

```text
ngspice -b -o <case>/ngspice.log <case>/rendered.spice
```

The runner records:

- executable path;
- complete command;
- working directory;
- timeout;
- return code;
- stdout;
- stderr;
- timeout status.

A nonzero ngspice return code creates a failed case result; it does not destroy
the remaining batch diagnostics.  Infrastructure failures such as a missing
executable raise an adapter error.

## 6. Deliberate exclusions

This slice does not:

- parse DC operating points;
- extract gain, bandwidth, phase margin, or slew rate;
- evaluate transistor operating regions;
- apply specification limits;
- decide whether AC should follow DC;
- retry convergence;
- invoke optimization.

Those belong to later result-parsing and simulation-policy slices.

## 7. Compatibility strategy

The runner reads manifest and case objects structurally.  It accepts the
canonical simulation model without creating a reverse dependency from this
backend module to synthesis or execution-planning internals.

The expected structural fields are:

```text
request.manifest
request.output_directory
manifest.backend
manifest.template.source
manifest.cases
case.name
case.rendered_parameters
case.assignment_name
case.analyses
```

Equivalent documented aliases are accepted at the adapter boundary so the
backend remains tolerant of harmless naming refinements in the
backend-neutral manifest model.

## 8. Next slice

The next layer should parse backend artifacts into backend-neutral raw
simulation results.  It should begin with convergence and declared scalar
measurements, while keeping specification evaluation separate.
