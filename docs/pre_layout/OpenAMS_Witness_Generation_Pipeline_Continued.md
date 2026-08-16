# OpenAMS Witness Generation Pipeline — Continued

# 11. STEP 06 — Generate the Independent Design Space

## Purpose

After the frontend has produced:

```text
examples/two_stage_opamp/generated/compiled_circuit_model.json
```

OpenAMS determines which circuit quantities are truly independent synthesis variables and constructs their allowed domains.

For the current two-stage amplifier, the hierarchical flow uses two circuit-level independent variables:

```text
w_m1_um
i_m5_a
```

The hierarchical metadata explicitly identifies their source as `independent_regions.json`; `w_m1_um` is sampled from its domain and `i_m5_a` uses the discrete candidate values stored in that domain.

This stage does **not** yet search internal node voltages or produce complete transistor sizes.

Conceptually:

```text
compiled circuit model
        +
design intent
        │
        ▼
identify independent variables
        │
        ▼
construct legal domains
        │
        ▼
independent_regions.json
```

---

## Command

Run:

```bash
cd ~/AMS-Tutorial/openams
source .venv-openams/bin/activate
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

bash scripts/run_assignment_step_03.sh
```

The repository contains both the Step-03 wrapper and its corresponding validation implementation:

```text
scripts/run_assignment_step_03.sh

tools/validation/
    validate_assignment_step_03_independent_domains.py
```



---

## Main Output

The important artifact for the hierarchical pipeline is:

```text
examples/two_stage_opamp/generated/assignment_synthesis/
    independent_regions.json
```

This file becomes the source of the independent points used later by the hierarchical witness engine.

---

## What `independent_regions.json` Contains

Conceptually it contains a domain for each independent synthesis quantity.

For example:

```text
w_m1_um
    minimum
    maximum
    candidate/sampling information

i_m5_a
    minimum
    maximum
    candidate_values
```

The exact representation should be treated as generated metadata.

It should **not normally be edited by hand**.

The later hierarchical metadata references it explicitly as:

```text
independent_point_source:
    kind: independent_regions_json
    path:
      examples/two_stage_opamp/generated/
      assignment_synthesis/independent_regions.json
```



---

## Check

Verify that the file was produced:

```bash
ls -lh \
examples/two_stage_opamp/generated/assignment_synthesis/independent_regions.json
```

A useful quick inspection is:

```bash
python -m json.tool \
examples/two_stage_opamp/generated/assignment_synthesis/independent_regions.json \
| less
```

At this point we have:

```text
W1 domain
I5 domain
```

but not yet:

```text
VY
VBIAS
VOUT
W2 ... W7
```

Those values are determined through the hierarchical component search and exact realization.

---

# 12. STEP 07 — Dependent-Region Preparation

## Purpose

The next assignment stage processes quantities that are not allowed to vary independently.

These quantities are constrained by:

```text
circuit topology
device relationships
current relationships
voltage relationships
design rules
```

The objective is to preserve those dependencies rather than turning every circuit variable into an independent Cartesian search dimension.

This is critical to OpenAMS.

The design space should look like:

```text
small set of independent variables
        │
        ▼
electrical dependencies
        │
        ▼
correlated realizations
```

rather than:

```text
W1 × W2 × W3 × W4 × W5 × W6 × W7 ×
VY × VBIAS × VOUT × ...
```

---

## Command

Run:

```bash
bash scripts/run_assignment_step_04.sh
```

The repository contains:

```text
scripts/run_assignment_step_04.sh

tools/validation/
    validate_assignment_step_04_dependent_regions.py
```



---

## Main Output

The expected assignment-synthesis artifact is:

```text
examples/two_stage_opamp/generated/assignment_synthesis/
    dependent_regions.json
```

This is supporting synthesis metadata.

For the latest hierarchical algorithm, this is **not the final search space**. Exact cross-device correlations are handled later through component feasibility and exact device realization.

---

# 13. STEP 08 — Define the Hierarchical Topology Partition

## Purpose

The circuit is now divided into basic electrically meaningful sub-components.

This is the key structural step that enables the component-MLP acceleration.

For the current two-stage operational amplifier the partition is:

```text
                 TWO-STAGE OPAMP

        ┌─────────────────────────┐
        │                         │
        │  INPUT / BIAS NETWORK   │
        │                         │
        │       Component A       │
        │                         │
        └────────────┬────────────┘
                     │
                     │ VY
                     │ VBIAS
                     │ stage_ratio
                     │
                     ▼
        ┌─────────────────────────┐
        │                         │
        │      OUTPUT STAGE       │
        │                         │
        │       Component B       │
        │                         │
        └─────────────────────────┘
```

The current component IDs are:

```text
input_bias_network
output_stage
```

The second component declares a dependency on the first.

---

# 14. Partition Metadata

The topology partition is stored in:

```text
examples/two_stage_opamp/inputs/design_intent.yaml
```

under:

```yaml
hierarchical_feasibility:
```

This is important:

> The partition is circuit-specific metadata. The hierarchical witness engine itself should remain circuit-independent.

The contract compiler explicitly states that it has no hard-coded topology names, device numbers, or node names.

---

## Component A — `input_bias_network`

The current metadata declares:

```text
MLP features:
    w_m1_um
    i_m5_a
    vy_v
    vbias_v
```

Its component MLP performs two functions:

```text
1. predict whether this interface state is feasible

2. emit a feasible range for:
       stage_ratio
```

The exact realized value is later computed as:

```text
stage_ratio = 2 × W3 / W5
```

The current hierarchical intent explicitly stores this derived relation.

---

## Component B — `output_stage`

Its MLP features are:

```text
vout_v
vy_v
vbias_v
stage_ratio
```

Its purpose is simpler:

```text
given the upstream state and an output voltage,
is the output stage feasible?
```

The current B model is therefore a binary feasibility classifier.

---

# 15. Interface Variables

The two components cannot be searched independently because they share electrical conditions.

The partition therefore exposes explicit interface quantities.

For the two-stage amplifier, the important electrical interface coordinates include:

```text
VY
VBIAS
```

and the upstream component also propagates:

```text
stage_ratio
```

The basic relationship is:

```text
Independent point
    W1, I5
       │
       ▼
Component A
    searches:
       VY
       VBIAS
       │
       ├── feasible?
       │
       └── feasible stage_ratio
                     │
                     ▼
              Component B
                  searches:
                     VOUT
```

This prevents Component B from being evaluated against arbitrary values unrelated to a feasible Component-A realization.

---

# 16. Updating the Two-Stage Hierarchical Metadata

The current repository contains a helper that writes the hierarchical declaration into `design_intent.yaml`:

```text
tools/update_two_stage_hierarchical_intent_v2.py
```

Its only required argument is the intent file.

If the current `design_intent.yaml` has not already been updated, run:

```bash
python tools/update_two_stage_hierarchical_intent_v2.py \
  --intent examples/two_stage_opamp/inputs/design_intent.yaml
```

Do **not** rerun this casually if the intent has subsequently been hand-tuned, because the script writes the hierarchical-feasibility section.

Afterwards inspect it with:

```bash
grep -n -A160 "hierarchical_feasibility:" \
  examples/two_stage_opamp/inputs/design_intent.yaml
```

---

# 17. Brief Description of `hierarchical_feasibility`

This section of `design_intent.yaml` controls the hierarchical search.

The important fields are:

```text
strategy
    Which hierarchical synthesis strategy is requested.

independent_point_source
    Where the circuit-level independent design points come from.

components
    The basic circuit partitions.

source_group
    Links each component to an assignment-synthesis group.

depends_on
    Defines the component dependency graph.

checkpoint
    Path to the trained component MLP.

model_kind
    Type of component model.

mlp_features
    Ordered input features expected by that component MLP.

interface_inputs
    Interfaces consumed by the component.

interface_outputs
    Interfaces produced by the component.

local_search_coordinates
    Variables searched locally within a downstream component.

exact_realizer
    Describes how an MLP-positive state is verified using the
    device-level witness engine.

derived_after_realization
    Quantities calculated from an exact component witness.
```

The current two-stage metadata specifies Component A as a feasibility/range-emitting model and Component B as a binary feasibility classifier.

---

# 18. Why the Component MLP Is Needed

Without component MLPs, Step 5 would have to invoke the exact transistor-level realization engine over a very large number of interface combinations.

Instead OpenAMS uses:

```text
                  FAST
                   │
                   ▼
            Component MLP
          feasibility filter
                   │
             reject most cells
                   │
                   ▼
                 SMALL
          surviving state set
                   │
                   ▼
             Exact device-MLP
               realizer
                   │
                   ▼
            exact component
               witnesses
```

The component MLP therefore does **not** replace the transistor/device MLP.

It accelerates the search.

The transistor/device-level witness engine remains the teacher and exact realizer.

---

# 19. STEP 09 — Generate Component-A and Component-B Training Data

## Purpose

We now need to build training datasets for the two basic sub-components.

The labels are generated using the existing transistor-level MLP witness engine.

Thus:

```text
device MLP
    │
    ▼
device-level witness engine
    │
    ▼
component feasibility labels
    │
    ▼
component training CSV
```

The dataset generator explicitly describes itself this way and generates independent A and B datasets.

---

## Component-A Dataset

Component A uses:

```text
INPUTS
------
W1
I5
VY
VBIAS
```

and produces training targets:

```text
valid
Rmin
Rmax
```

where:

```text
R = stage_ratio
```

The generator determines the exact `R` values from successful transistor-level component witnesses and records their minimum and maximum.

---

## Component-B Dataset

Component B uses:

```text
INPUTS
------
VOUT
VY
VBIAS
R
```

with the target:

```text
valid
```

The B dataset is deliberately generated independently of Component A so that it contains both feasible and infeasible output-stage states.

---

# 20. Generate the Two-Stage Component Datasets

## Command

Run:

```bash
cd ~/AMS-Tutorial/openams
source .venv-openams/bin/activate
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

rm -rf runtime/two_stage_component_training_v2

python tools/validation/generate_two_stage_component_datasets_v2.py \
  --root . \
  --work-dir runtime/two_stage_component_training_v2
```

The generator defaults to:

```text
teacher:
    tools/validation/run_two_stage_independent_tables_v2.py

device witness engine:
    tools/validation/witness_engine.py

base witness plan:
    examples/two_stage_opamp/inputs/
        two_stage_mlp_witness_plan.yaml
```



---

# 21. Default Dataset Sampling

The current script uses geometric sampling over:

```text
W1:
    1.0 → 100.0 µm
    7 samples

I5:
    10.009030134 → 99.956552025 µA
    7 samples
```

For Component A it uses:

```text
VY:
    61 samples

VBIAS:
    9 samples

exact witnesses retained/state:
    5
```

For Component B it uses:

```text
VOUT:
    0.20 → 1.70 V
    5 samples

VY:
    21 samples

VBIAS:
    5 samples

stage_ratio:
    0.10 → 20.0
    11 geometric samples

exact witnesses retained/state:
    3
```

These are the current defaults in `generate_two_stage_component_datasets_v2.py`.

These values are **dataset-generation policy**, not fundamental circuit constants.

---

# 22. Dataset Outputs

The final datasets are written to:

```text
runtime/two_stage_component_training_v2/
└── datasets/
    ├── A_dataset.csv
    └── B_dataset.csv
```

The generator explicitly writes those two files and prints the number of valid and invalid examples at completion.

Check them with:

```bash
ls -lh \
runtime/two_stage_component_training_v2/datasets/A_dataset.csv \
runtime/two_stage_component_training_v2/datasets/B_dataset.csv
```

Then inspect the headers:

```bash
head -5 \
runtime/two_stage_component_training_v2/datasets/A_dataset.csv

head -5 \
runtime/two_stage_component_training_v2/datasets/B_dataset.csv
```

A should contain fields corresponding to:

```text
group_id
w_m1_um
i_m5_a
vy_v
vbias_v
valid
r_count
r_min
r_max
```

B contains:

```text
group_id
i_m5_a
vout_v
vy_v
vbias_v
stage_ratio
valid
```



---

# 23. Acceptance Check

The important requirement is that both datasets contain useful discrimination.

Check:

```bash
python - <<'PY'
import pandas as pd

for name in ["A", "B"]:
    p = f"runtime/two_stage_component_training_v2/datasets/{name}_dataset.csv"
    d = pd.read_csv(p)

    print(f"\n{name}")
    print("rows    :", len(d))
    print("valid   :", int(d["valid"].sum()))
    print("invalid :", int((d["valid"] == 0).sum()))
PY
```

A usable classification dataset should contain both:

```text
valid states
invalid states
```

The generator itself prints this summary after completing the teacher runs.

---

At this point the pipeline has reached:

```text
SPICE
  ↓
topology
  ↓
metadata / constraints
  ↓
independent W1/I5 design space
  ↓
two-component topology partition
  ↓
device-MLP teacher
  ↓
A_dataset.csv
B_dataset.csv
```

The next step is to train the two basic-component MLPs from these datasets and validate them against unseen transistor-level teacher points.