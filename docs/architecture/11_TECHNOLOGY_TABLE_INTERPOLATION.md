# OpenAMS Generic Technology Table Interpolation

## Status

This document defines generic interpolation over
`openams.technology.table`.

Package:

```text
openams.technology.table.interpolation
```

## Responsibility

The interpolation layer turns a discrete characterization table into a
continuous forward-query backend inside the characterized domain.

It owns:

- exact-or-interpolated lookup;
- strict no-extrapolation behavior;
- deterministic one-axis linear interpolation;
- deterministic staged multi-axis interpolation;
- interpolation provenance and diagnostics;
- operating-region compatibility checks;
- saturation requirement preservation.

It does not own:

- inverse width solving;
- extrapolation;
- SKY130 schemas;
- CSV parsing;
- characterization generation;
- ngspice execution;
- machine-learning inference;
- synthesis policy.

## Numerical policy

Interpolation is linear along one axis at a time.

For multiple varying axes, interpolation is performed in a deterministic
sequence:

```text
temperature_c
length_m
width_m
vbs_v
vds_v
vgs_v
```

The configured axis order is part of backend identity and diagnostics.

This staged method is equivalent to multilinear interpolation on a complete
rectilinear grid. Sparse grids are rejected when a required bracket cannot be
formed.

## Exact lookup precedence

An exact table row always wins.

No interpolation is performed when an exact point exists and contains all
requested quantities.

## No extrapolation

A request outside the characterized range fails.

The backend must have both lower and upper neighbors at every interpolation
stage. One-sided brackets are insufficient.

## Quantity policy

Every source point used in an interpolation step must contain every requested
quantity.

Values are interpolated independently:

```text
y = y0 + alpha * (y1 - y0)
alpha = (x - x0) / (x1 - x0)
```

## Operating-region policy

Interpolation is permitted only when the lower and upper source points have
compatible operating regions.

Compatible means:

- both regions are identical; or
- one or both are `UNKNOWN`, in which case the known region is preserved.

Conflicting known regions cause lookup failure.

When saturation is required, all contributing source points must be classified
as `SATURATION`.

## Interpolated records

Internal interpolation produces immutable synthetic
`CharacterizationPoint` objects.

The synthetic point:

- has the requested operating-point coordinate on the interpolated axis;
- preserves exact coordinates on all other axes;
- contains interpolated requested quantities;
- records source count and interpolation step diagnostics;
- uses source `linear_interpolation`.

Synthetic points are not inserted into the underlying table.

## Diagnostics

Successful interpolated lookup results include:

```text
lookup_method
axis_order
interpolation_steps
source_point_count
source_keys
```

This makes every result reproducible and auditable.

## Architecture boundary

The interpolation package may depend on:

```text
openams.technology
openams.technology.table
```

It must not depend on:

- topology;
- constraints;
- planning;
- synthesis;
- simulation;
- evaluation;
- optimization;
- pandas;
- numpy;
- scipy;
- torch;
- ngspice.

## Future dependency

Inverse lookup will consume this backend through the standard
`TechnologyBackend` protocol. It must not duplicate interpolation logic.
