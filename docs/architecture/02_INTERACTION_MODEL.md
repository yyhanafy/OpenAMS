# OpenAMS Interaction Model

## Purpose

This document defines how the canonical OpenAMS objects collaborate at runtime.

The core object model defines what each object is.

This interaction model defines:

- who creates each object;
- who may modify it;
- how information flows through the system;
- when technology queries occur;
- when simulation occurs;
- when optimization is required;
- where rejection decisions are made.

The objective is one simple and canonical execution path.

---

# 1. Governing runtime rule

OpenAMS progressively enriches a circuit description until it becomes a verified
design result.

The canonical flow is:

```text
Inputs
  |
  v
Metadata validation
  |
  v
Topology extraction
  |
  v
Constraint compilation
  |
  v
Assignment synthesis
  |
  +------------------------+
  |                        |
  v                        v
Resolved assignments   Unresolved assignments
  |                        |
  v                        v
Direct simulation       Optimization
  |                        |
  |                        v
  |                  Resolved candidates
  |                        |
  +-----------+------------+
              |
              v
         Simulation
              |
              v
          Evaluation
              |
              v
     Accepted or rejected results
```

There must not be separate execution pipelines for individual topologies.

Topology-specific knowledge is supplied as data through the circuit, design
intent, and design rules.

---

# 2. External inputs

The initial OpenAMS execution consumes:

- a SPICE netlist;
- specifications metadata;
- design intent metadata;
- design rules metadata;
- simulation metadata;
- active technology configuration.

These inputs are external representations.

They are not the canonical internal model.

Each input is parsed and normalized before entering the core system.

---

# 3. Metadata validation

## Responsibility

The metadata validator answers:

> Are the provided inputs structurally complete and internally consistent?

## Inputs

- raw metadata documents;
- file references;
- schema versions.

## Outputs

- validated immutable configuration objects;
- validation diagnostics.

## Validation includes

- required keys;
- valid schema version;
- canonical field names;
- referenced files exist;
- active technology table exists;
- technology provider is supported;
- units are valid;
- rule identifiers are unique;
- specification identifiers are unique.

## Validation does not include

- transistor physics;
- DC operating-point feasibility;
- topology inference;
- simulator execution;
- specification pass or fail.

Invalid metadata stops the pipeline before topology extraction.

---

# 4. Topology extraction

## Responsibility

The topology extractor answers:

> What devices and electrical connections exist in the netlist?

## Inputs

- validated netlist reference;
- parser configuration.

## Outputs

- a canonical `Circuit` containing:
  - nodes;
  - devices;
  - terminals;
  - fixed netlist parameters;
  - source definitions.

## Process

The parser:

1. reads the SPICE netlist;
2. identifies supported elements;
3. normalizes terminal names;
4. creates canonical nodes;
5. creates canonical devices;
6. creates parameter variables;
7. preserves source provenance;
8. validates connectivity.

## Important boundary

Topology extraction records what is explicitly connected.

It does not infer analog functions such as:

- differential pair;
- current mirror;
- input stage;
- output stage;
- folded branch;
- cascode branch.

Those meanings belong in design intent or in a later optional recognition layer.

## Immutability

After successful topology extraction, device and node identity are immutable.

Later stages may add variables and constraints, but they must not silently
rewrite connectivity.

---

# 5. Circuit enrichment

The canonical `Circuit` is progressively enriched.

The stages are:

```text
Topology Circuit
      |
      v
Intent-enriched Circuit
      |
      v
Rule-enriched Circuit
      |
      v
Constraint-complete Circuit
```

Each stage returns a new circuit value or a well-defined enriched model.

The initial implementation should prefer immutable dataclasses and replacement
over uncontrolled mutation.

---

# 6. Design intent compilation

## Responsibility

The design intent compiler answers:

> What relationships are intended by the circuit designer?

## Inputs

- topology circuit;
- validated design intent metadata.

## Outputs

- canonical variables;
- canonical constraints;
- optional named device groups;
- optional named current groups;
- optional matching groups.

## Examples

Design intent may declare:

```text
M1 and M2 form a matched pair
M3 and M4 form a current mirror
M1 width equals M2 width
M3 width equals M4 width
I1 equals I2
```

These declarations become canonical constraints.

## Important rule

Design intent describes circuit-specific meaning as data.

It must not trigger topology-specific Python solver paths.

## Named groups

Named groups may improve readability, but they are not special core classes.

For example:

```text
group.input_pair = [M1, M2]
group.active_load = [M3, M4]
```

The synthesis engine consumes the constraints generated from these groups, not
the group names themselves.

---

# 7. Design rule compilation

## Responsibility

The design rule compiler answers:

> What values and relationships are allowed?

## Inputs

- intent-enriched circuit;
- validated design rules metadata.

## Outputs

- fixed-value constraints;
- range constraints;
- equality constraints;
- derived-expression constraints;
- technology-query requirements;
- variable-role assignments.

## Examples

```text
device.M1.length = 0.5e-6
device.M1.width == device.M2.width
node.vout.voltage in [0.5, 2.0]
device.M1.region.saturated == true
```

## Variable classification

At synthesis time, variables may be classified as:

- constant;
- independent;
- derived;
- technology_solved.

At simulation time, additional variables may be:

- simulator_measured;
- objective.

Classification is contextual.

It is not a permanent physical property of the quantity.

## Important rule

Fully resolved assignments bypass executable-contract generation.

Executable contracts or optimizer search spaces are created only when unresolved
ranges remain after synthesis.

---

# 8. Topology-derived constraints

## Responsibility

The topology constraint compiler answers:

> Which electrical relationships follow directly from connectivity?

## Inputs

- canonical circuit topology.

## Outputs

- KCL constraints;
- terminal-voltage definitions;
- source constraints;
- optional device-current sign conventions.

## Examples

For a node:

```text
sum(currents entering node) = 0
```

For an NMOS transistor:

```text
device.M1.voltage.vgs =
    node.<gate>.voltage - node.<source>.voltage

device.M1.voltage.vds =
    node.<drain>.voltage - node.<source>.voltage

device.M1.voltage.vbs =
    node.<bulk>.voltage - node.<source>.voltage
```

For a PMOS transistor, canonical signed terminal voltages remain consistent with
the same terminal definitions.

Absolute-value or polarity-specific quantities may be introduced only at the
technology-query boundary.

## Important rule

The compiler derives equations from actual connectivity.

It must not contain concepts such as left branch or second stage.

---

# 9. Constraint set

After all compilation stages, OpenAMS has one canonical constraint set.

Constraint sources include:

- topology;
- KCL;
- terminal relations;
- design intent;
- design rules;
- fixed operating conditions;
- technology requirements;
- simulation requirements.

Every constraint must retain provenance.

Example provenance:

```text
source_type: design_rule
source_file: design_rules.yaml
source_id: input_pair_match
```

This allows diagnostics to explain why a candidate was accepted or rejected.

---

# 10. Dependency planning

## Responsibility

The dependency planner answers:

> In what order can variables be assigned or solved?

## Inputs

- canonical variables;
- canonical constraints.

## Outputs

- dependency graph;
- independent-variable set;
- derivation order;
- technology-query order;
- unresolved cycles;
- diagnostics.

## Process

The planner:

1. identifies constants;
2. identifies explicit independent ranges;
3. identifies direct equalities;
4. identifies algebraic dependencies;
5. identifies technology-solved variables;
6. identifies KCL-dependent quantities;
7. detects circular dependencies;
8. creates a solve order.

## Important rule

Variable independence is derived from the available constraints and selected
synthesis strategy.

It is not hard-coded by transistor name.

## Cycles

Some valid physical systems contain simultaneous equations.

The initial implementation may reject unsupported cycles with clear diagnostics.

A later solver may handle simultaneous nonlinear systems.

Simplicity takes priority over prematurely supporting every case.

---

# 11. Assignment synthesis

## Responsibility

The assignment synthesizer answers:

> Which physically consistent DC assignments satisfy the compiled constraints?

## Inputs

- constraint-complete circuit;
- dependency plan;
- active technology model.

## Outputs

- resolved assignments;
- unresolved assignments;
- rejected assignments;
- diagnostics.

## Canonical procedure

For each independent-variable combination:

1. create a partial assignment;
2. apply constants;
3. apply selected independent values;
4. propagate direct equalities;
5. evaluate derived expressions;
6. derive terminal voltages;
7. apply KCL relationships;
8. issue required technology queries;
9. insert technology-solved values;
10. re-evaluate dependent constraints;
11. reject inconsistent assignments;
12. classify the surviving assignment.

## Assignment classifications

### Resolved

All values required for simulation are known.

Route:

```text
resolved assignment -> direct simulation
```

### Unresolved

One or more required quantities remain ranged or undecided.

Route:

```text
unresolved assignment -> optimization
```

### Rejected

One or more required constraints cannot be satisfied.

Route:

```text
rejected assignment -> diagnostics only
```

---

# 12. Technology query interaction

## Query creator

The synthesis layer creates a `DeviceQuery`.

The technology layer does not inspect the entire circuit.

## Inputs to a query

A query may include:

- device kind;
- polarity;
- model;
- known terminal voltages;
- known current;
- known geometry;
- temperature;
- process corner;
- requested unknowns;
- operating-region requirements.

## Output

The technology model returns a `DeviceSolution`.

## Example interaction

```text
Assignment Synthesizer
        |
        | DeviceQuery:
        | L, VGS, VDS, VBS, ID
        | solve_for = width
        v
TechnologyModel
        |
        | DeviceSolution:
        | width, validity, diagnostics
        v
Assignment Synthesizer
```

## Important boundaries

The synthesis layer must not:

- read technology CSV files directly;
- call MLP models directly;
- know interpolation details;
- know whether compare mode is active.

The technology layer must not:

- decide circuit topology;
- select design independent variables;
- evaluate system specifications;
- run circuit simulation.

---

# 13. Technology validity

A technology solution may be invalid because:

- the query is outside characterized bounds;
- no width satisfies the requested current;
- the operating-region condition fails;
- interpolation is unsupported;
- the active model reports low confidence;
- multiple incompatible solutions exist.

An invalid technology solution rejects only the current candidate assignment.

It does not invalidate the entire circuit unless all candidates fail.

Diagnostics must identify:

- device;
- query values;
- requested unknown;
- failure reason;
- technology backend.

---

# 14. Optimization routing

## Responsibility

Optimization answers:

> Which choices within unresolved ranges best satisfy the objectives?

## Inputs

- unresolved assignment template;
- unresolved variable ranges;
- circuit;
- constraints;
- technology model;
- simulation configuration;
- objectives.

## Outputs

- resolved candidate assignments;
- optimization history;
- diagnostics.

## Important rule

Optimization is conditional, not mandatory.

It is used only when synthesis leaves meaningful unresolved ranges.

A fully resolved assignment must not pass through optimization merely because an
optimizer exists.

## Optimizer boundary

The optimizer proposes values.

It does not own:

- topology;
- physical constraints;
- technology behavior;
- simulation interpretation;
- specification definitions.

Every optimizer proposal must pass through the same synthesis completion and
constraint checks used outside optimization.

---

# 15. Simulation readiness

An assignment is simulation-ready when all required netlist quantities are known.

For the initial MOS implementation, this normally includes:

- model identity;
- device length;
- device width;
- source values;
- required fixed parameters;
- analysis configuration.

Expected node voltages and device currents may be present as synthesis
predictions, but ngspice remains the reference verifier.

The simulation layer must not silently invent missing design values.

---

# 16. Simulation interaction

## Responsibility

The simulator adapter answers:

> What does the reference simulator report for this assignment?

## Inputs

- canonical circuit;
- simulation-ready assignment;
- requested analyses;
- simulator configuration.

## Outputs

- normalized `SimulationResult`;
- raw artifact references;
- execution diagnostics.

## Canonical sequence

```text
Circuit + Assignment + Analysis
              |
              v
        Netlist Renderer
              |
              v
       Simulator Executor
              |
              v
        Result Extractor
              |
              v
      Normalized SimulationResult
```

## Simulator adapter responsibilities

- render device values;
- render sources;
- render analysis commands;
- execute the simulator;
- detect execution failure;
- extract raw quantities;
- normalize names and units;
- preserve artifact locations.

## Important boundary

The simulator adapter verifies an assignment.

It does not change the assignment to make it pass.

---

# 17. Simulation failure

Simulation failure and design failure are different.

## Simulation failure examples

- ngspice cannot start;
- netlist rendering fails;
- convergence fails;
- output files are missing;
- result parsing fails.

## Design failure examples

- transistor not saturated;
- output voltage outside the allowed range;
- gain below target;
- phase margin below target;
- power above target.

Simulation infrastructure failures belong in `SimulationResult.diagnostics`.

Design failures belong in evaluation results.

---

# 18. Evaluation interaction

## Responsibility

The evaluator answers:

> Does the normalized simulation result satisfy the specifications?

## Inputs

- simulation result;
- specification set.

## Outputs

- `EvaluationResult`.

## Canonical sequence

For each specification:

1. locate the normalized result variable;
2. verify units;
3. apply the comparison relation;
4. record pass or fail;
5. compute optional normalized margin;
6. aggregate required checks;
7. compute optional score.

## Acceptance

An assignment is accepted only when:

- simulation succeeded;
- every required specification passed;
- no required operating condition failed.

Preferred and objective specifications influence ranking but do not necessarily
control acceptance.

---

# 19. Provenance and diagnostics

Every major generated object must preserve provenance.

Examples:

- which metadata rule created a constraint;
- which independent values created an assignment;
- which technology query solved a width;
- which simulator run produced a metric;
- which specification rejected a result.

Diagnostics must be structured data first and human-readable text second.

This makes the system usable by:

- developers;
- command-line users;
- automated workflows;
- LLM-based agents.

---

# 20. Mutation policy

The preferred policy is immutable core objects.

## Immutable after creation

- Node identity;
- Device identity;
- Terminal connectivity;
- Variable identity;
- Constraint identity;
- Specification identity.

## New values rather than mutation

Each stage should produce a new value:

```text
raw metadata
    -> validated configuration

netlist
    -> topology circuit

topology circuit
    -> constraint-complete circuit

partial assignment
    -> resolved assignment

resolved assignment
    -> simulation result

simulation result
    -> evaluation result
```

Controlled internal mutation may be used inside a builder or solver for
efficiency, but mutable intermediate state must not leak through public
interfaces.

---

# 21. Error ownership

Each layer reports only errors it owns.

## Metadata layer

- malformed metadata;
- missing required fields;
- unsupported schema.

## Topology layer

- unsupported netlist element;
- invalid terminal count;
- missing node reference.

## Constraint layer

- unknown variable;
- duplicate constraint;
- invalid expression;
- dependency cycle.

## Synthesis layer

- inconsistent assignments;
- unresolved required variables;
- constraint failure.

## Technology layer

- query outside model domain;
- no device solution;
- backend failure.

## Simulation layer

- rendering failure;
- execution failure;
- convergence failure;
- extraction failure.

## Evaluation layer

- missing metric;
- unit mismatch;
- specification failure.

Errors must not be silently reclassified by downstream layers.

---

# 22. Initial runtime interfaces

The initial implementation should converge toward interfaces equivalent to:

```python
validated = validate_inputs(input_paths)

circuit = extract_topology(validated.netlist)

circuit = compile_design_intent(
    circuit,
    validated.design_intent,
)

circuit = compile_design_rules(
    circuit,
    validated.design_rules,
)

circuit = compile_topology_constraints(circuit)

plan = build_dependency_plan(circuit)

synthesis_result = synthesize_assignments(
    circuit=circuit,
    plan=plan,
    technology=technology_model,
)

resolved = list(synthesis_result.resolved)

for assignment in resolved:
    simulation_result = simulator.run(
        circuit=circuit,
        assignment=assignment,
        analyses=circuit.analyses,
    )

    evaluation_result = evaluator.evaluate(
        simulation_result=simulation_result,
        specifications=circuit.specifications,
    )
```

Unresolved assignments follow:

```python
for assignment in synthesis_result.unresolved:
    optimized_assignments = optimizer.resolve(
        circuit=circuit,
        assignment=assignment,
        technology=technology_model,
        simulator=simulator,
        evaluator=evaluator,
    )
```

These examples define interaction boundaries, not final API syntax.

---

# 23. Canonical command-line interaction

The eventual canonical CLI should execute the same internal path.

Conceptually:

```bash
openams run   --netlist circuit.spice   --specs specs.yaml   --intent design_intent.yaml   --rules design_rules.yaml   --simulation simulation.yaml
```

The CLI must not duplicate synthesis logic.

It only:

- parses command-line arguments;
- invokes library interfaces;
- writes normalized outputs;
- returns an appropriate exit status.

---

# 24. Output model

A complete run should produce a run manifest referencing:

- validated input snapshot;
- topology representation;
- compiled constraints;
- dependency plan;
- resolved assignments;
- unresolved assignments;
- rejected assignments;
- technology diagnostics;
- simulation results;
- evaluation results;
- optimization history when applicable.

The manifest is the run index.

Generated CSV, JSON, SPICE, and raw simulator files are artifacts referenced by
the manifest, not parallel sources of truth.

---

# 25. Initial implementation sequence

The implementation should proceed in this order:

1. canonical immutable data objects;
2. object validation;
3. serialization;
4. flat SPICE topology extraction;
5. topology-derived terminal constraints;
6. metadata loading and validation;
7. design-intent constraint compilation;
8. design-rule constraint compilation;
9. dependency planning;
10. basic assignment propagation;
11. technology query interface;
12. direct resolved-assignment simulation;
13. evaluation;
14. unresolved-assignment optimization.

Each step must have tests before the next step becomes dependent on it.

---

# 26. Acceptance criteria

The interaction model is acceptable when:

1. one execution path supports both the two-stage op-amp and folded-cascode OTA;
2. no synthesis function refers to topology-specific stage names;
3. synthesis accesses technology only through `TechnologyModel`;
4. fully resolved assignments bypass optimization;
5. unresolved assignments use the same constraints as direct synthesis;
6. simulator adapters do not alter candidate design values;
7. evaluation remains separate from simulation;
8. every rejection has traceable provenance;
9. all core interactions are usable through Python without the CLI;
10. the CLI is a thin adapter over the same Python interfaces.

---

# 27. Central architectural rule

OpenAMS must have one canonical model and one canonical execution path.

Different circuits contribute different topology and constraints.

Different technologies contribute different device models.

Different simulators contribute different adapters.

Different optimizers contribute different search strategies.

None of those differences may create a second OpenAMS architecture.
