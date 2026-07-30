# Feasible Technology Regions

## Decision

OpenAMS keeps synthesis explicit and table-based. A continuous technology model is sampled on demand by `openams.technology.adaptive`; this layer then converts the resulting exact model evaluations into an explicit feasible region by applying generic constraints to complete correlated rows.

A feasible region is therefore not a collection of independent per-variable intervals. It is a finite set of complete operating points:

```text
(W, L, VGS, VDS, VBS, ID, VDSAT, gm, gds, ...)
```

Removing a point removes the complete tuple. No projection into unrelated ranges occurs.

## Responsibilities

`openams.technology.feasible`:

- consumes an `AdaptiveTable`;
- evaluates immutable row constraints;
- retains complete correlated rows;
- records all rejection causes;
- reports aggregate failure counts;
- can return a tighter, denser next sampling domain;
- converts retained points back into an `AdaptiveTable` for downstream intersection.

## Non-responsibilities

This layer does not contain:

- MOS-specific equations;
- SKY130 names or units;
- MLP implementation details;
- topology extraction;
- KCL or KVL derivation;
- transistor-group joining;
- optimization policy;
- ngspice execution.

Those concerns belong to later adapters and synthesis layers.

## Constraint model

The initial generic constraints are:

- closed numeric range;
- required Boolean field;
- finite allowed-value set;
- affine relation between two row fields with tolerance.

These constraints are intentionally row-local. Cross-device constraints are applied later when multiple feasible tables are joined by the technology/topology intersection engine.

## Refinement

When enabled, the builder computes the bounding domain of retained rows and increases the sampling density within that domain. The continuous model evaluates the new points directly. Interpolation is not used to produce final rows.

## Pipeline position

```text
ContinuousTechnologyModel
        ↓
AdaptiveTableGenerator
        ↓
FeasibleRegionBuilder
        ↓
explicit feasible device table
        ↓
transistor-group and topology intersections
```
