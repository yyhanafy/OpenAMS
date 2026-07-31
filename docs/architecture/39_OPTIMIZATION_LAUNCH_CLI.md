# Optimization launch CLI adapter

## Purpose

This slice exposes the atomic optimization launch service through a narrow CLI
boundary.

```text
normalized launch-input JSON
        ↓
OptimizationLaunchInputParser
        ↓
OptimizationLaunchRequest
        ↓
OptimizationLaunchService
        ↓
route/status/manifest summary
```

## Command

```bash
python -m openams.cli.launch_optimization \
  --input launch_input.json \
  --factory project_runtime:create_optimization_launch_service
```

The factory must be a zero-argument callable using:

```text
module:function
```

It must return an initialized `OptimizationLaunchService`.

This keeps simulator, evaluator, persistence, and proposer construction outside
the generic CLI adapter.

## Normalized input

```json
{
  "schema_version": 1,
  "launch_id": "launch_0001",
  "synthesis": {
    "assignments": [],
    "unresolved_ranges": {
      "vbias": {
        "lower": 0.6,
        "upper": 0.9
      }
    },
    "fixed_parameters": {
      "vdd": 1.8
    },
    "metadata": {}
  },
  "execution": {
    "session_id": "session_0001",
    "output_directory": "runtime/launch_0001",
    "batch_size": 8,
    "session_metadata": {},
    "iteration_metadata": {}
  },
  "metadata": {}
}
```

Ranges may also use the compact pair form:

```json
"vbias": [0.6, 0.9]
```

## Output

Successful CLI output is exactly one JSON object:

```json
{
  "manifest": "runtime/launch_0001/optimization_launch_manifest.json",
  "route": "contract_search",
  "status": "completed"
}
```

The CLI does not print duplicated assignment, evaluation, or workflow data.

## Factory boundary

The generic CLI intentionally does not decide:

- which simulator backend to instantiate;
- which evaluator to use;
- which proposer implements contract search;
- which persistence ports are enabled;
- which topology-specific adapters are required.

Those are composition-root responsibilities.

## Next slice

The next layer should add a repository composition root for the currently
supported ngspice workflow and reference proposers, allowing the CLI to run
without a project-specific factory module.
