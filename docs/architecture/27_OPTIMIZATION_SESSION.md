# Optimizer-neutral proposal and session state

## Purpose

This layer introduces the first optimizer-facing state machine without binding
OpenAMS to Bayesian optimization, random search, gradient methods, or any other
specific candidate generator.

```text
ProposalRequest
        ↓
CandidateProposer protocol
        ↓
CandidateProposal[]
        ↓
OptimizationSession
        ↓
OptimizationSessionState
        ↓
OptimizerFeedback[]
        ↓
updated immutable session state
```

## Explicit route separation

Every session uses exactly one route:

```text
direct_simulation
contract_search
```

### Direct simulation

Used when assignments are fully resolved.

A direct-simulation proposal request:

- may contain fixed parameters;
- must not contain unresolved parameter ranges;
- bypasses executable-contract optimization.

### Contract search

Used only when synthesis leaves unresolved ranges.

A contract-search proposal request:

- must contain parameter bounds;
- may also contain non-overlapping fixed parameters;
- may be serviced by any optimizer implementing `CandidateProposer`.

This directly enforces the architectural decision that executable contracts and
optimization are not required for fully resolved assignments.

## Candidate proposal

Each proposal records:

- globally unique candidate identifier;
- parameter values;
- route;
- iteration index;
- proposal index;
- optional proposer source;
- metadata.

All parameter values must be finite.

## Immutable iteration history

An optimization session contains contiguous immutable iterations beginning at
zero.

Each iteration stores proposal records with status:

```text
proposed
evaluated
rejected
```

Evaluated records retain the complete `OptimizerFeedback`.

The service creates a new `OptimizationSessionState` for each transition rather
than mutating historical iteration records in place.

## Feedback ingestion

Feedback is matched by candidate identifier.

Feedback may remain partial: evaluated candidates are updated while candidates
without feedback remain proposed.

The following are rejected:

- feedback for an unknown candidate;
- feedback with a mismatched candidate identifier;
- proposals for the wrong iteration;
- proposals using the wrong route;
- duplicate candidate identifiers across the session.

## Optimizer-neutral protocol

```python
class CandidateProposer(Protocol):
    def propose(
        self,
        request: ProposalRequest,
    ) -> Sequence[CandidateProposal]:
        ...
```

A deterministic grid generator, FA-BO adapter, random sampler, or future
learned optimizer can all implement the same protocol.

## Next slice

The next layer should persist optimization sessions with:

- stable schema version;
- deterministic iteration-history JSON;
- proposal and feedback CSV files;
- reload validation;
- links to candidate-evaluation artifacts;
- resumable session reconstruction.
