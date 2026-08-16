# OpenAMS Witness Generation Pipeline — Component MLP Training and Validation

# 24. STEP 10 — Train the Basic-Component MLPs

## Purpose

The previous step generated:

```text
runtime/two_stage_component_training_v2/datasets/
├── A_dataset.csv
└── B_dataset.csv
```

These datasets contain feasibility information obtained from the device-level MLP witness engine.

We now compress that relatively expensive component-level feasibility calculation into two fast neural-network models:

```text
A_dataset.csv
      │
      ▼
Component-A MLP
      │
      ├── feasible / infeasible
      └── feasible stage_ratio range


B_dataset.csv
      │
      ▼
Component-B MLP
      │
      └── feasible / infeasible
```

The resulting component MLPs are used as fast feasibility filters during the hierarchical witness search.

They do **not** replace exact device-level realization.

---

# 25. Component-A Model

Component A corresponds to:

```text
input_bias_network
```

Its input features are:

```text
w_m1_um
i_m5_a
vy_v
vbias_v
```

The model determines:

```text
feasibility
+
feasible stage_ratio interval
```

The training script therefore trains Component A as a feasibility model with an additional range prediction.

The `stage_ratio` propagated by A is later consumed by Component B.

---

# 26. Component-B Model

Component B corresponds to:

```text
output_stage
```

Its training dataset contains:

```text
i_m5_a
vout_v
vy_v
vbias_v
stage_ratio
valid
```

The component model itself is used by the hierarchical contract with the required MLP features:

```text
vout_v
vy_v
vbias_v
stage_ratio
```

and predicts:

```text
feasible / infeasible
```

The current hierarchical intent identifies Component B as a binary feasibility classifier. 

---

# 27. Train the Component MLPs

## Command

From the OpenAMS repository:

```bash
cd ~/AMS-Tutorial/openams
source .venv-openams/bin/activate
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

mkdir -p technology/component_models

python tools/technology/train_two_stage_component_mlps_v3.py \
  --a-dataset \
  runtime/two_stage_component_training_v2/datasets/A_dataset.csv \
  --b-dataset \
  runtime/two_stage_component_training_v2/datasets/B_dataset.csv \
  --a-output \
  technology/component_models/two_stage_input_bias_network_v3.pt \
  --b-output \
  technology/component_models/two_stage_output_stage_v3.pt
```

The repository inventory identifies `train_two_stage_component_mlps_v3.py` as the latest two-stage component-training script, alongside the earlier training variants.

---

# 28. Training Method

The current training implementation uses grouped validation rather than simply performing a random row-level split.

This is important because many rows can originate from closely related circuit states.

The objective is to test whether the component MLP generalizes to previously unseen groups of operating conditions rather than merely memorizing nearby interface samples.

Conceptually:

```text
component dataset
       │
       ├──────────────┐
       ▼              ▼
training groups   validation groups
       │              │
       ▼              │
train MLP             │
       │              │
       └──────► evaluate
```

---

# 29. Expected Outputs

After training, verify:

```bash
ls -lh \
  technology/component_models/two_stage_input_bias_network_v3.pt \
  technology/component_models/two_stage_output_stage_v3.pt
```

The expected checkpoints are:

```text
technology/component_models/
├── two_stage_input_bias_network_v3.pt
└── two_stage_output_stage_v3.pt
```

These files are subsequently referenced from the hierarchical feasibility metadata.

---

# 30. What Is Stored in the Component Checkpoint?

Conceptually, a component checkpoint contains enough information to reproduce the trained feasibility model, including:

```text
trained neural-network weights
feature definitions
feature scaling/normalization information
model configuration
classification information
range-emitter information where applicable
```

The `.pt` checkpoint is generated metadata.

It should not be edited manually.

---

# 31. STEP 11 — Validate the Component MLP Hierarchy

## Purpose

High standalone classification accuracy is not sufficient.

The important question is:

> Does the MLP hierarchy preserve the feasible interface states that would have been found by the device-level teacher?

The validation therefore compares:

```text
DEVICE-MLP TEACHER
        │
        ▼
exact component feasibility
```

against:

```text
COMPONENT MLP
      │
      ▼
predicted component feasibility
```

and, more importantly, compares the result after joining the two components.

---

# 32. Why Recall Is Particularly Important

Suppose the teacher says an interface state is feasible but the component MLP rejects it:

```text
Teacher = feasible
MLP     = infeasible
```

That state disappears before exact realization.

OpenAMS can therefore lose a valid part of the circuit design space.

This is a false negative.

For this reason, component feasibility recall is particularly important.

Conceptually:

```text
                    MLP
              PASS       FAIL

Teacher PASS   correct    LOST
Teacher FAIL   extra      correct
```

An extra MLP-positive state is relatively inexpensive because the exact realizer can reject it later.

A false negative is more serious because the valid state is never sent to the exact realizer.

---

# 33. Run the Two-Stage Hierarchy Validation

## Command

Run:

```bash
cd ~/AMS-Tutorial/openams
source .venv-openams/bin/activate
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

python tools/validation/validate_two_stage_component_mlp_hierarchy.py
```

The current repository includes this validation tool as part of the component-MLP pipeline.

It uses the two-stage component checkpoints and compares the MLP hierarchy with the device-level teacher.

---

# 34. What the Validation Measures

The important measurements are conceptually:

```text
Component A:
    recall
    precision

Component B / final join:
    recall
    precision

Runtime:
    component-MLP evaluation time
    teacher/device realization time
```

The most important system-level measurement is the final joined feasibility result:

```text
A feasible
      │
      ▼
compatible interface
      │
      ▼
B feasible
      │
      ▼
joined circuit-feasible state
```

The validation should show that the hierarchical MLP path retains sufficiently high coverage of the teacher's valid joined states.

---

# 35. Acceptance Check

Before continuing, confirm that:

```text
[1] Component-A checkpoint exists.

[2] Component-B checkpoint exists.

[3] Both models can be loaded.

[4] Component-A feasibility recall is acceptable.

[5] Final joined feasibility recall is acceptable.

[6] Hierarchical MLP evaluation is substantially faster
    than repeatedly invoking the exact component teacher.
```

If these conditions are not met, do **not** compensate by modifying Step 5.

The problem should instead be addressed at:

```text
dataset coverage
sampling ranges
training
classification threshold
component partition/interface definition
```

This preserves the generic nature of the final witness engine.

---

# 36. STEP 12 — Compile the Hierarchical Component Contract

## Purpose

We now have all of the information needed to describe the hierarchical witness search:

```text
independent circuit variables
+
topology partition
+
component dependency graph
+
interface variables
+
component MLP checkpoints
+
exact component realizers
+
final witness fields
```

These declarations are converted into one executable contract:

```text
hierarchical_component_contract.json
```

The generic Step-5 witness engine reads this contract.

It should not need to know that the circuit is a two-stage op-amp.

---

# 37. Contract Compilation

## Command

Run:

```bash
cd ~/AMS-Tutorial/openams
source .venv-openams/bin/activate
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

python tools/compile_hierarchical_component_contract.py \
  --intent \
  examples/two_stage_opamp/inputs/design_intent.yaml \
  --output \
  examples/two_stage_opamp/generated/assignment_synthesis/hierarchical_component_contract.json
```

The repository contains the generic compiler:

```text
tools/compile_hierarchical_component_contract.py
```

as part of the current pipeline.

---

# 38. Contract Output

Verify:

```bash
ls -lh \
examples/two_stage_opamp/generated/assignment_synthesis/hierarchical_component_contract.json
```

Inspect it with:

```bash
python -m json.tool \
examples/two_stage_opamp/generated/assignment_synthesis/hierarchical_component_contract.json \
| less
```

---

# 39. What the Contract Contains

The contract is the executable description of the hierarchical synthesis problem.

Conceptually:

```text
hierarchical_component_contract.json

├── independent point source
│
├── independent variables
│   ├── w_m1_um
│   └── i_m5_a
│
├── component order
│   ├── input_bias_network
│   └── output_stage
│
├── input_bias_network
│   ├── MLP checkpoint
│   ├── MLP features
│   ├── interface search
│   ├── propagated stage_ratio
│   └── exact realizer
│
├── output_stage
│   ├── dependency on input_bias_network
│   ├── MLP checkpoint
│   ├── MLP features
│   ├── VOUT local search
│   └── exact realizer
│
├── interface grids
│
├── derived relationships
│
└── final witness fields
```

---

# 40. Why the Contract Is Important

The contract separates:

```text
CIRCUIT-SPECIFIC KNOWLEDGE
```

from:

```text
GENERIC SEARCH ALGORITHM
```

Circuit-specific information belongs in:

```text
design_intent.yaml
        ↓
hierarchical_component_contract.json
```

The search engine should operate only on the contract:

```text
hierarchical_component_contract.json
        │
        ▼
generic hierarchical witness engine
```

This is what allows the same Step-5 algorithm to be applied to another topology without writing another topology-specific search algorithm.

---

# 41. Check the Component Order

For the two-stage amplifier the contract should resolve the order:

```text
input_bias_network
        ↓
output_stage
```

because:

```text
output_stage.depends_on:
    input_bias_network
```

This forms a component DAG:

```text
Independent point
     W1, I5
        │
        ▼
┌───────────────────┐
│ input_bias_network│
└─────────┬─────────┘
          │
          │ VY
          │ VBIAS
          │ stage_ratio
          ▼
┌───────────────────┐
│   output_stage    │
└───────────────────┘
```

For a larger circuit the same contract can describe:

```text
A
│
├──► B
│
└──► C
     │
     ▼
     D
```

provided the component dependencies form a valid acyclic graph.

---

# 42. STEP 13 — Run the Generic Hierarchical Witness Engine

## Purpose

We have now reached the actual correlated circuit witness search.

Inputs:

```text
independent_regions.json

component A MLP

component B MLP

hierarchical_component_contract.json

device technology MLP / exact realizer
```

Output:

```text
complete correlated transistor-level witnesses
```

---

# 43. First Run — Small Smoke Test

Do not immediately run the entire independent design space after changing the pipeline.

First run 25 independent points.

```bash
cd ~/AMS-Tutorial/openams
source .venv-openams/bin/activate
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

rm -rf runtime/generic_step5_two_stage_smoke

python tools/validation/hierarchical_witness_engine.py \
  --contract \
  examples/two_stage_opamp/generated/assignment_synthesis/hierarchical_component_contract.json \
  --output \
  examples/two_stage_opamp/generated/assignment_synthesis/generic_step5_smoke.csv \
  --work-dir \
  runtime/generic_step5_two_stage_smoke \
  --max-points 25 \
  --workers 12
```

`hierarchical_witness_engine.py` is the generic hierarchical Step-5 implementation in the current script set.

---

# 44. Recommended Timed Smoke Test

For development and regression testing, use:

```bash
/usr/bin/time -f '\nREAL=%e sec\nMAX_RSS=%M KB' \
python tools/validation/hierarchical_witness_engine.py \
  --contract \
  examples/two_stage_opamp/generated/assignment_synthesis/hierarchical_component_contract.json \
  --output \
  examples/two_stage_opamp/generated/assignment_synthesis/generic_step5_smoke.csv \
  --work-dir \
  runtime/generic_step5_two_stage_smoke \
  --max-points 25 \
  --workers 12
```

This records:

```text
wall-clock runtime
maximum resident memory
```

which is useful for regression testing.

---

# 45. What Happens Inside Step 13

For each independent circuit point:

```text
W1, I5
```

the engine performs approximately:

```text
1. Enumerate Component-A interface cells

             W1, I5
                │
                ▼
         VY × VBIAS grid


2. Evaluate Component-A MLP

         VY × VBIAS
                │
                ▼
         A feasibility MLP
                │
          ┌─────┴─────┐
          │           │
        reject      retain
                       │
                       ▼
              stage_ratio range


3. Exact-realize surviving Component-A cells

        surviving A states
                │
                ▼
        device-level MLP
          witness engine
                │
                ▼
        exact A witnesses


4. Compute exact propagated values

        exact A witness
                │
                ▼
 stage_ratio = 2 × W3 / W5


5. Search Component B

     exact A interface
             +
           VOUT
             │
             ▼
      Component-B MLP


6. Exact-realize surviving B states

        B MLP-positive
              │
              ▼
       device-level MLP
         exact realizer
              │
              ▼
       exact B witnesses


7. Join compatible A and B witnesses

        exact A
           │
           │ interface agreement
           ▼
        exact B
           │
           ▼
     complete circuit witness
```

---

# 46. Expected Runtime Report

The engine reports quantities such as:

```text
components

component order

independent points

Component-A:
    MLP evaluations
    positive cells
    exact witnesses

Component-B:
    MLP evaluations
    positive cells
    exact witnesses

exact joined component tuples

points with >=1 witness

coverage

final exact witnesses

wall seconds
```

These numbers are useful both for debugging and for measuring how effectively the component MLPs reduce the exact-realization workload.

---

# 47. Smoke-Test Acceptance

The smoke test should answer:

```text
Did every requested independent point execute?

Did Component A produce feasible states?

Did exact realization produce witnesses?

Did Component B receive the propagated A interfaces?

Did Component B produce exact witnesses?

Did the interface join succeed?

Did the final CSV contain complete witnesses?
```

The most important summary is:

```text
points with >=1 witness
------------------------
independent points
```

which provides the observed independent-point coverage for that run.

---

# 48. Smoke-Test Output

The command above writes:

```text
examples/two_stage_opamp/generated/assignment_synthesis/
    generic_step5_smoke.csv
```

Inspect:

```bash
head -5 \
examples/two_stage_opamp/generated/assignment_synthesis/generic_step5_smoke.csv
```

and:

```bash
wc -l \
examples/two_stage_opamp/generated/assignment_synthesis/generic_step5_smoke.csv
```

---

# 49. What a Complete Circuit Witness Contains

A final witness should represent one correlated realization of the complete circuit.

Conceptually:

```text
Independent variables
---------------------
W1
I5

Interface operating point
-------------------------
VY
VBIAS
VOUT
stage_ratio

Device realization
------------------
W1
W2
W3
W4
W5
W6
W7

plus required currents,
voltages and realization metadata
```

The important property is correlation.

A witness is **not**:

```text
an independently selected W3
+
an independently selected W5
+
an independently selected VY
```

Instead all values come from one compatible sequence:

```text
independent point
       ↓
feasible A interface
       ↓
exact A realization
       ↓
propagated exact interface
       ↓
feasible B realization
       ↓
exact A/B join
       ↓
complete witness
```

---

# 50. Full Step-5 Run

After the smoke test succeeds, remove `--max-points`.

Use:

```bash
cd ~/AMS-Tutorial/openams
source .venv-openams/bin/activate
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

rm -rf runtime/generic_step5_two_stage_full

/usr/bin/time -f '\nREAL=%e sec\nMAX_RSS=%M KB' \
python tools/validation/hierarchical_witness_engine.py \
  --contract \
  examples/two_stage_opamp/generated/assignment_synthesis/hierarchical_component_contract.json \
  --output \
  examples/two_stage_opamp/generated/assignment_synthesis/hierarchical_witnesses.csv \
  --work-dir \
  runtime/generic_step5_two_stage_full \
  --workers 12
```

This searches the complete independent-point source specified by the hierarchical contract.

---

# 51. Final Step-5 Artifact

The principal output of the OpenAMS synthesis stage is now:

```text
examples/two_stage_opamp/generated/assignment_synthesis/
    hierarchical_witnesses.csv
```

This should be considered the canonical **candidate circuit witness pool** produced by the hierarchical synthesis algorithm.

At this point:

```text
SPICE topology
      ↓
metadata
      ↓
independent design space
      ↓
topology partition
      ↓
component teacher datasets
      ↓
component MLPs
      ↓
hierarchical contract
      ↓
component-MLP filtering
      ↓
exact device realization
      ↓
interface joining
      ↓
hierarchical_witnesses.csv
```

has been completed.

---

# 52. Important Distinction: Candidate vs. Valid Circuit Witness

The witnesses in:

```text
hierarchical_witnesses.csv
```

have passed the OpenAMS model-based hierarchical synthesis process.

They are therefore:

```text
OpenAMS-realizable correlated witnesses
```

They have **not yet necessarily been independently verified by ngspice**.

The final distinction is:

```text
hierarchical_witnesses.csv
       │
       │ OpenAMS model-based witnesses
       ▼
ngspice verification
       │
       ▼
valid_circuit_witnesses.csv
```

The next pipeline stage is therefore **SPICE witness validation**.

That stage establishes which synthesized witnesses correspond to actual converged circuit operating points and produces the final valid circuit witness set.