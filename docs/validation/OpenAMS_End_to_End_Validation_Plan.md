# OpenAMS End-to-End Validation Plan
**Version 2.0**

---

# Purpose

This document defines the official validation methodology for the OpenAMS project.

The objective is **not** simply to verify that individual classes or functions work.

The objective is to demonstrate, using objective evidence, that every architectural layer integrates correctly with the next until a complete end-to-end OpenAMS execution has been proven.

Every validation step must produce persistent artifacts that can be inspected by developers, researchers, reviewers, or future LLM assistants.

Validation always proceeds from architecture to implementation—not the other way around.

---

# Validation Philosophy

OpenAMS validation follows five fundamental principles.

## 1. Evidence before assumptions

Never assume that a subsystem works because source code exists.

Every conclusion must be supported by one or more of:

- source inspection
- unit tests
- integration tests
- executable validation
- generated artifacts

---

## 2. Validate architecture before implementation

The first objective is to understand the architecture that actually exists.

Only after the architecture has been mapped should individual execution paths be validated.

---

## 3. Validate one architectural layer at a time

Each validation gate proves one integration boundary.

The next gate may not begin until the current gate has passed.

---

## 4. Preserve validation evidence

Every validation gate produces permanent evidence stored in the repository.

```
docs/
    validation/
        evidence/
            gate_00_baseline/
            gate_01_api_map/
            gate_02_topology/
            ...
            gate_15_orchestration/
```

Each directory should contain

- raw evidence
- generated reports
- validation artifacts
- summary

---

## 5. Small commits

Every completed gate should be committed independently.

Example:

```
Record Gate 0 validation baseline

Map Gate 1 public APIs

Validate topology parser

Validate metadata loader

...
```

This creates an auditable validation history.

---

# Validation Gates

---

# Gate 0 — Freeze the Baseline

## Objective

Capture the exact repository state before beginning validation.

## Validate

- Git commit
- Repository status
- Test status
- Runtime environment
- Available CLI modules
- Example inputs
- Existing generated artifacts

## Artifacts

```
baseline.json
pytest.txt
BASELINE_REPORT.md
```

## Exit Criterion

The repository baseline is reproducible and committed.

---

# Gate 1 — Map the Public APIs

## Objective

Document the actual architecture exposed by the repository.

The purpose is **not** to list every class.

The purpose is to document the contracts between architectural layers.

For every subsystem determine

- Who calls it
- Public entry API
- Accepted inputs
- Returned outputs
- Downstream dependencies

Subsystems include

- topology
- metadata
- constraints
- technology
- synthesis
- planning
- simulation
- optimization

## Artifacts

```
API_MAP.md

api_inventory.json

raw/
```

## Exit Criterion

The architectural wiring of OpenAMS is documented.

---

# Gate 2 — Validate Topology Parsing

## Objective

Demonstrate that the topology parser correctly converts the SPICE netlist into the canonical circuit representation.

## Validate

- device extraction
- node extraction
- connectivity
- supplies
- I/O nodes

## Artifacts

```
topology.json

topology_report.json
```

## Exit Criterion

The parsed topology matches the reference circuit.

---

# Gate 3 — Validate Metadata

## Objective

Verify that every metadata file is accepted by the current architecture.

Validate

- specs
- design rules
- design intent
- simulation

Confirm

- schema compatibility
- units
- technology references
- required fields

## Artifacts

```
metadata_report.json
```

## Exit Criterion

All metadata is accepted or incompatibilities are documented.

---

# Gate 4 — Validate Constraint Compilation

## Objective

Verify that metadata is transformed into executable circuit constraints.

Examples

- symmetry
- current mirrors
- KCL
- KVL
- saturation
- width limits
- independent variables
- dependent variables

## Artifacts

```
compiled_constraints.json

constraint_report.json
```

## Exit Criterion

Circuit intent has become executable constraints.

---

# Gate 5 — Validate Hierarchical Synthesis

## Objective

Verify the hierarchical synthesis workflow.

Validate

- region construction
- region intersection
- hierarchy joins
- feasibility propagation

## Artifacts

```
hierarchical_synthesis_report.json
```

## Exit Criterion

Hierarchical synthesis produces valid circuit regions.

---

# Gate 6 — Validate Assignment Emission

## Objective

Generate complete circuit assignments.

Validate

- fixed assignments
- ranged assignments
- serialization
- completeness
- consistency

## Artifacts

```
complete_assignments.csv

assignment.json

assignment_report.json
```

## Exit Criterion

Assignments are internally consistent.

---

# Gate 7 — Validate Planning

## Objective

Verify execution planning.

Validate

- execution plan
- route selection
- simulation path
- optimization path

## Artifacts

```
execution_plan.json
```

## Exit Criterion

Correct execution route is selected.

---

# Gate 8 — Validate Simulation Manifest

## Objective

Verify SPICE deck generation.

Validate

- supplies
- models
- widths
- lengths
- analyses
- outputs

## Artifacts

```
rendered.spice

manifest_report.json
```

## Exit Criterion

SPICE deck matches assignment.

---

# Gate 9 — Validate ngspice Adapter

## Objective

Execute generated decks.

Validate

- invocation
- convergence
- logs
- return codes

## Artifacts

```
ngspice.log

raw_result.json
```

## Exit Criterion

ngspice executes correctly.

---

# Gate 10 — Validate Raw Result Parsing

## Objective

Verify parsing of simulator outputs.

Validate extraction of

- voltages
- currents
- operating point
- device regions

## Artifacts

```
parsed_results.json
```

## Exit Criterion

Simulator output becomes structured data.

---

# Gate 11 — Validate Specification Screening

## Objective

Verify specification evaluation.

Examples

- gain
- bandwidth
- phase margin
- slew rate
- power

## Artifacts

```
screening_report.json
```

## Exit Criterion

PASS/FAIL decisions are correct.

---

# Gate 12 — Validate Complete Simulation Workflow

## Objective

Validate the complete simulation subsystem.

```
Assignment

↓

Manifest

↓

ngspice

↓

Parser

↓

Screening
```

## Artifacts

```
simulation_workflow_report.json
```

## Exit Criterion

Simulation pipeline executes successfully.

---

# Gate 13 — Validate End-to-End Pipeline

## Objective

Validate the complete OpenAMS execution flow.

```
Netlist

↓

Metadata

↓

Topology

↓

Constraints

↓

Technology

↓

Hierarchical Synthesis

↓

Assignments

↓

Planning

↓

Simulation

↓

Screening
```

## Artifacts

```
end_to_end_report.json
```

## Exit Criterion

One complete design execution succeeds.

---

# Gate 14 — Validate Route Selection

## Objective

Verify automatic route selection.

Cases

- direct simulation
- optimization

## Artifacts

```
route_report.json
```

## Exit Criterion

Correct route is always selected.

---

# Gate 15 — Validate One-Command Orchestration

## Objective

Validate the final public application entry point.

Example

```
python -m openams.cli.run_design ...
```

The CLI should only orchestrate already validated library APIs.

## Artifacts

```
orchestration_report.json
```

## Exit Criterion

One command executes the complete validated architecture.

---

# Validation Dashboard

| Gate | Validation | Status | Evidence |
|------|------------|--------|----------|
| 0 | Baseline | PASS | gate_00_baseline |
| 1 | Public API map | Pending | gate_01_api_map |
| 2 | Topology parser | Pending | gate_02_topology |
| 3 | Metadata | Pending | gate_03_metadata |
| 4 | Constraint compiler | Pending | gate_04_constraints |
| 5 | Hierarchical synthesis | Pending | gate_05_hierarchical_synthesis |
| 6 | Assignment emission | Pending | gate_06_assignments |
| 7 | Planning | Pending | gate_07_planning |
| 8 | Simulation manifest | Pending | gate_08_manifest |
| 9 | ngspice adapter | Pending | gate_09_ngspice |
| 10 | Result parser | Pending | gate_10_parser |
| 11 | Specification screening | Pending | gate_11_screening |
| 12 | Simulation workflow | Pending | gate_12_simulation |
| 13 | End-to-end pipeline | Pending | gate_13_end_to_end |
| 14 | Route validation | Pending | gate_14_routes |
| 15 | One-command orchestration | Pending | gate_15_orchestration |

---

# Guiding Principle

Validation is complete only when every architectural boundary has been demonstrated with objective evidence and the complete OpenAMS execution path has been reproduced from the official public APIs.

The goal is not merely to show that individual components work in isolation, but to prove that the architecture functions as a coherent, integrated system.
