# Explicit Region Intersection

## Purpose

This slice begins the `openams.synthesis` layer. It combines explicit feasible
rows from multiple devices or previously synthesized subregions into an
explicit circuit region.

The layer does not solve transistor equations, interpolate technology data, or
infer topology. It performs deterministic joins and filters over complete,
correlated rows.

## Architectural position

```text
continuous technology model
        ↓
adaptive local table generation
        ↓
feasible technology regions
        ↓
explicit region intersection          ← this slice
        ↓
branch / stage / circuit regions
        ↓
resolved assignments or optimization
```

## Core rule

A source row is indivisible. Values originating from one device operating point
must never be recombined independently with values from another row of that
same source region.

Each retained circuit row therefore contains:

- namespaced values such as `M1.id`, `M1.w`, and `M3.vgs`;
- the exact source-row index selected from every input region;
- deterministic intersection provenance.

## Public model

- `RegionInput`: a named set of complete source rows.
- `CircuitRow`: one retained combination and its source indices.
- `CircuitRegion`: all retained combinations, bounded rejection records, and
  aggregate diagnostics.
- `RegionIntersection`: deterministic Cartesian join followed by generic
  circuit constraints.

`RegionInput.from_feasible_region()` adapts the technology-side
`FeasibleRegion` without introducing a reverse dependency from technology to
synthesis.

## Generic constraints

The first constraint vocabulary contains:

- `FieldRelationConstraint` for equality, scaled mirror relationships, offsets,
  and tolerances;
- `SumConstraint` for KCL-like affine sums;
- `AllowedValuesConstraint` for finite categorical or discrete restrictions.

Constraints operate on namespaced fields and remain independent of MOS naming,
specific circuit topologies, or a particular PDK.

## Complexity and safety

The baseline algorithm is an explicit Cartesian product. This is intentionally
simple, inspectable, and correct. `IntersectionPolicy.max_combinations` rejects
an oversized join before enumeration. Later slices may add indexed joins and
join planning without changing the immutable public result model.

Rejection records may also be bounded while exact aggregate rejection and
failure counts are preserved.

## Non-goals

This slice does not:

- parse design intent;
- discover current groups from topology;
- schedule the order of multiple intersections;
- derive variables analytically;
- collapse a circuit region into independent min/max ranges;
- invoke an optimizer or simulator.

Those belong to later compiler and execution layers.
