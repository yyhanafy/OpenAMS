# Optimization-cycle adapters

## Purpose

This slice connects existing OpenAMS implementations to the narrow protocols
introduced by the optimization-cycle orchestrator.

```text
existing OpenAMS component
        ↓
adapter
        ↓
OptimizationCycleOrchestrator port
```

No simulator, evaluator, or persistence behavior is reimplemented here.

## Workflow execution adapters

### WorkflowBatchExecutorAdapter

Use when an existing workflow already accepts
`Sequence[CandidateProposal]`.

```text
CandidateProposal[]
        ↓
existing workflow callable
        ↓
workflow result
```

### AssignmentWorkflowExecutorAdapter

Use when an existing workflow accepts assignment mappings.

```text
CandidateProposal[]
        ↓
ProposalAssignmentMapper
        ↓
assignment dictionaries
        ↓
existing fixed-assignment workflow
```

By default, the mapper includes:

```text
candidate_id
```

alongside the sorted numeric parameters.

This preserves proposal identity through rendering, simulation, parsing, and
screening.

## Evaluation adapter

`CandidateEvaluationEngineAdapter` extracts screening results from a workflow
result and forwards them to the existing `CandidateEvaluationEngine`.

```text
workflow result
        ↓ screening_results_getter
CaseScreeningResult[]
        ↓ CandidateEvaluationEngine
CandidateEvaluationSummary
```

The extractor is supplied by the caller because workflow-result container
shapes may differ.

## Persistence adapters

The persistence chain is:

```text
WorkflowPersistenceAdapter
        ↓ workflow_result.json

CandidateEvaluationPersistenceAdapter
        ↓ candidate_evaluation.json

OptimizationSessionPersistenceAdapter
        ↓ optimization_session.json
```

Each adapter uses a dedicated subdirectory by default:

```text
workflow/
evaluation/
session/
```

Artifact links are forwarded through the chain.

## Translation-only rule

Adapters may:

- translate proposal objects into assignment mappings;
- select the primary artifact path from an artifact bundle;
- forward artifact links;
- call an existing implementation.

Adapters must not:

- modify candidate parameters;
- change screening outcomes;
- recompute objective values;
- reinterpret feasibility;
- alter ranking;
- create optimizer policy;
- bypass route validation.

## Next slice

The next layer should create a concrete cycle factory or application service
that assembles:

- proposer;
- assignment workflow executor;
- evaluation engine;
- workflow persistence;
- evaluation persistence;
- session persistence;
- optimization-cycle orchestrator.

It should expose one high-level operation for direct simulation and one for
contract search while reusing the same orchestration core.
