# Hierarchical Circuit Region Synthesis

## Purpose

Real analog circuits should not be synthesized by forming one Cartesian product
of every device operating-point table.  OpenAMS instead compiles small physical
subsystems first and carries each surviving subsystem forward as a compact,
explicit stage region.

## Flow

```text
Device feasible regions
        ↓
input-pair / mirror / output-stage intersections
        ↓
explicit stage regions
        ↓
full-circuit intersection
        ↓
explicit circuit assignments
```

`HierarchicalSynthesisWorkflow` executes dependency-ordered `SynthesisStage`
objects.  A stage selects existing `RegionBinding` objects, compiles canonical
constraints, executes the planned intersection engine, and publishes the result
as a new binding.

## Correlation and provenance

A stage output retains complete rows from its source intersection.  Fields stay
namespaced (for example `M1.id`), canonical-to-local bindings are propagated,
and later stages record the selected source-row index for each stage region.
No independent min/max envelopes are substituted for correlated rows.

## Two-stage op-amp integration

The first integration exercises the intended topology hierarchy:

1. Compile `M1/M2` as an input-pair region.
2. Compile `M3/M4` as an active-load mirror region.
3. Compile `M6/M7` as an output-stage region.
4. Join those compact stage regions with `M5` using tail KCL and stage-current
   relationships.

This validates the complete path from named device regions through canonical
constraint compilation and planned intersection to inspectable circuit rows.

## Boundaries

This layer does not create technology points, infer topology, run ngspice, or
optimize unresolved ranges.  It consumes explicit feasible rows and canonical
constraints.  Simulation confirmation remains a later execution stage.
