# OpenAMS Design Guidelines

## Status

This document is normative for production code in the OpenAMS rebuild.

## Design objective

OpenAMS should be understandable as a sequence of explicit transformations:

```text
external representation
    -> semantic metadata
    -> topology
    -> constraints
    -> dependency plan
    -> assignments
    -> technology resolution
    -> simulation results
    -> evaluation results
```

Each package introduces one new concept and preserves the meaning of earlier
objects.

## Default to immutability

Production domain objects are immutable by default.

Preferred tools:

- `@dataclass(frozen=True, slots=True)`;
- tuples instead of lists;
- immutable mapping views or recursively frozen mappings;
- explicit replacement that creates a new object.

Mutation requires a documented reason, normally confined to a short-lived
builder or external adapter.

## Constructors protect invariants

Invalid objects should not exist.

Use `__post_init__` or normalization factories to reject:

- empty canonical names;
- unknown references;
- inconsistent ranges;
- duplicate identifiers;
- active selections that do not exist;
- unsupported enum values.

Do not postpone obvious structural errors until simulation.

## Public APIs are narrow

Every package has a deliberate `__all__`.

Public classes and functions must have:

- a precise semantic purpose;
- stable input and output types;
- no hidden global state;
- documented ownership.

Internal helpers begin with `_` and are not imported by other packages.

## Naming

Use domain nouns:

- `Circuit`;
- `Assignment`;
- `DependencyPlan`;
- `TechnologyModel`;
- `SimulationResult`;
- `EvaluationResult`.

Use verbs for transformations:

- `normalize_project_inputs`;
- `compile_constraints`;
- `plan_dependencies`;
- `synthesize_assignments`;
- `evaluate_specifications`.

Avoid vague names:

- `Manager`;
- `Helper`;
- `Utils`;
- `Processor`;
- `Engine`;
- `Handler`;
- `Data`.

A broad name usually hides mixed responsibilities.

## Functions

Prefer functions that are:

- small;
- deterministic;
- explicit about dependencies;
- free of observable side effects;
- easy to test with value equality.

Functions should not read environment variables, current directories, or
global configuration unless they are I/O adapters explicitly responsible for
that behavior.

## Exceptions

Raise meaningful package-specific exceptions.

Do not use `None`, `False`, or empty collections to hide failures when absence
is not a valid result.

Exception messages should include:

- the invalid field or object;
- the offending value when safe;
- the violated invariant;
- enough context to identify the source.

Wrap external-library exceptions at package boundaries while preserving the
original exception with `raise ... from exc`.

## Dictionaries

Raw mappings are accepted only at representation boundaries.

After normalization, use named immutable objects.

A dictionary is appropriate when:

- keys are genuinely dynamic;
- the schema is external;
- the value is immediately normalized.

A dictionary is inappropriate when:

- required fields are known;
- multiple packages rely on the same undocumented keys;
- typos would silently create new semantics.

## Units

Physical quantities must use canonical SI units in the domain model unless the
type explicitly states otherwise.

Examples:

- volts;
- amperes;
- seconds;
- hertz;
- meters;
- farads.

Human-facing metadata may use qualified names such as `width_um`, but
normalization must make the unit explicit and deterministic. Never infer units
from a bare numeric value.

## Logging

Library packages do not call `print()`.

Use logging only for operational observability, not semantic results.

Semantic diagnostics belong in returned result objects or raised exceptions.
This keeps tests deterministic and allows CLI, GUI, and API clients to present
the same information differently.

## Technology abstraction

All device physics access goes through the public technology protocol:

```python
solution = technology_model.solve(query)
```

Forbidden outside `openams.technology`:

- reading characterization CSV rows;
- interpolation;
- model checkpoint loading;
- backend comparison logic;
- BSIM-specific calculations.

A technology provider solves device questions. It does not understand circuit
topology.

## Simulation discipline

A simulator receives an assignment and returns results.

It must not:

- resize devices;
- repair biases;
- derive alternative assignments;
- apply optimization steps;
- reinterpret design intent.

A failed simulation is a result with diagnostics, not permission to mutate the
design.

## Optimization discipline

Optimization is a routing choice, not the default pipeline.

```text
resolved assignment   -> simulation
unresolved assignment -> optimization -> simulation
```

The optimizer may propose values only for variables explicitly marked
unresolved by planning.

## Testing

Every package includes:

1. invariant tests;
2. failure-path tests;
3. public API tests;
4. boundary tests;
5. deterministic examples.

Test filenames must be globally unique because test directories are not
required to be Python packages.

Preferred naming:

```text
test_model_public_api.py
test_metadata_public_api.py
test_topology_public_api.py
```

Avoid repeating `test_public_api.py` in multiple directories.

## Dependency tests

An AST-based architecture test should scan imports without importing packages.
This catches violations even when optional runtime dependencies are absent.

The test policy must match `04_LAYER_DEPENDENCIES.md`.

## Type design

Use:

- enums for closed vocabularies;
- protocols for replaceable behavior;
- dataclasses for immutable values;
- explicit union types for genuine alternatives.

Avoid inheritance hierarchies used only to share implementation. Prefer
composition and protocols.

## Complexity limits

Line counts are signals, not laws.

Review a module when it exceeds roughly 300-400 lines or when one class owns
multiple transformations. Split by responsibility, not arbitrary size.

A package should not become a second application hidden below the CLI.

## Provenance

Derived objects should retain stable provenance identifiers where needed for
auditability:

- source assignment identifier;
- technology provider identifier;
- model/table version;
- analysis identifier;
- simulator backend and version.

Provenance is data, not logging.

## Reproducibility

Any nondeterministic algorithm must accept an explicit seed.

Input order must not alter semantic results unless ordering is part of the
domain.

Serialize canonical objects in stable key order where practical.

## Backward compatibility

During the rebuild, obsolete metadata shapes should be rejected explicitly
rather than guessed.

A migration may provide a dedicated converter, but the canonical
normalization path accepts one schema. Silent compatibility branches recreate
the ambiguity the rebuild is intended to remove.

## Review checklist

Before merging an implementation slice, verify:

- [ ] package ownership matches the architecture documents;
- [ ] no forbidden imports;
- [ ] no circular imports;
- [ ] public API is explicit;
- [ ] objects preserve invariants;
- [ ] external dependencies remain in their owning adapter package;
- [ ] tests cover success and failure paths;
- [ ] test filenames are globally unique;
- [ ] `python -m pytest -q` passes;
- [ ] `python -m compileall -q src tests` passes;
- [ ] working tree is clean after the commit.
