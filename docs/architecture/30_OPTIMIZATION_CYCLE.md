# End-to-end optimization-cycle orchestrator

## Purpose

This slice connects the optimizer-neutral layers into one complete iteration.

```text
ProposalRequest
        ↓
CandidateProposer
        ↓
CandidateProposal[]
        ↓
record proposals
        ↓
CandidateBatchExecutor
        ↓
execution/workflow result
        ↓
CandidateBatchEvaluator
        ↓
CandidateEvaluationSummary
        ↓
OptimizerFeedback[]
        ↓
apply feedback
        ↓
persist workflow → evaluation → session
```

## Orchestrator boundary

`OptimizationCycleOrchestrator` owns ordering and validation.

It does not own:

- topology synthesis;
- executable-contract construction;
- SPICE rendering;
- simulator invocation;
- raw-result parsing;
- specification rules;
- objective definitions;
- candidate-ranking policy;
- optimizer model state.

These concerns enter through explicit protocols.

## Execution protocol

```python
class CandidateBatchExecutor(Protocol):
    def execute(
        self,
        proposals: Sequence[CandidateProposal],
    ) -> Any:
        ...
```

A concrete OpenAMS executor may internally perform:

```text
render assignments
→ generate simulator inputs
→ run ngspice
→ parse raw outputs
→ screen specifications
```

The cycle orchestrator only requires the returned workflow result.

## Evaluation protocol

```python
class CandidateBatchEvaluator(Protocol):
    def evaluate(
        self,
        execution_result: Any,
    ) -> CandidateEvaluationSummary:
        ...
```

This preserves the candidate-evaluation engine as a replaceable policy layer.

## Candidate coverage

Every proposed candidate must produce exactly one optimizer-feedback record.

The cycle rejects:

- missing candidate feedback;
- feedback for candidates not proposed in the batch;
- duplicate evaluation candidate identifiers;
- stale proposal requests;
- proposer batch-size mismatches.

This prevents partial simulator or parser failures from silently disappearing
from optimization history. Such cases must be represented explicitly as
`unknown` feedback.

## Route preservation

The route comes from `OptimizationSessionState` and remains unchanged through
the cycle.

```text
direct_simulation
    fully resolved assignments
    no optimization contract required

contract_search
    unresolved bounded variables
    candidate proposer required
```

The orchestrator does not force fully resolved assignments through the
contract-search path.

## Persistence order

When persistence services are supplied, artifacts are written in dependency
order:

```text
workflow artifact
        ↓ link
candidate-evaluation artifact
        ↓ link
optimization-session artifact
```

Persistence remains optional. A cycle may run entirely in memory.

## Result

`OptimizationCycleResult` contains:

- iteration index;
- route;
- proposals;
- raw execution result;
- evaluation summary;
- optimizer feedback;
- updated immutable session state;
- primary artifact links;
- valid, infeasible, and unknown counts.

## Next slice

The next layer should provide concrete adapters from the existing OpenAMS
workflow, evaluation persistence, and session persistence implementations to
the cycle protocols.

That slice should avoid modifying their internal behavior. It should only
translate between established interfaces and the new orchestrator boundary.
