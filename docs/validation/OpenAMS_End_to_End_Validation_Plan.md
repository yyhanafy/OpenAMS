# OpenAMS End-to-End Validation Plan

## Purpose

This document defines the canonical validation strategy for OpenAMS. The
objective is to validate the system incrementally through objective
evidence, preventing development from drifting into low-level debugging
before the overall architecture has been proven.

Each stage has: - A single objective - A measurable exit criterion -
Persistent artifacts - A clear gate before moving to the next stage

------------------------------------------------------------------------

# Stage 0 --- Freeze the Starting Point

Record:

``` bash
git status
git rev-parse HEAD
pytest -q
```

Create a baseline report containing: - Commit hash - Test summary -
Input examples present - Generated artifacts present/absent - Legacy
scripts status

**Exit criterion:** The repository baseline is frozen and reproducible.

------------------------------------------------------------------------

# Stage 1 --- Identify the Real Public APIs

Audit the implementation and tests to identify the actual callable APIs
for:

-   Topology parsing
-   Constraint compilation
-   Technology-region construction
-   Region intersection
-   Assignment emission
-   Simulation manifest creation
-   ngspice execution
-   Specification screening
-   Run planning

Build an API inventory:

  Subsystem     Entry API   Inputs   Outputs   Test Reference
  ------------- ----------- -------- --------- ----------------
  Topology                                     
  Constraints                                  
  Technology                                   
  Synthesis                                    
  Simulation                                   
  Screening                                    

**Exit criterion:** The public execution path is known from code and
tests---not assumptions.

------------------------------------------------------------------------

# Stage 2 --- Validate Topology Ingestion

Input: - `examples/two_stage_opamp/inputs/netlist.spice`

Validate: - Device extraction - Connectivity - Supplies - Input/output
nodes

Artifacts: - `generated/topology.json` -
`generated/validation/topology_report.json`

**Exit criterion:** The netlist is represented correctly.

------------------------------------------------------------------------

# Stage 3 --- Validate Metadata Ingestion

Load:

-   specs.yaml
-   design_rules.yaml
-   design_intent.yaml
-   simulation.yaml

Validate: - Parsing - Schema compatibility - Units - Technology
references

Artifact:

`generated/validation/metadata_report.json`

Classify each field as: - accepted - translated - unused - invalid -
missing

**Exit criterion:** Metadata compatibility is completely understood.

------------------------------------------------------------------------

# Stage 4 --- Validate Canonical Constraint Compilation

Compile:

-   topology
-   design intent
-   design rules
-   operating conditions

Verify: - symmetry - mirrors - KCL - KVL - width limits - saturation -
independent/dependent variables

Artifacts:

-   `generated/canonical_constraints.json`
-   `generated/validation/constraint_report.json`

**Exit criterion:** Constraints become explicit machine-executable
rules.

------------------------------------------------------------------------

# Stage 5 --- Validate the Technology Backend

Independently verify:

-   table lookup
-   interpolation
-   saturation classification
-   width/current solving
-   NMOS/PMOS handling

Artifacts:

-   `generated/validation/technology_probe_results.csv`
-   `generated/validation/technology_report.json`

**Exit criterion:** Device queries behave correctly.

------------------------------------------------------------------------

# Stage 6 --- Generate One Operating Point

Generate one complete assignment from one independent-variable
selection.

Validate:

-   KCL
-   KVL
-   symmetry
-   mirror rules
-   widths
-   saturation
-   technology provenance

Artifact:

`generated/assignment_synthesis/assignment_0000.json`

**Exit criterion:** One internally consistent operating point is
synthesized.

------------------------------------------------------------------------

# Stage 7 --- Generate a Small Assignment Set

Generate a small set (5--20 assignments).

Artifacts:

-   `complete_assignments.csv`
-   `synthesis_report.json`

Validate: - classification - failure counts - route recommendation

Run Layer 3 assignment validation.

**Exit criterion:** Multiple assignments are generated and validated.

------------------------------------------------------------------------

# Stage 8 --- Validate SPICE Deck Generation

Render one assignment into a SPICE deck.

Verify: - model library - widths/lengths - supplies - bias values -
analysis commands

Artifact:

`rendered_dc.spice`

**Exit criterion:** Assignment translation into SPICE is correct.

------------------------------------------------------------------------

# Stage 9 --- Validate ngspice Execution

Execute one generated deck.

Capture: - return code - logs - node voltages - branch currents -
operating point

Artifacts: - `raw_result.json` - `ngspice.log`

**Exit criterion:** ngspice executes successfully.

------------------------------------------------------------------------

# Stage 10 --- Compare Synthesis vs. ngspice

Compare:

-   node voltages
-   currents
-   device regions

Generate comparison report.

**Exit criterion:** Synthesized and simulated operating points agree
within tolerance.

------------------------------------------------------------------------

# Stage 11 --- Validate a Small Assignment Set

Run DC validation on all synthesized assignments.

Classify failures:

-   synthesis
-   technology
-   rendering
-   convergence
-   current mismatch
-   voltage mismatch
-   saturation
-   parsing

**Exit criterion:** Failure modes are understood.

------------------------------------------------------------------------

# Stage 12 --- Validate AC Extraction

Extract:

-   Gain
-   UGB
-   Phase Margin

Validate extraction independently.

Artifacts:

-   `ac_results.csv`
-   `ac_validation_report.json`

**Exit criterion:** AC metrics are reproducible.

------------------------------------------------------------------------

# Stage 13 --- Validate Specification Screening

Verify PASS/FAIL decisions independently.

Record:

-   measured value
-   threshold
-   operator
-   result

**Exit criterion:** Screening decisions are correct.

------------------------------------------------------------------------

# Stage 14 --- Validate Route Selection

Verify:

## Direct Simulation

Fully resolved assignments must bypass optimization.

## Optimization

Assignments containing unresolved ranges must invoke optimization.

**Exit criterion:** Correct execution path is selected automatically.

------------------------------------------------------------------------

# Stage 15 --- Build the Application Orchestrator

Only after every subsystem has been validated should a top-level
application flow be created.

Execution sequence:

1.  Load inputs
2.  Parse topology
3.  Compile constraints
4.  Load technology
5.  Synthesize assignments
6.  Classify assignments
7.  Select execution route
8.  Simulate or optimize
9.  Screen specifications
10. Persist reports

The CLI should remain a thin adapter over validated library APIs.

**Exit criterion:** One command reproduces the fully validated flow.

------------------------------------------------------------------------

# Validation Dashboard

  Gate   Proof                      Status    Artifact
  ------ -------------------------- --------- -------------------------
  0      Baseline frozen            Pending   Baseline report
  1      API map                    Pending   API inventory
  2      Topology                   Pending   Topology report
  3      Metadata                   Pending   Metadata report
  4      Constraints                Pending   Constraint report
  5      Technology                 Pending   Technology report
  6      One assignment             Pending   Assignment JSON
  7      Assignment set             Pending   CSV + report
  8      SPICE deck                 Pending   Rendered deck
  9      ngspice                    Pending   Raw result
  10     DC comparison              Pending   Comparison report
  11     Multi-point DC             Pending   Validation summary
  12     AC                         Pending   AC report
  13     Screening                  Pending   Screening report
  14     Route selection            Pending   Route report
  15     End-to-end orchestration   Pending   Final validation report

## Guiding Principle

Never proceed to the next stage until the current stage has objective
evidence and persistent artifacts. The validation campaign should always
be driven by facts collected from the implementation rather than
assumptions about the architecture.
