# Concrete ngspice optimization runtime leaf

## Purpose

This slice adds the concrete infrastructure leaf required by the repository
optimization composition root.

```text
assignment-oriented ngspice workflow
        ↓
AssignmentWorkflowExecutorAdapter
        ↓
CandidateEvaluationEngineAdapter
        ↓
OptimizationCyclePersistence
        ↓
OptimizationApplicationService
        ↓
ReferenceProposerRunPlanExecutor
```

The factory returns the exact `OptimizationRunPlanExecutor` expected by
`OptimizationCompositionRoot`.

## Runtime configuration

```json
{
  "schema_version": 1,
  "ngspice_optimization": {
    "assignment_workflow_factory": "project_runtime:create_assignment_workflow",
    "objectives_factory": "project_runtime:create_objectives",
    "proposer": "grid",
    "points_per_dimension": 3,
    "include_candidate_id": true,
    "candidate_id_field": "candidate_id"
  }
}
```

Optional:

```json
"screening_results_getter_factory":
  "project_runtime:create_screening_results_getter"
```

The default getter reads:

```text
workflow_result.screening_summary.cases
```

## Composition-root configuration

The repository composition configuration can now reference:

```json
{
  "schema_version": 1,
  "composition": {
    "run_plan_executor_factory":
      "openams.optimization.ngspice_runtime:create_run_plan_executor",
    "plan_subdirectory": "plan",
    "require_session_artifact": true
  }
}
```

Set the leaf configuration path with:

```bash
export OPENAMS_NGSPICE_OPTIMIZATION_CONFIG=ngspice_runtime.json
```

Then launch through the normal CLI.

## Reference contract-search proposer

The leaf supplies a default proposer when the normalized launch request does
not explicitly supply one.

Supported deterministic references:

```text
grid
midpoint
```

Direct simulation remains unchanged because direct assignments use
`DirectAssignmentProposer` inside the application service.

## Persistence

The concrete leaf enables all existing persistence layers:

```text
workflow/workflow_result.json
evaluation/candidate_evaluation.json
session/optimization_session.json
```

Those artifacts are then linked through:

```text
plan/optimization_run_plan.json
optimization_launch_manifest.json
```

## Adapter corrections

This slice also corrects two existing integration mismatches.

### Candidate evaluation

`CandidateEvaluationEngine` owns its objective definitions at construction.
The adapter now calls:

```python
engine.evaluate_many(screening_results)
```

rather than attempting to pass objectives a second time.

### Workflow persistence

The repository `SimulationWorkflowPersistence` returns:

```text
workflow_json
```

The adapter now accepts both:

```text
workflow_json
workflow_result_json
```

for compatibility.

## Remaining topology boundary

The topology-specific runtime module still constructs the assignment-oriented
ngspice workflow and objective definitions. It no longer constructs any
optimization application, persistence, routing, or launch services.
