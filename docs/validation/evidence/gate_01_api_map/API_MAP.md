# Gate 1 Public API Map

## Summary

- **Gate:** 1
- **Proof:** Public APIs mapped
- **Status:** PASS
- **Scope:** topology, metadata, constraints, technology, synthesis, planning, simulation, optimization

This document records the public contracts that connect the OpenAMS architectural layers. It is not an inventory of every class or helper. It identifies the entry points that other subsystems are expected to call, the data they accept, the objects they return, and the architectural dependency direction.

---

## 1. Topology

### Public entry APIs

```python
from openams.topology import (
    parse_spice_circuit,
    parse_spice_subcircuit,
    extract_spice_subcircuit,
    connected_devices,
    connected_terminals,
    device,
    node,
)
```

### Accepts

- Flat SPICE text through `parse_spice_circuit(text, name=...)`
- One named, single-level `.subckt` through `parse_spice_subcircuit(text, subcircuit=...)`
- Canonical `Circuit` objects for connectivity queries

### Returns

- `openams.model.Circuit`
- `ParsedSubcircuit`
- Canonical device and node query results

### Calls

- Canonical object model in `openams.model`
- SPICE scalar parser and topology records

### Called by

- Metadata-to-topology validation
- Constraint construction
- Synthesis preparation
- End-to-end orchestration

### Current boundary

- Flat circuits are supported directly.
- One named, non-nested subcircuit is supported.
- Recursive nested hierarchy is not yet supported.

---

## 2. Metadata

### Public role

The metadata layer owns normalization and validation of external design data before it is transformed into canonical model objects.

### Primary modules

```text
openams.metadata.model
openams.metadata.normalize
openams.metadata.validation
openams.io.yaml_loader
```

### Accepts

- Parsed YAML mappings
- Design specifications
- Design rules
- Design intent
- Simulation metadata

### Returns

- Normalized immutable metadata objects
- Validation diagnostics
- Canonical mappings suitable for downstream compilation

### Calls

- `openams.io` for loading
- `openams.model` for canonical data structures

### Called by

- Constraint compilation
- Planning
- Simulation manifest construction
- End-to-end application services

### Current boundary

Gate 3 must prove that the archived two-stage metadata is compatible with the current metadata contracts.

---

## 3. Constraints

### Public entry APIs

The package exports immutable constraint models, expression handling, queries, and validation.

### Primary modules

```text
openams.constraints.model
openams.constraints.expressions
openams.constraints.validation
openams.constraints.queries
```

### Accepts

- Canonical variable names
- Constraint expressions
- Constraint collections
- Metadata-derived rules

### Returns

- Validated canonical constraint objects
- Expression representations
- Query results and diagnostics

### Calls

- Canonical model vocabulary

### Called by

- Synthesis constraint compiler
- Planning validation
- Optimization contract construction

### Current boundary

The constraint package defines canonical intent. `openams.synthesis.CircuitConstraintCompiler` translates supported linear equalities into executable region-intersection predicates.

---

## 4. Technology

### Public role

The technology layer provides device behavior and feasible-region data without embedding circuit topology decisions.

### Primary public concepts

```text
Technology backend interface
Technology capabilities
Technology query objects
Table backend
Interpolation backend
Adaptive generation
Feasible-region builder
```

### Accepts

- Device operating-point queries
- Technology table records
- Interpolation coordinates
- Feasibility constraints
- Backend configuration

### Returns

- Technology query responses
- Interpolated device data
- Explicit feasible device regions
- Capability and validation records

### Calls

- Technology table and interpolation internals
- Immutable technology model types

### Called by

- Hierarchical synthesis preparation
- Technology-required planning routes
- Optimization/runtime composition

### Current boundary

The technology layer is unit-tested, but Gate 5 must prove it works with the actual configured two-stage technology data.

---

## 5. Synthesis

### Public entry APIs

```python
from openams.synthesis import (
    CanonicalConstraintRecord,
    CircuitConstraintCompiler,
    RegionBinding,
    SynthesisStage,
    HierarchicalSynthesisWorkflow,
    CircuitRegionAssignmentEmitter,
    FixedAssignmentPolicy,
)
```

### Accepts

- Explicit `RegionInput` device or stage regions
- `RegionBinding` canonical-to-local field mappings
- Canonical linear equality constraints
- Dependency-ordered `SynthesisStage` programs
- Final `CircuitRegion` objects

### Returns

- `CompiledIntersection`
- `SynthesisWorkflowResult`
- `StageResult`
- `CircuitRegion`
- `FixedAssignmentBatch`
- Simulation-ready canonical assignments
- Direct-simulation execution plans for fully resolved rows

### Calls

- `openams.planning.build_execution_plan`
- Region intersection and indexed join engines
- Canonical `Assignment` model

### Called by

- End-to-end synthesis orchestration
- Assignment emission
- Route planning

### Execution path

```text
RegionBinding inputs
    ↓
CircuitConstraintCompiler
    ↓
CompiledIntersection
    ↓
HierarchicalSynthesisWorkflow
    ↓
CircuitRegion
    ↓
CircuitRegionAssignmentEmitter
    ↓
FixedAssignmentBatch
```

### Current boundary

The workflow is proven with synthetic regions in tests. Gates 4–6 must prove the same path using real metadata and technology-derived regions.

---

## 6. Planning

### Public entry API

```python
from openams.planning import build_execution_plan
```

### Accepts

- `PlanningRequest`
- Variable set
- Resolved values
- Synthesis-independent variables
- Optimization-independent variables
- Technology-required variables
- Simulation and specification-verification requirements

### Returns

- Immutable `ExecutionPlan`
- Variable-role classification
- Ordered execution stages
- Selected `ExecutionRoute`

### Route logic

```text
synthesis + optimization → SYNTHESIS_THEN_OPTIMIZATION
synthesis only           → TECHNOLOGY_SYNTHESIS
optimization only        → OPTIMIZATION
resolved + simulation    → DIRECT_SIMULATION
otherwise                → VALIDATION_ONLY
```

### Calls

- Planning validation

### Called by

- Assignment emitter
- Optimization application services
- Final orchestration

### Current boundary

Planning classifies work; it does not perform synthesis, optimization, or simulation.

---

## 7. Simulation

### Public entry APIs

```python
from openams.simulation import (
    DirectSimulationManifestBuilder,
    DirectSimulationInput,
    SimulationManifest,
    SimulationRunRequest,
    SimulationTemplate,
)
```

Additional workflow/runtime APIs:

```python
from openams.simulation.ngspice import NgspiceRunner
from openams.simulation.workflow import (
    SimulationWorkflow,
    build_ngspice_workflow,
)
```

### Accepts

- Simulation-ready assignments and execution plans
- SPICE templates
- Backend-neutral run requests
- Measurement declarations
- Specification rules

### Returns

- Simulation manifests
- Rendered case decks
- `NgspiceRunResult`
- Parsed raw measurements
- Screening summaries
- `SimulationWorkflowResult`

### Calls

- ngspice process adapter
- Raw-result parser
- Specification screening engine

### Called by

- Direct-simulation route
- Optimization runtime leaf
- End-to-end orchestration

### Execution path

```text
Assignment
    ↓
DirectSimulationManifestBuilder
    ↓
NgspiceRunner
    ↓
NgspiceRawResultParser
    ↓
SpecificationScreeningEngine
    ↓
SimulationWorkflowResult
```

### Current boundary

The workflow is tested with fake runner results. Gates 8–12 must prove it using the real deck and ngspice.

---

## 8. Optimization

### Public role

The optimization layer owns optimization launches, sessions, cycles, candidate evaluation, persisted plans, composition, and runtime preflight.

### Primary application APIs

```text
OptimizationApplicationService
OptimizationLaunchService
Optimization composition root
RunPlan and RunPlanExecutor
PersistedRunPlanExecutor
OptimizationSession
OptimizationCycle
Candidate evaluation
Runtime preflight
```

### CLI adapters

```text
openams.cli.launch_optimization
openams.cli.launch_validated_optimization
openams.cli.validate_optimization_runtime
```

### Accepts

- Optimization launch input
- Execution plans requiring optimization
- Configured proposer/evaluator/runtime factories
- Persisted run plans and manifests

### Returns

- Launch manifests
- Optimization sessions and cycles
- Candidate evaluations
- Persisted execution records
- Runtime validation reports

### Calls

- Planning
- Simulation runtime adapters
- Persistence layer
- Configured composition factories

### Called by

- Optimization and synthesis-then-optimization routes
- Final CLI/application orchestration

### Current boundary

This is the most fully wired externally executable area of the repository. Gate 14 must still prove that end-to-end route selection enters it correctly from real unresolved assignments.

---

# Architectural Dependency Direction

```text
External inputs
    ↓
I/O and Metadata
    ↓
Canonical Model / Constraints / Topology
    ↓
Technology and Synthesis
    ↓
Planning
    ↓
Simulation or Optimization
    ↓
Parsing and Screening
    ↓
Persisted Reports
```

Lower layers must not depend on higher orchestration layers.

---

# Gate 1 Conclusion

Gate 1 passes because the repository's public architectural contracts have been identified from exported APIs, implementation entry points, workflow classes, and tests.

The API map establishes the intended integration path for all later validation gates. Later work must use these public contracts rather than recreating archived CLI behavior or coupling directly to private helpers.
