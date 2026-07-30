# OpenAMS Layer Dependencies

## Status

This document is normative. It defines the allowed dependency direction for
the OpenAMS implementation. Code that violates these rules is architecturally
incorrect even when its tests pass.

## Core rule

Dependencies point toward more stable concepts.

```text
                    application / CLI
                           |
          +----------------+----------------+
          |                                 |
     optimization                       evaluation
          |                                 |
          +---------------+-----------------+
                          |
                     simulation
                          |
                     synthesis
                          |
                      planning
                          |
                    constraints
                          |
                      topology
                          |
                     metadata
                          |
                        model

Infrastructure adapters:
    io          -> standard library / optional serialization libraries
    technology  -> model
```

The diagram describes conceptual flow, not permission for every adjacent
package to import every package below it. The package matrix below is the
authoritative rule.

## Architectural layers

### `openams.model`

Owns immutable domain objects shared across the system.

Allowed imports:

- Python standard library only.

Forbidden imports:

- every other `openams` package;
- filesystem or serialization libraries;
- simulator, optimizer, and technology implementations.

### `openams.io`

Owns external representation and filesystem access.

Examples:

- project path discovery;
- YAML, JSON, and TOML loading;
- serialization;
- text and file encoding.

Allowed imports:

- Python standard library;
- optional serialization libraries.

Forbidden imports:

- `openams.metadata`;
- topology, constraints, planning, synthesis, technology, simulation,
  evaluation, optimization, and CLI packages.

The I/O package returns ordinary Python values. Application composition passes
those values to metadata normalization.

### `openams.metadata`

Owns semantic configuration normalization and validation.

Examples:

- converting generic mappings into immutable configuration objects;
- validating required semantic keys;
- normalizing provider declarations;
- rejecting obsolete metadata shapes.

Allowed imports:

- `openams.model`;
- Python standard library.

Forbidden imports:

- `openams.io`;
- YAML, JSON, or TOML libraries;
- filesystem existence checks;
- topology and all higher layers.

Metadata objects must not record how their source document was loaded.

### `openams.topology`

Owns netlist interpretation and circuit connectivity.

Allowed imports:

- `openams.model`;
- `openams.metadata`.

Forbidden imports:

- constraints, planning, synthesis, technology, simulation, evaluation,
  optimization, and CLI packages.

Topology records connectivity. It does not infer circuit intent such as
differential pairs, mirrors, stages, or folded branches unless that intent is
explicitly supplied as metadata.

### `openams.constraints`

Owns canonical constraint construction and validation.

Allowed imports:

- `openams.model`;
- `openams.metadata`;
- `openams.topology`.

Forbidden imports:

- planning, synthesis, technology, simulation, evaluation, optimization,
  and CLI packages.

It represents constraints but does not solve them.

### `openams.planning`

Owns dependency analysis and executable planning.

Allowed imports:

- `openams.model`;
- `openams.constraints`.

Forbidden imports:

- synthesis, technology backends, simulation, evaluation, optimization,
  and CLI packages.

Planning decides ordering and identifies unresolved variables. It does not
evaluate device physics.

### `openams.synthesis`

Owns deterministic assignment generation.

Allowed imports:

- `openams.model`;
- `openams.planning`;
- the public `openams.technology` abstraction.

Forbidden imports:

- concrete technology backend internals;
- simulation, evaluation, optimization, and CLI packages.

Synthesis may call `TechnologyModel.solve(DeviceQuery)`. It must not read
technology tables directly.

### `openams.technology`

Owns device-level technology evaluation.

Allowed imports:

- `openams.model`;
- Python standard library and backend-specific libraries.

Forbidden imports:

- metadata, topology, constraints, planning, synthesis, simulation,
  evaluation, optimization, and CLI packages.

All technology providers implement the public technology abstraction. Circuit
knowledge does not enter this package.

### `openams.simulation`

Owns simulator invocation and result extraction.

Allowed imports:

- `openams.model`;
- simulator adapter libraries.

Forbidden imports:

- topology, constraints, planning, synthesis internals, concrete technology
  backends, evaluation, optimization, and CLI packages.

Simulation verifies a supplied assignment. It never changes design variables.

### `openams.evaluation`

Owns metric interpretation, specification checks, and ranking.

Allowed imports:

- `openams.model`.

Forbidden imports:

- simulator invocation code;
- topology, planning, synthesis, technology backend internals, optimization,
  and CLI packages.

Evaluation consumes simulation results. It does not run simulations.

### `openams.optimization`

Owns search strategies for unresolved assignments.

Allowed imports:

- `openams.model`;
- public synthesis, simulation, and evaluation services through stable
  interfaces.

Forbidden imports:

- raw metadata documents;
- topology parser internals;
- technology table internals;
- CLI packages.

Optimization is conditional. Fully resolved assignments bypass it.

### `openams.cli`

Owns command-line adaptation only.

Allowed imports:

- public APIs from all application packages.

Forbidden behavior:

- implementing domain algorithms;
- parsing technology tables;
- embedding circuit-specific equations;
- mutating shared global state.

## Import matrix

`A -> B` means package A may import package B.

| Package | Allowed OpenAMS imports |
|---|---|
| `model` | none |
| `io` | none |
| `metadata` | `model` |
| `topology` | `model`, `metadata` |
| `constraints` | `model`, `metadata`, `topology` |
| `planning` | `model`, `constraints` |
| `technology` | `model` |
| `synthesis` | `model`, `planning`, `technology` |
| `simulation` | `model` |
| `evaluation` | `model` |
| `optimization` | stable public interfaces only |
| `cli` | public package APIs |

## Composition root

The application or CLI is the composition root:

```python
raw_specs = io.load_yaml(...)
raw_rules = io.load_yaml(...)

project_inputs = metadata.normalize_project_inputs(
    specs=raw_specs,
    design_intent=raw_intent,
    design_rules=raw_rules,
    simulation=raw_simulation,
)
```

This is deliberate. `metadata` does not call `io`, and `io` does not call
`metadata`.

## Communication rules

Cross-package communication uses:

- immutable model objects;
- immutable metadata configuration objects;
- explicit function arguments and return values;
- narrow protocols.

Cross-package communication must not use:

- mutable global registries;
- singleton managers;
- hidden caches as semantic state;
- dictionaries whose schema exists only in comments;
- environment variables read deep inside domain algorithms.

## Circular dependencies

Circular imports are prohibited.

A circular dependency indicates one of the following:

- ownership is misplaced;
- an interface belongs in `model`;
- application composition has leaked into a lower layer;
- two responsibilities must be separated.

A cycle must be fixed architecturally, not hidden with local imports.

## Optional dependencies

Optional libraries are imported only inside the package that owns the external
capability.

Examples:

- PyYAML belongs only to `openams.io`;
- ngspice adapters belong only to `openams.simulation`;
- PyTorch belongs only to a concrete technology or optimization backend.

Importing `openams.metadata` must not require PyYAML. Importing
`openams.model` must not require any third-party package.

## Enforcement

The repository test suite should include an AST-based dependency test. New
packages must be added to its policy table before production code is merged.

Code review must reject:

- upward imports;
- direct backend access across package boundaries;
- filesystem operations in semantic packages;
- parsing libraries in domain packages;
- simulation code that changes assignments;
- optimizer code used for already-resolved assignments.

## Change policy

Changing this document requires an architecture commit separate from ordinary
feature implementation. The commit must explain:

1. the responsibility that moved;
2. the old and new dependency directions;
3. why the change does not introduce a cycle;
4. which enforcement tests changed.
