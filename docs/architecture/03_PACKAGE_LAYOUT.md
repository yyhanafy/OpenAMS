# OpenAMS Package Layout

## Purpose

This document defines the source-code package structure for the OpenAMS rebuild.

The package layout translates the core object model and interaction model into a
small set of responsibilities with explicit dependency boundaries.

The goals are:

- one canonical architecture;
- one clear home for every responsibility;
- no topology-specific solver packages;
- no simulator or technology details leaking into the core model;
- no circular dependencies;
- simple navigation for developers and LLM-based agents.

---

# 1. Target source tree

```text
src/openams/
├── __init__.py
├── model/
├── metadata/
├── topology/
├── constraints/
├── synthesis/
├── technology/
├── simulation/
├── evaluation/
├── optimization/
├── io/
└── cli/
```

The initial implementation may create only the packages currently needed.

Empty speculative packages should not be added merely to match this diagram.

---

# 2. Dependency direction

The intended dependency direction is:

```text
model
  ↑
metadata
  ↑
topology
  ↑
constraints
  ↑
synthesis
  ↑
simulation
  ↑
evaluation
  ↑
optimization
```

This diagram expresses conceptual dependency direction, not mandatory linear
execution.

Supporting packages such as `io` and `cli` sit at the outer boundary.

A more precise view is:

```text
                    cli
                     |
                     v
 metadata  topology  synthesis  simulation  evaluation  optimization
      \        |         |          |           |           /
       \       |         |          |           |          /
        +-------+---------+----------+-----------+---------+
                                |
                                v
                              model

technology is called through interfaces defined by model or technology,
and is consumed by synthesis and optimization.

io serializes model objects and run artifacts but does not own domain logic.
```

---

# 3. Fundamental dependency rules

## Rule 1

`model` depends only on the Python standard library.

## Rule 2

No package may import from `cli`.

## Rule 3

No package may import simulator-specific code except `simulation`.

## Rule 4

No package may access technology tables or ML models except `technology`.

## Rule 5

`synthesis` accesses device behavior only through the canonical technology
interface.

## Rule 6

`evaluation` consumes normalized results and specifications. It does not invoke
the simulator.

## Rule 7

`optimization` orchestrates existing synthesis, technology, simulation, and
evaluation interfaces. It does not duplicate them.

## Rule 8

`io` serializes and deserializes objects. It does not make design decisions.

## Rule 9

`cli` is a thin adapter. It does not contain domain algorithms.

## Rule 10

Circular imports are prohibited.

---

# 4. Package: model

## One-sentence responsibility

Defines the canonical OpenAMS domain objects and their basic validation.

## Owns

- `Circuit`
- `Node`
- `Terminal`
- `Device`
- `Variable`
- `Constraint`
- `Assignment`
- `DeviceQuery`
- `DeviceSolution`
- `Analysis`
- `SimulationResult`
- `Specification`
- `EvaluationResult`
- shared enums and scalar value types
- object-level invariants

## Must not own

- SPICE parsing;
- YAML loading;
- topology inference;
- constraint compilation;
- assignment search;
- technology interpolation;
- simulator execution;
- specification scoring;
- command-line behavior.

## Initial internal layout

```text
model/
├── __init__.py
├── circuit.py
├── variable.py
├── constraint.py
├── assignment.py
├── technology.py
├── analysis.py
├── result.py
└── specification.py
```

This may be reduced further if fewer files improve clarity.

## Public API

The public objects should be importable from:

```python
from openams.model import Circuit, Device, Node
```

Callers should not need to know the internal file containing each class.

---

# 5. Package: metadata

## One-sentence responsibility

Loads, validates, and normalizes user-supplied OpenAMS metadata.

## Owns

- metadata schema versions;
- YAML or JSON loading;
- canonical metadata field names;
- metadata validation;
- unit normalization at input boundaries;
- active technology configuration selection;
- input-path validation;
- validated configuration objects.

## Must not own

- circuit topology;
- device physics;
- KCL generation;
- assignment synthesis;
- simulator execution;
- performance evaluation.

## Initial internal layout

```text
metadata/
├── __init__.py
├── loader.py
├── validation.py
├── schema.py
└── technology_config.py
```

## Canonical technology metadata

The rebuild uses:

```yaml
active_technology_table: sky130_tt_27c

technology_tables:
  sky130_tt_27c:
    provider: mos_inverse_table
    path: ...
```

The old top-level `technology:` structure is not supported.

## Public API

Conceptually:

```python
from openams.metadata import load_project_inputs, validate_project_inputs
```

---

# 6. Package: topology

## One-sentence responsibility

Builds canonical circuit connectivity from a source netlist.

## Owns

- supported SPICE element parsing;
- terminal-order normalization;
- node creation;
- device creation;
- source extraction;
- flat-circuit connectivity validation;
- source-line provenance.

## Must not own

- analog function recognition;
- design intent;
- device sizing;
- KCL solution;
- technology lookup;
- simulation;
- optimization.

## Initial internal layout

```text
topology/
├── __init__.py
├── spice_parser.py
├── builder.py
└── validation.py
```

## Important rule

The topology package records what is connected.

It does not label a device group as an input stage, current mirror, folded
branch, or second stage.

## Public API

Conceptually:

```python
from openams.topology import parse_spice_circuit
```

---

# 7. Package: constraints

## One-sentence responsibility

Compiles topology, design intent, and design rules into canonical constraints.

## Owns

- topology-derived terminal-voltage constraints;
- KCL constraints;
- design-intent compilation;
- design-rule compilation;
- canonical expression representation;
- constraint provenance;
- dependency extraction;
- dependency-cycle diagnostics.

## Must not own

- technology data;
- simulator execution;
- optimizer search;
- topology-specific solving algorithms;
- result scoring.

## Initial internal layout

```text
constraints/
├── __init__.py
├── expression.py
├── topology.py
├── intent.py
├── rules.py
├── dependency.py
└── validation.py
```

## Important rule

Constraints are data.

A topology-specific equation may appear in metadata or be derived from actual
connectivity, but it must not be embedded as a special Python branch for one
named circuit.

## Public API

Conceptually:

```python
from openams.constraints import (
    compile_design_intent,
    compile_design_rules,
    compile_topology_constraints,
    build_dependency_plan,
)
```

---

# 8. Package: synthesis

## One-sentence responsibility

Produces physically consistent DC assignments from variables, constraints, and
technology queries.

## Owns

- independent-value enumeration;
- constant application;
- direct equality propagation;
- derived-expression evaluation;
- assignment completion;
- technology-query issuance;
- consistency checks;
- resolved, unresolved, and rejected routing;
- synthesis diagnostics.

## Must not own

- netlist parsing;
- technology backend implementation;
- ngspice execution;
- specification scoring;
- optimizer algorithms;
- topology-specific stage solvers.

## Initial internal layout

```text
synthesis/
├── __init__.py
├── planner.py
├── enumerator.py
├── propagator.py
├── solver.py
├── classification.py
└── diagnostics.py
```

The initial implementation may combine these into fewer files.

## Important rule

There must be no equivalent of:

```text
intersection.py
second_stage_intersection.py
```

for a particular topology.

The generic synthesis engine consumes the dependency plan and canonical
constraints.

## Public API

Conceptually:

```python
from openams.synthesis import synthesize_assignments
```

---

# 9. Package: technology

## One-sentence responsibility

Answers canonical physical device-behavior queries using the active backend.

## Owns

- `TechnologyModel` implementations;
- provider selection;
- table loading;
- interpolation;
- inverse device solving;
- MLP loading and inference;
- compare mode;
- model-domain validation;
- technology diagnostics.

## Must not own

- circuit topology;
- design-variable classification;
- KCL;
- system-level specification checks;
- ngspice circuit simulation;
- optimizer policy.

## Initial internal layout

```text
technology/
├── __init__.py
├── interface.py
├── config.py
├── query.py
├── table/
│   ├── __init__.py
│   ├── loader.py
│   └── mos.py
├── mlp/
│   ├── __init__.py
│   └── mos.py
└── compare.py
```

Only the required backend should be implemented initially.

## Public API

Conceptually:

```python
from openams.technology import build_technology_model
```

The returned object satisfies the canonical technology interface.

---

# 10. Package: simulation

## One-sentence responsibility

Renders, executes, and normalizes simulator analyses for resolved assignments.

## Owns

- simulator adapter interface;
- ngspice netlist rendering;
- simulator process execution;
- timeout handling;
- output extraction;
- normalized result creation;
- raw artifact references;
- simulation diagnostics.

## Must not own

- assignment search;
- design repair;
- technology interpolation;
- specification acceptance;
- optimization policy.

## Initial internal layout

```text
simulation/
├── __init__.py
├── interface.py
├── runner.py
├── rendering.py
├── extraction.py
└── ngspice/
    ├── __init__.py
    ├── adapter.py
    ├── renderer.py
    └── parser.py
```

The initial implementation may use a simpler flat layout.

## Important rule

The simulator adapter verifies the provided assignment.

It must not silently alter transistor dimensions, bias values, or other design
choices to obtain convergence or a passing result.

## Public API

Conceptually:

```python
from openams.simulation import build_simulator
```

---

# 11. Package: evaluation

## One-sentence responsibility

Compares normalized simulation results against specifications.

## Owns

- metric lookup;
- unit-compatible comparisons;
- required pass or fail;
- preferred-condition reporting;
- objective normalization;
- score calculation;
- rejection reasons;
- evaluation summaries.

## Must not own

- simulator invocation;
- netlist rendering;
- topology;
- technology queries;
- candidate generation.

## Initial internal layout

```text
evaluation/
├── __init__.py
├── evaluator.py
├── comparison.py
└── scoring.py
```

## Public API

Conceptually:

```python
from openams.evaluation import evaluate_result
```

---

# 12. Package: optimization

## One-sentence responsibility

Explores unresolved design ranges using the canonical synthesis, simulation, and
evaluation interfaces.

## Owns

- unresolved search-space construction;
- candidate proposal;
- optimizer state;
- exploration and exploitation policy;
- optimization history;
- stopping criteria;
- candidate ranking.

## Must not own

- duplicate constraint evaluation;
- direct technology table access;
- duplicate simulator code;
- topology-specific search paths;
- separate result semantics.

## Initial internal layout

```text
optimization/
├── __init__.py
├── interface.py
├── search_space.py
├── objective.py
└── strategies/
```

The package should not be implemented until unresolved assignments genuinely
require it.

## Important rule

Optimization is optional.

Resolved assignments bypass this package entirely.

---

# 13. Package: io

## One-sentence responsibility

Serializes, deserializes, and organizes canonical OpenAMS artifacts.

## Owns

- JSON serialization;
- canonical object decoding;
- run manifest writing;
- artifact path management;
- CSV export for human inspection;
- stable output naming.

## Must not own

- metadata semantics;
- circuit solving;
- technology queries;
- simulator execution;
- evaluation decisions.

## Initial internal layout

```text
io/
├── __init__.py
├── json.py
├── manifest.py
├── artifacts.py
└── csv.py
```

## Important rule

JSON is the preferred canonical machine-readable format.

CSV is a derived inspection format, not the source of truth.

---

# 14. Package: cli

## One-sentence responsibility

Maps command-line requests to the public Python API.

## Owns

- argument parsing;
- command dispatch;
- human-readable console output;
- process exit codes;
- file-path resolution at the command boundary.

## Must not own

- metadata validation algorithms;
- topology parsing algorithms;
- synthesis algorithms;
- technology solving;
- simulation extraction;
- evaluation rules;
- optimization logic.

## Initial internal layout

```text
cli/
├── __init__.py
├── main.py
└── commands/
    ├── validate.py
    ├── inspect.py
    └── run.py
```

## Canonical CLI direction

The long-term canonical command is:

```bash
openams run   --netlist circuit.spice   --specs specs.yaml   --intent design_intent.yaml   --rules design_rules.yaml   --simulation simulation.yaml
```

Multiple internal library stages may exist, but the user should not be required
to manually execute a long chain of unrelated commands for a standard run.

Diagnostic subcommands may still expose intermediate stages.

---

# 15. Root package API

`openams/__init__.py` should remain small.

It may expose:

- package version;
- a small number of stable high-level entry points.

It should not import the entire package tree eagerly.

Example future API:

```python
from openams import run_project
```

Detailed objects remain available through their owning packages:

```python
from openams.model import Circuit
from openams.topology import parse_spice_circuit
from openams.synthesis import synthesize_assignments
```

---

# 16. Allowed dependency matrix

The following matrix describes normal allowed imports.

| Package | May import |
|---|---|
| model | standard library only |
| metadata | model |
| topology | model |
| constraints | model |
| synthesis | model, constraints, technology |
| technology | model |
| simulation | model |
| evaluation | model |
| optimization | model, constraints, synthesis, technology, simulation, evaluation |
| io | model |
| cli | all public package APIs |

Some narrow exceptions may be accepted when documented, but no exception may
create a circular dependency.

---

# 17. Prohibited dependencies

The following imports are prohibited:

```text
model -> any OpenAMS package
technology -> synthesis
technology -> topology
simulation -> synthesis
simulation -> optimization
evaluation -> simulation implementation
constraints -> technology implementation
topology -> metadata-specific YAML structures
io -> synthesis algorithms
any package -> cli
```

The following behavioral dependencies are also prohibited:

- synthesis reading technology CSV files directly;
- constraints invoking ngspice;
- simulation evaluating performance specifications;
- optimization implementing a second constraint system;
- CLI scripts containing domain equations.

---

# 18. Interface placement

Interfaces should be owned by the domain that defines the contract.

Examples:

- technology query contract: `model` or `technology`;
- simulator adapter contract: `simulation`;
- optimizer strategy contract: `optimization`;
- serialization protocol: `io`.

The consumer must not define private assumptions about a provider.

---

# 19. Builders versus immutable objects

Core domain objects should be immutable after construction.

Packages may use private mutable builders internally.

Examples:

```text
topology._CircuitBuilder
constraints._ConstraintBuilder
synthesis._AssignmentState
```

Private builders:

- are not part of the public API;
- may mutate during one operation;
- must produce validated immutable public objects;
- must not leak across package boundaries.

---

# 20. Exceptions and diagnostics

Each package owns its exception hierarchy.

Conceptually:

```text
OpenAMSError
├── MetadataError
├── TopologyError
├── ConstraintError
├── SynthesisError
├── TechnologyError
├── SimulationError
├── EvaluationError
└── OptimizationError
```

However, ordinary candidate rejection should generally be represented as
structured diagnostics rather than raised as an exception.

Exceptions are for failures that prevent the requested operation from
continuing.

---

# 21. Testing layout

Tests mirror the source tree.

```text
tests/
├── model/
├── metadata/
├── topology/
├── constraints/
├── synthesis/
├── technology/
├── simulation/
├── evaluation/
├── optimization/
├── io/
└── integration/
```

Not every directory must be created immediately.

## Unit tests

Each package tests its own behavior with minimal external dependencies.

## Contract tests

Provider interfaces should have shared tests.

Examples:

- all technology models satisfy the same query contract;
- all simulator adapters produce normalized results;
- all serializers preserve canonical object identity.

## Integration tests

Integration tests verify canonical paths such as:

```text
netlist
 -> circuit
 -> constraints
 -> assignments
 -> simulation
 -> evaluation
```

## Topology-generic acceptance tests

At least two materially different circuits must pass through the same APIs:

- two-stage op-amp;
- folded-cascode OTA.

---

# 22. Example-project layout

Examples should be data-driven demonstrations, not hidden production code.

```text
examples/
├── two_stage_opamp/
│   ├── inputs/
│   ├── expected/
│   └── README.md
└── folded_cascode/
    ├── inputs/
    ├── expected/
    └── README.md
```

Example directories may contain:

- netlists;
- metadata;
- expected normalized outputs;
- execution notes.

They must not contain topology-specific Python solvers.

---

# 23. Tools layout

`tools/` contains developer utilities that are not part of the stable OpenAMS
library API.

Examples:

- technology characterization scripts;
- model-training scripts;
- repository audits;
- artifact inspection utilities;
- migration helpers.

A tool may import the public OpenAMS API.

Production packages must not import from `tools`.

---

# 24. Generated-artifact layout

Generated files belong outside `src/`.

Recommended layout:

```text
runtime/
└── <run_id>/
    ├── manifest.json
    ├── inputs/
    ├── topology/
    ├── constraints/
    ├── synthesis/
    ├── simulation/
    ├── evaluation/
    └── optimization/
```

The exact layout may evolve.

The run manifest remains the artifact index.

Generated directories are not imported as Python packages.

---

# 25. Naming conventions

## Modules

Use lowercase names with underscores only when needed.

Examples:

```text
spice_parser.py
technology_config.py
search_space.py
```

## Classes

Use descriptive singular nouns.

Examples:

```text
Circuit
Assignment
TechnologyModel
SimulationResult
```

## Functions

Use verbs describing one action.

Examples:

```text
parse_spice_circuit
compile_design_rules
synthesize_assignments
evaluate_result
```

## Avoid vague names

Avoid names such as:

```text
manager
helper
processor
common
misc
utils
engine
```

unless the module truly has a narrow and obvious meaning.

A file named `engine.py` is discouraged because it tends to accumulate unrelated
responsibilities.

---

# 26. Public and private names

Public names are intentionally exported through package `__init__.py` files.

Private implementation details begin with an underscore or remain unexported.

Example:

```python
# openams/topology/__init__.py

from .spice_parser import parse_spice_circuit

__all__ = ["parse_spice_circuit"]
```

Callers should import public names from package boundaries rather than deep
implementation modules whenever practical.

---

# 27. Dependency enforcement

The initial project may enforce boundaries through:

- code review;
- tests;
- simple import audits.

A future dependency checker may be added only if violations become difficult to
control manually.

Do not add architectural tooling before it provides clear value.

---

# 28. Initial implementation subset

The first production implementation should create only:

```text
src/openams/
├── __init__.py
└── model/
    ├── __init__.py
    ├── circuit.py
    ├── variable.py
    ├── constraint.py
    ├── assignment.py
    ├── technology.py
    ├── analysis.py
    ├── result.py
    └── specification.py
```

Corresponding tests:

```text
tests/
└── model/
```

No other package should be created until the model package is stable enough to
support it.

---

# 29. Acceptance criteria

The package layout is acceptable when:

1. every responsibility has one clear owner;
2. no production module is topology-specific;
3. `model` depends only on the standard library;
4. technology backends are isolated under `technology`;
5. simulator-specific code is isolated under `simulation`;
6. optimization reuses synthesis, simulation, and evaluation;
7. the CLI contains no domain algorithms;
8. tests mirror source responsibilities;
9. example circuits contain data rather than solver code;
10. a new developer can identify the correct package for a change without
    reading the full codebase.

---

# 30. Central package rule

Every module must answer one primary question.

Every package must own one coherent responsibility.

When code appears to belong in two packages, the boundary or object contract
must be clarified before the code is added.
