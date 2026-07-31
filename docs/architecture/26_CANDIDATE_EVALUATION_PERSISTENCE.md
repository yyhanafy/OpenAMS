# Candidate evaluation persistence

## Purpose

This layer persists candidate evaluations, deterministic rankings, objective
components, and optimizer feedback while linking the records back to the
simulation workflow that produced them.

```text
CandidateEvaluationSummary
        ↓
CandidateEvaluationPersistence
        ├── candidate_evaluation.json
        ├── candidate_ranking.csv
        ├── objective_components.csv
        └── optimizer_feedback.json
```

## Stable schema

Current schema identifier:

```text
openams.candidate_evaluation.v1
```

The canonical JSON payload contains:

- schema version;
- artifact root;
- optional workflow-result link;
- complete candidate evaluations;
- states and aggregate scores;
- objective components;
- failure and unknown reasons;
- preserved screening records;
- deterministic ranking.

## Workflow linkage

When supplied, `workflow_result_path` is stored in
`candidate_evaluation.json`.

If the workflow artifact is located beneath the evaluation output directory,
the path is rewritten relative to that directory.

This allows the evaluation artifact to preserve a traceable relationship to the
simulation evidence without duplicating or rewriting the workflow result.

## Ranking CSV

`candidate_ranking.csv` contains rankable candidates only.

Stable columns include:

- rank;
- candidate identifier;
- state;
- aggregate score;
- rankable flag;
- known failure reasons;
- unknown reasons.

Rows follow the already-determined ranking order.

## Objective-component CSV

`objective_components.csv` contains one row per candidate-objective pair.

Stable columns include:

- candidate identifier and state;
- objective name;
- analysis and measurement;
- optimization direction;
- availability status;
- raw value;
- normalized value;
- weighted value;
- weight;
- unit;
- diagnostic.

Rows are sorted by candidate identifier and objective name.

## Optimizer feedback

`optimizer_feedback.json` contains the compact optimizer-facing form for every
candidate.

Feasibility remains three-state:

```text
true   → valid
false  → infeasible
null   → unknown
```

Unknown candidates are not silently converted into failed candidates.

## Reload support

`load_payload()` validates the candidate-evaluation schema before returning the
persisted dictionary.

Typed object reconstruction remains intentionally outside this slice.

## Next slice

The next layer should introduce a candidate-proposal protocol and optimization
session state that can:

- accept persisted optimizer feedback;
- request new candidate points;
- preserve iteration history;
- remain independent of a specific optimizer implementation;
- support direct simulation for resolved assignments and contract-based search
  only for unresolved ranges.
