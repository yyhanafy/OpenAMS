# Adaptive technology-table generation

## Decision

OpenAMS retains explicit table-intersection synthesis. A continuous technology model is used as an on-demand table generator, not as a symbolic constraint solver.

## Flow

```text
continuous technology model
        ↓ direct evaluation
case-specific sampling domain + density
        ↓
adaptive local table
        ↓
existing filter/join/intersection synthesis
        ↓
refine surviving or near-feasible domain
        ↓
new exact model evaluations
```

Every retained row is produced by a direct model evaluation. Technology-table interpolation is not used to produce row values.

## Public objects

- `AxisDomain`: one finite coordinate range and requested density.
- `SamplingDomain`: Cartesian local model-input domain.
- `GenerationPolicy`: point budget, batch size, finite-value and saturation policy.
- `ContinuousTechnologyModel`: backend protocol exposing `identity` and `evaluate_many()`.
- `AdaptiveTableGenerator`: evaluates the exact requested grid.
- `AdaptiveTable`: immutable explicit point cloud with provenance.
- `surviving_domain()`: bounds and densifies points selected by caller-owned constraints.

## Layer boundaries

This layer is generic. It contains no SKY130 names, MOS equations, MLP framework dependency, ngspice invocation, topology rules, design intent, synthesis joins, or optimization policy.

Circuit-specific code owns the feasibility predicate. A future adapter may convert `AdaptiveTable.rows()` to the canonical `CharacterizationTable` representation used by `openams.technology.table`.

## Why correlation is preserved

The generator does not convert outputs to independent ranges. It emits complete correlated rows:

```text
(width, vgs, vds, id, vdsat, gm, ...)
```

Filtering and intersection retain or reject each complete row. Refinement only selects a smaller input box and increases density; the continuous model then recomputes every new row exactly.

## Initial scope

Included:

- linear and logarithmic grids
- fixed coordinates
- deterministic Cartesian enumeration
- batched model evaluation
- strict point budget
- optional saturation filtering
- non-finite rejection
- provenance and diagnostics
- density refinement around surviving rows

Deferred:

- non-Cartesian samplers
- boundary/near-miss scoring
- uncertainty-driven refinement
- model confidence constraints
- CSV serialization
- integration with synthesis solve groups
- SKY130 MLP adapter
