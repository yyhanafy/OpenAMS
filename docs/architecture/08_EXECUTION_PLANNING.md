# OpenAMS Execution Planning

## Status

This document defines the production boundary for `openams.planning`.

## Responsibility

The planning layer answers:

> Given the known design quantities and unresolved relationships, what work
> remains before the circuit can be verified?

It owns:

- immutable design-state declarations;
- variable-role classification;
- route selection;
- ordered execution-stage declarations;
- plan validation;
- plan dependency inspection.

It does not own:

- equation solving;
- topology inference;
- technology lookup;
- assignment generation;
- simulation;
- optimization;
- performance scoring.

## Inputs

The planner consumes an explicit `PlanningRequest`.

A request declares:

- all known variable names;
- resolved values;
- synthesis-independent variables;
- optimization-independent variables;
- dependent variables;
- technology-required variables;
- unresolved constraints;
- whether simulation verification is required.

The planner does not infer independence from algebra in this slice. Classification
must come from normalized metadata or a future analysis layer.

## Variable roles

Every variable may have one role:

- `RESOLVED`
- `SYNTHESIS_INDEPENDENT`
- `OPTIMIZATION_INDEPENDENT`
- `DEPENDENT`
- `TECHNOLOGY_REQUIRED`

Roles must not conflict.

A resolved variable is complete and must not also be classified as unresolved.

## Routes

The planner selects one route:

- `DIRECT_SIMULATION`
- `TECHNOLOGY_SYNTHESIS`
- `OPTIMIZATION`
- `SYNTHESIS_THEN_OPTIMIZATION`
- `VALIDATION_ONLY`

### Direct simulation

Selected when all design variables are resolved and simulation verification is
requested.

### Technology synthesis

Selected when unresolved technology-required or synthesis-independent variables
exist, but optimization-independent variables do not.

### Optimization

Selected when optimization-independent variables exist and no technology
synthesis stage is required.

### Synthesis then optimization

Selected when both synthesis work and optimization work remain.

### Validation only

Selected when all variables are resolved and no simulation verification is
requested.

## Execution stages

A plan contains an ordered tuple chosen from:

- `VALIDATE_INPUTS`
- `QUERY_TECHNOLOGY`
- `SYNTHESIZE_ASSIGNMENTS`
- `BUILD_EXECUTABLE_CONTRACT`
- `OPTIMIZE`
- `SIMULATE`
- `VERIFY_SPECIFICATIONS`

The route determines the allowed stage sequence.

## Architectural rule

The planning layer describes work. It does not perform that work.

In particular:

```text
planning != synthesis
planning != optimization
planning != simulation
```

## OpenAMS branch policy

This package reflects the agreed OpenAMS branch behavior:

1. Fully resolved assignments bypass executable-contract generation.
2. Fully resolved assignments go directly to simulation and specification
   verification when verification is requested.
3. An executable contract is required only when optimization-independent
   variables remain.
4. Technology synthesis precedes optimization when unresolved technology-driven
   quantities must first be realized.
5. Synthesis-independent and optimization-independent classifications are
   distinct.

## Dependency boundary

`openams.planning` may depend on:

- `openams.model`
- `openams.metadata`
- `openams.topology`
- `openams.constraints`

The initial implementation depends only on standard-library value types. This
keeps the planning intermediate representation portable and deterministic.
