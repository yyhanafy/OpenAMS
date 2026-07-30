# OpenAMS Generic Technology Table Backend

## Status

This document defines the first concrete backend for `openams.technology`.

Package:

```text
openams.technology.table
```

## Responsibility

The table backend stores immutable characterization points and performs
deterministic table queries.

It owns:

- immutable characterization-table construction;
- table-wide identity and capabilities;
- model/condition indexing;
- exact operating-point lookup;
- deterministic nearest-point lookup;
- deterministic one-axis bracketing;
- lookup-result construction from exact table records;
- structural table validation.

It does not own:

- CSV parsing;
- SKY130 column conventions;
- interpolation;
- inverse width solving;
- extrapolation;
- ngspice execution;
- characterization generation;
- machine-learning inference;
- caching policy;
- synthesis policy.

## Input representation

The backend consumes `CharacterizationPoint` objects from the technology
contract. It is therefore neutral to source format.

Rows may later come from:

- CSV;
- JSON;
- Parquet;
- ngspice characterization;
- generated fixtures;
- ML validation datasets.

## Table identity

`CharacterizationTable` contains:

- one backend `TechnologyIdentity`;
- one `TechnologyCapabilities` declaration;
- an immutable ordered tuple of points;
- immutable metadata.

All points must be compatible with the declared capabilities.

## Exact key

An exact point is identified by:

```text
model name
device polarity
device kind
process corner
temperature
length
width
VGS
VDS
VBS
```

Optional operating-condition context such as supply voltage and body bias is
also compared when present.

Floating-point fields are compared exactly in this slice. Source adapters are
responsible for consistent normalization.

## Exact lookup

`TableTechnologyBackend.lookup()` supports exact lookup only.

A request succeeds when:

1. backend capabilities support the request;
2. one exact operating point exists;
3. all requested quantities exist in that point;
4. a requested saturation condition is satisfied.

Otherwise, a typed technology error is raised.

## Deterministic nearest lookup

`nearest_points()` returns points ordered by normalized Euclidean distance in
the electrical/dimensional coordinate space:

```text
length
width
VGS
VDS
VBS
temperature
```

Only points matching model identity and process corner are considered.

Distance normalization is computed from the candidate subset span per axis.
Zero-span axes contribute zero distance.

Ties are broken by the stable table insertion order.

Nearest lookup is an inspection primitive. It does not claim physical
interpolation validity.

## One-axis bracketing

`bracket_points()` locates the lower and upper neighboring samples along one
axis while requiring exact equality on all other operating-point coordinates.

Supported axes:

```text
length_m
width_m
vgs_v
vds_v
vbs_v
temperature_c
```

The result may contain:

- both lower and upper points;
- only a lower point;
- only an upper point;
- neither point.

An exact point is returned as both lower and upper.

Bracketing does not interpolate.

## Duplicate policy

Duplicate exact operating points are rejected.

This prevents ambiguous lookup results and makes table behavior deterministic.

## Capability derivation

This slice does not derive capabilities implicitly.

The constructor receives explicit capabilities and validates each row against
them. Later adapters may provide convenience capability derivation.

## Architecture boundary

The generic table backend may depend on:

```text
openams.technology
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

## Future slices

Later work may add:

```text
openams.technology.table.interpolation
openams.technology.table.inverse
openams.technology.sky130
openams.technology.mlp
```

Those features must build on this exact-table foundation rather than changing
its deterministic semantics.
