# Direct Simulation Manifests

## Status

This document is normative. It defines the boundary between execution planning
and concrete simulator adapters.

## Purpose

Fully resolved assignments already carry a direct-simulation execution plan.
This layer converts those two immutable objects into a backend-neutral manifest
without introducing simulator syntax into synthesis or planning.

```text
simulation-ready Assignment
        +
direct ExecutionPlan
        +
SimulationTemplate
        ↓
DirectSimulationManifestBuilder
        ↓
SimulationManifest
        ↓
SimulationRunRequest
        ↓
concrete simulator adapter (ngspice, Xyce, ...)
```

## Dependency rule

`openams.simulation` imports only canonical objects from `openams.model`.
Execution plans are accepted structurally. The package does not import
`openams.planning` or `openams.synthesis`, and neither lower layer imports the
simulation package.

Application composition creates `DirectSimulationInput` values from emitted
assignments and their plans.

## Manifest contents

A manifest contains:

- a logical backend selection;
- an external circuit-template reference;
- canonical-variable to template-parameter bindings;
- one immutable case per assignment;
- requested analyses;
- complete assignment and plan provenance.

It contains no ngspice deck rendering, subprocess invocation, output parsing,
or specification evaluation.

## Validation

A case is accepted only when:

- its assignment is `simulation_ready`;
- its plan route is `direct_simulation`;
- its plan contains the `simulate` stage;
- it does not require an executable contract;
- every template binding has a numeric assignment value.

These checks prevent optimization or incomplete assignments from accidentally
entering the fixed-assignment simulator path.

## Adapter boundary

Concrete adapters implement the `SimulationRunner` protocol:

```python
runner.run(SimulationRunRequest(...))
```

A future ngspice adapter may render decks, create case directories, invoke the
binary, and return raw results. Those operations are intentionally outside this
slice.
