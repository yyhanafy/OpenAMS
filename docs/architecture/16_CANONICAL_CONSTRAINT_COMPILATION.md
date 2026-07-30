# Canonical Constraint Compilation

## Purpose

This layer connects the immutable circuit model to explicit region synthesis.
It translates data-only circuit constraints into the generic predicates already
understood by the Cartesian and planned/indexed intersection engines.

```text
Circuit constraints + named device regions
                    |
                    v
          RegionBinding map
                    |
                    v
     CircuitConstraintCompiler
                    |
                    v
       CompiledIntersection
                    |
                    v
   PlannedRegionIntersection
```

## Boundary

The compiler contains no op-amp stage names, MOS equations, technology-table
logic, simulator behavior, or optimization policy.  It accepts objects by the
canonical constraint protocol: `name`, `kind`, `expression`, and optional
`source`.

## Supported first slice

- exact equality: `a == b`;
- affine equality: `a == scale*b + offset`;
- linear sums and KCL: `a == b + c - d`;
- immutable canonical-to-namespaced field binding;
- compilation diagnostics and source provenance;
- direct execution through the planned/indexed intersection engine.

Exact cross-region equalities become indexable joins automatically. Affine and
sum relations remain residual constraints and use the existing safe fallback.

## Deliberately deferred

- inequalities and ranges;
- Boolean and membership expressions;
- nonlinear symbolic equations;
- unit conversion;
- automatic construction of device regions from technology queries.

Unsupported constraints fail explicitly in strict mode. Non-strict mode records
them as diagnostics but never silently claims they were enforced.
