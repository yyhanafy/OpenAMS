# Deterministic reference candidate proposers

## Purpose

This slice provides concrete implementations of the optimizer-neutral
`CandidateProposer` protocol.

They are intentionally simple and reproducible. Their purpose is to validate
the proposal/session boundary and provide dependable integration-test
implementations before adding FA-BO or other adaptive optimizers.

## Direct assignment proposer

```text
fully resolved assignments
        ↓
DirectAssignmentProposer
        ↓
CandidateProposal[]
        ↓
direct simulation
```

The proposer:

- requires the `direct_simulation` route;
- rejects unresolved bounds;
- merges assignment values with fixed parameters;
- rejects conflicting fixed values;
- emits deterministic identifiers;
- performs no optimization.

This is the correct route for assignments fully resolved by topology and
technology synthesis.

## Grid-search proposer

```text
bounded unresolved variables
        ↓
GridSearchProposer
        ↓
deterministic Cartesian candidates
        ↓
contract-based evaluation
```

The proposer:

- requires the `contract_search` route;
- generates evenly spaced axes;
- sorts variable names before creating the Cartesian product;
- merges fixed parameters;
- returns candidates in deterministic order;
- rejects requests larger than the finite grid.

It is a reference search implementation, not the intended final optimizer.

## Midpoint proposer

`MidpointProposer` generates exactly one candidate at the center of every
bounded variable.

It is useful for:

- smoke tests;
- validating a newly built executable contract;
- confirming parameter rendering;
- checking end-to-end orchestration with one candidate.

## Candidate identifiers

Reference proposers generate identifiers using:

```text
<session>_iter_<iteration>_candidate_<proposal-index>
```

Unsafe session-identifier characters are replaced with underscores.

This makes identifiers reproducible while preserving global uniqueness within
the session.

## Separation from session orchestration

The proposers do not:

- modify session state;
- apply feedback;
- execute simulations;
- rank candidates;
- persist optimizer state;
- inspect simulator output.

`OptimizationSession.propose_and_record()` remains responsible for validating
and recording the generated batch.

## Next slice

The next layer should add the first end-to-end optimization-cycle orchestrator:

```text
proposal request
    ↓
propose and record
    ↓
render/simulate
    ↓
parse and screen
    ↓
evaluate
    ↓
apply feedback
    ↓
persist workflow, evaluation, and session artifacts
```

The orchestrator must preserve the direct-simulation bypass for fully resolved
assignments.
