# OpenAMS Correlated Witness Search Algorithm

## Purpose

This document describes the topology-generic correlated witness search implemented by:

    src/openams/synthesis/witness_engine.py

Its purpose is to provide an engineering reference for future optimization, extension, and research.

The algorithm does not contain hard-coded knowledge of a two-stage op-amp, folded cascode, or any other circuit topology. Circuit-specific search structure is declared in a witness-plan YAML file. The Python engine executes that plan using the generic MOS MLP oracle.

The central objective is:

> For every independent design point, find one or more complete correlated DC operating-point candidates whose device operating conditions, shared node voltages, widths, currents, saturation constraints, and circuit relations are mutually compatible.

The output is a witness CSV suitable for subsequent ngspice verification.

---

## 1. Search Problem

OpenAMS separates the search into three spaces.

### Independent design space

The independent design-space CSV contains the quantities selected before correlated witness generation. Each CSV row is one independent design point.

### Local stage search space

For one independent point, each stage introduces or derives additional variables such as node voltages, bias voltages, transistor widths, branch currents, and dependent quantities.

### Complete correlated witness space

A complete witness is one complete path through the staged search:

    independent point
            |
            v
       stage 1 choice
            |
            v
       stage 2 choice
            |
           ...
            |
            v
       complete candidate

Every child inherits all values selected by its parent. The final candidate therefore retains the correlation between all previously selected circuit quantities.

This is the key difference from independent-range propagation, where individually valid ranges do not guarantee that one simultaneous physical operating point exists.

---

## 2. High-Level Algorithm

For every independent design point:

    bind independent variables
            |
            v
       parent = {}
            |
            v
    +-----------------------------+
    |           STAGE k           |
    |                             |
    | build sweep grid            |
    | evaluate MLP devices        |
    | apply constraints           |
    | select feasible children    |
    | apply diversity cap         |
    +-------------+---------------+
                  |
                  v
             next stage
                  |
                 ...
                  |
                  v
          complete candidates
                  |
                  v
        reevaluate all devices
                  |
                  v
        compute residual vector
                  |
                  v
       enforce final constraints
                  |
                  v
       rank by residual quality
                  |
                  v
        keep best N witnesses
                  |
                  v
             witnesses.csv

A stage extends earlier choices; it does not replace them unless the plan explicitly introduces a new value.

---

## 3. Declarative Search Plan

The witness engine receives a YAML plan defining:

    constants
    point bindings
    derived bindings
    MLP checkpoints
    ordered stages
    sweep variables
    device equations
    constraints
    scoring
    outputs
    pruning policy
    final residuals
    final constraints
    CSV aliases

Topology-specific electrical knowledge belongs in YAML rather than in `witness_engine.py`.

---

## 4. Independent-Point Initialization

For each CSV row, the engine constructs:

    base = constants
         + point bindings
         + derived bindings

The initial parent set is:

    parents = [{}]

The first stage therefore starts from the base operating/design quantities only.

---

## 5. Stage Execution

For every incoming parent:

    seed = base + parent

The stage then:

1. constructs sweep vectors,
2. forms the multidimensional grid,
3. computes derived variables,
4. evaluates declared MOS devices,
5. applies feasibility constraints,
6. selects feasible children,
7. globally limits/diversifies the stage output.

---

## 6. Sweep Construction

The current engine supports three practical sweep sources.

### Row interval

A variable can use a range already present in the independent design-space CSV.

### Model width interval

A width sweep is intersected with the trained MLP width domain so the search does not deliberately evaluate unsupported widths.

### Explicit expression interval

Lower and upper bounds may be computed from expressions in the current environment.

Sweep spacing may be:

    linear
    geometric

If the count is one, the interval midpoint is used.

---

## 7. Vectorized Grid Evaluation

For multiple sweep variables, NumPy mesh generation forms the Cartesian grid.

Example:

    Vtail: 81 points
    Vx:   121 points

gives:

    81 x 121 = 9,801 local candidates

for one parent.

The grid is evaluated as arrays. This batched/vectorized execution is essential to the current performance.

---

## 8. Derived Variables

A stage may define dependent quantities such as:

    Vy = Vx

or:

    W6 = 2 * W3 * W7 / W5

Derived expressions are broadcast across the grid. This allows current/width/node relations to remain declarative.

---

## 9. Generic Device Evaluation

Each stage device declares:

    name
    polarity
    width
    VGS
    VDS
    VBS

The engine evaluates these expressions and calls:

    MlpOracle.inside_domain(...)
    MlpOracle.predict(...)

The environment receives generic quantities such as:

    M1_domain
    M1_id
    M1_vdsat

The engine does not attach topology meaning to the device name.

---

## 10. Feasibility Mask

The local mask starts as `True` over the entire grid.

Every constraint is evaluated and ANDed into the mask.

Typical constraints include:

    model-domain validity
    saturation margin
    target-current matching
    current balance
    width bounds
    topology relationships

A grid point remaining `True` is locally feasible for the current parent.

The total feasible-grid count is recorded for each stage and later written to the witness CSV.

---

## 11. Relative Error

The current normalized relative error is:

    |value - target|
    -------------------------------
    max(|value|, |target|, epsilon)

This avoids division by zero and provides scale-independent current matching.

---

## 12. Parent-Child Correlation

Correlation is preserved by copying the complete parent before adding stage outputs.

Example:

    parent:
        Vtail
        Vx

    stage selects:
        Vbias
        W5

    child:
        Vtail
        Vx
        Vbias
        W5

The next stage inherits all four values.

This is the defining mechanism that prevents unrelated independently valid ranges from being combined into a false operating point.

---

## 13. Stage Selection Modes

The engine currently supports two modes.

### `all_feasible`

Every feasible grid point for a parent is initially retained.

A later global diversity cap may still reduce the combined stage output.

This mode is important when early pruning could eliminate branches needed by later stages.

### `representative`

The engine retains a limited number of representatives.

The current representative selector considers:

1. minimum stage score,
2. minimum of each selection coordinate,
3. maximum of each selection coordinate.

Duplicates are removed and selection stops at:

    per_parent_keep

This deliberately mixes locally best candidates with boundary candidates.

---

## 14. Why Early Selection Matters

Local quality does not guarantee downstream feasibility.

A candidate with a slightly worse local score may be the only one that connects successfully to a later device or node.

Therefore:

    aggressive pruning -> lower runtime
    aggressive pruning -> higher risk of losing valid future paths

This was directly observed during regression: an early stage was unintentionally reduced to only a few representatives, causing a known valid independent point to lose all witnesses. Honoring `selection_mode: all_feasible` before global diversity capping restored the witnesses.

The key lesson is:

> Local stage quality and future branch value are not the same quantity.

---

## 15. Global Diversity Cap

After all parents have been expanded for one stage, all children are combined.

The optional:

    global_cap

limits the number of correlated states passed forward.

If:

    global_cap <= 0

no global cap is applied.

Otherwise `_cap_diverse()` tries to preserve coverage using:

    diversity_keys

instead of taking arbitrary children.

---

## 16. Current Diversity Strategy

For each diversity key, the engine first attempts to retain:

    minimum
    maximum
    nearest median

If more slots remain, records are sorted lexicographically by the diversity keys and approximately evenly spaced positions through that ordering are selected.

This is deterministic and inexpensive, but it is not an optimal multidimensional space-filling method.

It is one of the most important approximation points in the current algorithm.

---

## 17. Search Complexity

Let:

    Pk = number of parents entering stage k
    Gk = grid points per parent
    Dk = devices evaluated at stage k

Then approximate MLP work is:

    work_k ~ Pk * Gk * Dk

Without pruning, candidate population can grow approximately as:

    P(k+1) ~ Pk * Gk * feasible_fraction

which can become exponential across stages.

With a positive global cap:

    P(k+1) <= global_cap

The algorithm therefore trades exhaustive completeness for bounded computation.

---

## 18. Stage Ordering

Stage order is declared by the plan and strongly affects runtime and coverage.

Good early stages ideally:

    are relatively inexpensive
    impose strong physical constraints
    eliminate large infeasible regions
    preserve variables important downstream

Poor ordering can allow candidate populations to explode before strong constraints become available.

Automatic stage ordering is an important future-development direction.

---

## 19. Complete Candidates and Final Reevaluation

After the final stage, every surviving parent is a complete correlated candidate.

The engine reevaluates all final devices in one consistent candidate environment.

This is important because stage constraints are local, while final circuit consistency is global.

---

## 20. Final Residuals

The final plan declares circuit residuals such as:

    tail KCL
    internal-node KCL
    mirror balance
    output KCL
    target-current mismatch

For each candidate:

    r = [r1, r2, ..., rn]

The engine computes:

    max_abs_residual = max(|ri|)

and:

    rms_residual = sqrt(mean(ri^2))

Candidates are ranked lexicographically by:

    1. minimum max_abs_residual
    2. minimum rms_residual

This prioritizes reducing the worst remaining circuit inconsistency.

---

## 21. Final Constraints

The final block can reapply:

    model-domain checks
    saturation constraints
    complete-circuit topology constraints
    other final requirements

Only candidates satisfying all final constraints are ranked.

---

## 22. Saturation Headroom

The plan defines saturation-headroom expressions such as:

    VDS - VDSAT

These values are written per device.

The final `all_saturated` flag is true only when all declared headrooms exceed the configured saturation margin.

---

## 23. Witness Selection

The ranked complete candidates are truncated to:

    witnesses_per_point

A successful point produces rows with:

    generation_status = WITNESS
    witness_rank = 1..N

A point with no surviving candidate produces one bookkeeping row:

    generation_status = NO_WITNESS
    witness_rank = 0

`NO_WITNESS` means no witness was found under the current plan, resolution, pruning policy, and MLP domain. It is not a mathematical proof that the physical circuit has no valid operating point.

---

## 24. Diagnostic Output

The witness CSV includes:

    point index
    point source status
    witness rank
    max residual
    RMS residual
    saturation flag
    complete candidate count
    point runtime
    plan-defined node/width/current aliases
    individual residuals
    per-device saturation headroom
    per-device predicted current
    feasible-grid count for every stage

Stage feasible counts are especially important for debugging.

For example:

    stage1_feasible = 547
    stage2_feasible = 2123
    stage3_feasible = 0

localizes the failure to stage 3.

---

## 25. Main Search Controls

The current plan exposes:

### `count`

Sweep-grid resolution.

### `spacing`

Linear or geometric sweep spacing.

### `per_parent_keep`

Maximum representatives retained per parent in representative mode.

### `selection_mode`

    representative
    all_feasible

### `selection_coordinates`

Coordinates used for representative boundary selection.

### `global_cap`

Maximum total states retained after a stage.

### `diversity_keys`

Coordinates used by global diversity capping.

### `witnesses_per_point`

Number of final ranked witnesses written for each independent point.

This final number does not control intermediate search breadth.

---

## 26. Exact vs Approximate Behavior

The algorithm is exact only with respect to the points it actually evaluates.

For evaluated points:

    parent-child correlation is preserved
    MLP predictions are deterministic
    constraints are explicitly evaluated
    final residuals are explicitly computed

The continuous search remains approximate because of:

    finite sweep resolution
    representative selection
    global caps
    stage ordering
    MLP approximation
    trained-domain boundaries

This distinction should remain explicit in all future OpenAMS work.

---

## 27. Current Strengths

The present algorithm provides:

    topology-generic execution
    correlated complete paths
    vectorized MLP evaluation
    declarative circuit equations
    bounded search growth
    deterministic selection
    detailed stage diagnostics
    direct ngspice-verifiable outputs

---

## 28. Current Limitations

The present implementation does not yet provide:

    adaptive grid refinement
    backtracking
    uncertainty-aware MLP search
    search reuse across nearby independent points
    automatic stage ordering
    automatic witness-plan compilation
    sophisticated geometric/electrical deduplication
    continuous local refinement after grid search

These are natural areas for future development.

---

## 29. Critical Risk: Premature Pruning

The most important current algorithmic risk is branch loss.

Example:

    5,000 locally feasible children
            |
            v
        retain only 3
            |
            v
      later stage fails

This may indicate either:

    true circuit infeasibility

or:

    the needed branch was discarded too early

Therefore future work should focus on smarter pruning rather than simply increasing every cap.

---

## 30. Enhancement: Adaptive Resolution

A future stage could use:

    coarse grid
        |
        v
    identify promising/feasible regions
        |
        v
    locally refine those regions

This can improve continuous-space coverage without evaluating the entire fine grid.

Possible refinement triggers:

    low current error
    low KCL residual
    near-saturation boundary
    sparse downstream survival
    local residual minima

---

## 31. Enhancement: Adaptive Branch Budgets

Search budget can depend on branch importance.

Larger budgets may be assigned to branches that are:

    electrically unique
    close to difficult constraints
    associated with sensitive devices
    in sparse regions
    historically important for downstream survival

Redundant branches can receive smaller budgets.

---

## 32. Enhancement: Better Diversity

Possible replacements or additions to the current diversity heuristic include:

    farthest-point sampling
    k-center
    maximin distance
    k-means representatives
    Pareto-front retention
    Latin-hypercube-like retention

Diversity should eventually consider both:

    geometric design coordinates

and:

    electrical behavior

---

## 33. Enhancement: Electrical Deduplication

Two geometrically different candidates may produce nearly identical:

    node voltages
    currents
    VDSAT headroom
    residuals
    gm/Id

Such candidates are electrically redundant.

Clustering or deduplication in normalized electrical feature space could reduce path count without sacrificing meaningful coverage.

---

## 34. Enhancement: Residual-Aware Beam Search

The current algorithm is similar to a bounded staged beam search, but selection is mainly local.

A future beam score could combine:

    local residual quality
    diversity
    saturation robustness
    predicted downstream feasibility

The main danger is over-favoring the locally best candidates and losing alternative valid branches.

---

## 35. Enhancement: Backtracking

A failed late stage could trigger expansion of previously discarded candidates.

Concept:

    start with modest caps
            |
            v
    later stage gets zero survivors
            |
            v
    reopen earlier discarded candidates
            |
            v
    expand search only where needed

This can provide better coverage than fixed aggressive pruning without paying the cost of maximum breadth everywhere.

---

## 36. Enhancement: Constraint-Directed Search

Instead of sweeping a broad grid and then masking, the engine could use known circuit constraints to reduce intervals before MLP evaluation.

Examples:

    current bounds
    saturation-derived voltage bounds
    mirror relations
    density relationships
    known shared-node equations

This may substantially reduce wasted MLP evaluations.

---

## 37. Enhancement: Continuous Refinement

The MLP is continuous even though the initial search is gridded.

A promising grid witness could seed bounded continuous refinement of:

    node voltages
    widths
    bias voltages

Possible methods:

    bounded least squares
    scalar Brent search
    trust-region optimization
    derivative-free minimization

Continuous refinement should improve a correlated witness, not replace the robust staged feasibility search.

---

## 38. Enhancement: MLP Gradients and Uncertainty

Because the technology surrogate is a neural network, future versions may exploit gradients for:

    current matching
    KCL minimization
    sensitivity analysis
    adaptive sweep direction

A future oracle may also estimate uncertainty.

Uncertainty could influence:

    search margins
    refinement
    ngspice validation priority
    confidence near domain boundaries

---

## 39. Enhancement: Reuse Across Independent Points

Independent design points are often geometrically close.

Witnesses from neighboring points may provide good seeds for:

    node voltages
    widths
    bias states

This can turn isolated independent-point searches into continuation across the design space.

---

## 40. Enhancement: Automatic Stage and Plan Generation

Today:

    engineer writes witness-plan YAML

Long term:

    SPICE
      +
    design_rules.yaml
      +
    design_intent.yaml
        |
        v
    compiled dependency graph
        |
        v
    generated witness plan
        |
        v
    generic witness engine

The current YAML plan can therefore be viewed as the target intermediate representation for a future frontend/compiler.

---

## 41. Development Metrics

Algorithm changes should be evaluated with multiple metrics.

### Coverage

Fraction of independent points producing witnesses.

### Classification regression

Agreement of WITNESS / NO_WITNESS with known-good baselines.

### Witness quality

    best max_abs_residual
    best rms_residual

### Search cost

    MLP calls
    MLP points
    runtime per point

### Search growth

    feasible count per stage
    retained parents per stage
    complete candidate count

### Diversity

Spread of retained candidates in geometric and electrical feature space.

### ngspice success

Fraction of generated witnesses that reproduce acceptably in ngspice.

Runtime alone is not a sufficient optimization metric.

---

## 42. Current Regression Baseline

The cleaned generic engine has been regression-tested against archived OpenAMS results on:

    two-stage op-amp
    folded cascode

For 100 tested points of each topology, the cleaned engine preserved the archived WITNESS / NO_WITNESS classification for all points.

Residual values can differ because the generic engine may retain different valid candidates.

For future development, witness-existence coverage should remain a primary regression criterion, with residual quality and ngspice agreement evaluated separately.

---

## 43. Pseudocode

    for row in independent_design_space:

        base = bind_constants_and_point_variables(row)
        parents = [{}]

        for stage in witness_plan.stages:

            children = []

            for parent in parents:

                seed = base + parent

                grid = build_stage_grid(seed)

                derive_stage_variables(grid)

                evaluate_stage_devices_with_mlp(grid)

                feasible = apply_stage_constraints(grid)

                if selection_mode == all_feasible:
                    selected = all feasible points
                else:
                    selected = representative feasible points

                children += extend(parent, selected)

            parents = diversity_cap(children)

        complete_candidates = parents

        reevaluate_all_final_devices(complete_candidates)

        residuals = compute_global_residuals()

        valid = apply_final_constraints()

        rank valid candidates by:
            1. max absolute residual
            2. RMS residual

        write best N witnesses

---

## 44. Core Invariants

Future implementations may change:

    sweep generation
    pruning
    scoring
    optimization method
    stage ordering
    device-model implementation

but should preserve three invariants.

### Invariant 1 — Correlation

A witness must represent one complete internally consistent candidate path.

### Invariant 2 — Generic topology execution

Topology-specific circuit equations should remain declarative or compiled, not hard-coded into the search engine.

### Invariant 3 — Verifiability

Every generated witness must contain enough information to be instantiated and independently checked by ngspice.

These invariants define the core OpenAMS witness-search architecture.
