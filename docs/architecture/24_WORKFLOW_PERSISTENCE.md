# Simulation workflow persistence

## Purpose

This slice persists the complete direct-simulation workflow without discarding
any intermediate layer.

```text
SimulationWorkflowResult
        ↓
SimulationWorkflowPersistence
        ├── workflow_result.json
        └── screening_summary.csv
```

## Canonical JSON

`workflow_result.json` contains:

- a stable schema version;
- the original request payload;
- the backend execution result;
- parsed raw results;
- specification-screening results;
- workflow diagnostics;
- workflow provenance.

The JSON writer uses:

- sorted keys;
- two-space indentation;
- UTF-8;
- finite numeric values only;
- one trailing newline.

Current schema identifier:

```text
openams.simulation_workflow.v1
```

## Relative artifact references

Absolute paths located beneath the persistence directory are rewritten as
relative paths.

Example:

```text
/home/user/openams/runtime/run_001/case_0001/ngspice.log
```

becomes:

```text
case_0001/ngspice.log
```

Paths outside the artifact root remain unchanged because silently rewriting
external references would make them ambiguous.

## Deterministic screening CSV

`screening_summary.csv` contains one row per case-rule pair.

Stable columns include:

- case outcome;
- execution success;
- failed and unknown rule counts;
- rule name;
- analysis and measurement;
- rule outcome;
- actual value;
- comparison operator;
- threshold or range;
- tolerance;
- unit;
- diagnostic.

Cases and rules are sorted by name before serialization.

## Reload support

`load_payload()` validates the schema version before returning the persisted
dictionary.

This intentionally reloads the canonical payload rather than reconstructing
live Python domain objects. Rehydration should be added only when a downstream
consumer requires typed objects.

## Separation from ranking

Persistence does not:

- rank valid designs;
- calculate optimization objectives;
- modify specification outcomes;
- choose the next candidate;
- rerun simulations.

It only records the complete workflow deterministically.

## Next slice

The next layer should consume persisted screening results and create a
backend-neutral candidate evaluation record suitable for:

- ranking passing designs;
- returning structured feedback to an optimizer;
- distinguishing infeasible, unknown, and valid candidates;
- preserving individual objective components.
