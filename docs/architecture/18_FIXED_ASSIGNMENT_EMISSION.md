# Fixed Assignment Emission

## Purpose

The synthesis compiler produces an explicit `CircuitRegion`: complete correlated
rows that satisfy technology, topology, and design-intent constraints. The
execution subsystem consumes canonical `Assignment` objects and immutable
`ExecutionPlan` objects. This slice is the boundary between those layers.

```text
CircuitRegion
    + canonical-to-synthesis field map
        ↓
CircuitRegionAssignmentEmitter
        ↓
Assignment(status=simulation_ready)
        +
ExecutionPlan(route=direct_simulation)
```

## Architectural rule

A retained circuit row is converted atomically. Values are never selected from
independent column ranges and rows are never recombined. This preserves every
correlation established by adaptive technology generation and hierarchical
region intersection.

## Canonical field mapping

Circuit rows may contain synthesis-local names such as:

```text
input_pair.M1.w
output_stage.M6.id
```

The emitter receives an explicit map:

```python
{
    "device.M1.width": "input_pair.M1.w",
    "device.M6.current": "output_stage.M6.id",
}
```

The output assignment contains only canonical names. Missing mappings, missing
row fields, duplicate target fields, nonnumeric values, and nonfinite values are
reported as explicit errors.

## Direct-simulation routing

Every emitted value is resolved. The emitter therefore constructs a
`PlanningRequest` with all variables in `resolved_values`. The existing planner
must select:

```text
ExecutionRoute.DIRECT_SIMULATION
```

and must not add executable-contract or optimization stages. This enforces the
OpenAMS rule that fully resolved synthesis assignments bypass optimization and
go directly to ngspice confirmation and specification screening.

## Provenance

Each assignment records:

- source circuit-row index;
- source row indices from every contributing region;
- circuit-region metadata;
- the exact canonical-to-synthesis mapping.

This makes a simulation result traceable back through stage intersection and
ultimately to the technology rows from which it was synthesized.

## Public types

- `FixedAssignmentPolicy`
- `FixedAssignmentRecord`
- `FixedAssignmentBatch`
- `CircuitRegionAssignmentEmitter`
