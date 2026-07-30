# OpenAMS Technology Contract

## Status

This document defines the technology-independent production boundary for
`openams.technology`.

## Responsibility

The technology layer describes what a process backend can provide and how
downstream OpenAMS packages request device information.

It owns:

- technology identity;
- process corner and temperature;
- device model identity;
- supported quantities and capabilities;
- immutable device operating-point queries;
- immutable characterization records;
- immutable lookup results;
- backend protocol definition;
- structural validation and capability inspection.

It does not yet own:

- CSV loading;
- interpolation;
- inverse width solving;
- SKY130-specific behavior;
- ngspice characterization;
- machine-learning models;
- caching;
- synthesis policy;
- optimization.

## Design principle

Downstream code depends on the technology contract, not on a particular PDK or
data representation.

A technology backend may later be implemented using:

- characterization tables;
- ngspice;
- analytical models;
- neural-network surrogates;
- remote services.

All backends must expose the same immutable request and result objects.

## Technology identity

`TechnologyIdentity` identifies a concrete process/model source using:

- technology name;
- optional foundry;
- optional PDK version;
- optional model version;
- optional provenance metadata.

Examples:

```text
sky130 / open_pdks / sky130A
gf180mcu / open_pdks
```

The contract does not impose a naming convention beyond non-empty normalized
strings.

## Operating condition

`OperatingCondition` contains:

- process corner;
- temperature in degrees Celsius;
- optional supply voltage;
- optional body-bias context;
- provenance.

All numeric values must be finite.

## Device identity

`DeviceModel` contains:

- stable model name;
- `DevicePolarity`;
- nominal device kind;
- optional voltage class;
- optional metadata.

The initial device kind is MOS. The enum leaves room for later extensions.

## Quantities

`TechnologyQuantity` names a quantity that may be requested or returned.

The initial set includes:

```text
ID
GM
GDS
GMB
VTH
VDSAT
CAP_GS
CAP_GD
CAP_GB
CAP_DB
CAP_SB
NOISE_DENSITY
```

The enum is intentionally explicit so capability checks remain deterministic.

## Device query

`DeviceOperatingPoint` identifies one transistor operating point:

```text
model
condition
length
width
VGS
VDS
VBS
```

Dimensions are stored in SI units.

The query does not assume saturation and does not infer polarity-dependent sign
conventions. Backends return absolute or signed quantities according to their
declared `SignConvention`.

## Lookup request and result

`TechnologyLookupRequest` contains:

- one operating point;
- a non-empty set of requested quantities;
- optional saturation requirement;
- request metadata.

`TechnologyLookupResult` contains:

- the original request;
- returned scalar quantities;
- operating-region declaration;
- backend identity;
- optional interpolation or model diagnostics;
- result metadata.

Every requested quantity must appear in a successful result. Additional returned
quantities are allowed.

## Characterization records

`CharacterizationPoint` represents one immutable observed or generated sample.

It contains:

- device operating point;
- measured quantities;
- operating region;
- source;
- diagnostics;
- provenance.

This object is suitable for tables, model training, verification, and backend
testing without committing OpenAMS to a file format.

## Capabilities

`TechnologyCapabilities` declares:

- supported device kinds;
- supported quantities;
- supported polarities;
- whether saturation classification is available;
- whether interpolation is available;
- whether inverse queries are available;
- whether derivatives are available.

Capabilities are declarations only. They do not perform queries.

## Backend protocol

`TechnologyBackend` is a runtime-checkable protocol requiring:

```python
identity
capabilities
lookup(request)
```

Concrete backends must be implemented in later slices.

## Error policy

Structural errors are rejected at construction time.

Backend execution errors should later use the package exception hierarchy:

- `TechnologyError`
- `TechnologyValidationError`
- `TechnologyCapabilityError`
- `TechnologyLookupError`

## Dependency boundary

`openams.technology` may depend on:

- `openams.model`
- `openams.metadata`

The first contract implementation is self-contained and uses only standard
library types.

It must not depend on:

- topology;
- constraints;
- planning;
- synthesis;
- simulation;
- evaluation;
- optimization.

Technology describes device behavior independently of any circuit topology.
