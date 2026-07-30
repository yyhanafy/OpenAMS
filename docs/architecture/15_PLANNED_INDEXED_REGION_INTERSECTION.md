# Planned and Indexed Region Intersection

## Purpose

The explicit Cartesian intersection remains the reference implementation, but its
cost grows as the product of all input row counts. This slice adds a planner and
an indexed execution engine without changing the meaning of a retained circuit
row.

## Safe optimization boundary

Only an exact cross-region relation of the form

```text
A.field = B.field
```

may become a hash-join key. A relation with a scale, offset, absolute tolerance,
or relative tolerance remains a residual constraint. Sum/KCL constraints and
arbitrary predicates are also residual constraints.

The planner therefore never treats approximate numerical equivalence as exact
hash equality.

## Objects

- `JoinKey`: an exact cross-region field equality.
- `JoinStep`: one incoming region and the key used to join it.
- `JoinPlan`: deterministic input order, indexed steps, residual constraints,
  and fallback reason.
- `IntersectionPlanner`: derives a safe plan from regions and constraints.
- `PlannedRegionIntersection`: executes indexed joins and then evaluates every
  declared constraint over complete namespaced rows.

## Execution

```text
Region inputs + constraints
          |
          v
 IntersectionPlanner
          |
    +-----+------------------+
    |                        |
 exact connected keys     no safe plan
    |                        |
    v                        v
 indexed equality joins   Cartesian reference engine
    |
    v
 evaluate all constraints
    |
    v
 CircuitRegion
```

The indexed engine preserves full source-row provenance and never decomposes a
row into independent field ranges.

## Diagnostics

Indexed execution can report total Cartesian combinations, materialized indexed
candidates, work items, retained rows, and post-join filtering. It deliberately
does not claim complete per-combination rejection diagnostics because candidates
excluded by the index were never materialized. When complete rejection records
are requested, execution falls back to the Cartesian reference engine.

## Fallback cases

Fallback is mandatory when:

- regions are not connected by exact equality constraints;
- the only available relationships are approximate, scaled, KCL, or arbitrary;
- an indexed field is absent;
- complete rejection diagnostics are requested.

Fallback can be disabled for callers that prefer an explicit planning error.

## Architectural rule

Planning is an optimization of enumeration, not a new source of circuit
semantics. Constraints remain authoritative, and every materialized candidate is
still checked by the ordinary constraint evaluators before retention.
