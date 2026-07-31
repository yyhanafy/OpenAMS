# Backend-neutral candidate evaluation

## Purpose

This layer converts specification-screened simulation cases into explicit
candidate states, objective components, deterministic rankings, and compact
optimizer feedback.

```text
CaseScreeningResult
        +
ObjectiveDefinition[]
        ↓
CandidateEvaluationEngine
        ↓
CandidateEvaluation
        ├── valid
        ├── infeasible
        └── unknown
```

The original screening result remains attached to every candidate evaluation.

## Candidate states

```text
valid
infeasible
unknown
```

- `valid` means specification screening passed and all required objectives are
  available.
- `infeasible` means at least one known specification rule failed.
- `unknown` means feasibility or a required objective could not be determined.

Unknown candidates are not silently converted into infeasible candidates.

## Objective model

Each objective specifies:

- analysis and measurement;
- maximize or minimize direction;
- non-negative weight;
- optional normalization scale;
- reference value;
- required or optional status;
- optional unit.

Example:

```python
ObjectiveDefinition(
    name="power",
    measurement="power_w",
    analysis="dc",
    direction=ObjectiveDirection.MINIMIZE,
    reference_value=2e-3,
    normalization_scale=1e-3,
    weight=2.0,
)
```

For maximization:

```text
normalized = (value - reference) / scale
```

For minimization:

```text
normalized = (reference - value) / scale
```

The aggregate score is the sum of available weighted normalized components.

## Ranking

Only valid candidates with finite aggregate scores are rankable.

Ranking is deterministic:

1. higher aggregate score first;
2. candidate identifier as the tie breaker.

Infeasible and unknown candidates remain in the evaluation summary but are not
included in the ranking.

## Optimizer feedback

Each evaluation can emit a compact `OptimizerFeedback` record containing:

- candidate identifier;
- feasible `true`, `false`, or `null`;
- aggregate objective value;
- candidate state;
- known failure reasons;
- unknown reasons;
- individual objective components.

This format is optimizer-neutral and does not depend on Bayesian optimization,
gradient methods, or any specific search algorithm.

## Separation of responsibilities

This layer does not:

- execute simulations;
- parse simulator output;
- screen specifications;
- propose new candidates;
- update an optimizer model;
- choose topology or technology.

It consumes explicit screening evidence and produces explicit evaluation data.

## Next slice

The next layer should persist candidate evaluations and optimizer feedback with:

- stable schema version;
- deterministic ranking CSV;
- objective-component CSV;
- reload support;
- linkage back to the persisted simulation workflow.
