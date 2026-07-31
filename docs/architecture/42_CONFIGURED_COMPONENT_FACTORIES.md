# Configured component factories

## Purpose

This slice removes the remaining environment-variable coupling between the
repository composition root and the ngspice infrastructure leaf.

Previously:

```text
optimization composition JSON
        ↓
zero-argument leaf factory
        ↓
OPENAMS_NGSPICE_OPTIMIZATION_CONFIG
        ↓
ngspice runtime JSON
```

Now:

```text
optimization composition JSON
        ↓
configured leaf factory
        ↓
ngspice runtime JSON path
```

## Backward-compatible factory form

The original string form remains valid:

```json
{
  "run_plan_executor_factory":
    "openams.optimization.ngspice_runtime:create_run_plan_executor"
}
```

This invokes the factory with no arguments.

## Configured factory form

The new object form passes explicit keyword arguments:

```json
{
  "schema_version": 1,
  "composition": {
    "run_plan_executor_factory": {
      "factory":
        "openams.optimization.ngspice_runtime:create_run_plan_executor",
      "kwargs": {
        "config_path": "config/ngspice_optimization.json"
      }
    },
    "plan_subdirectory": "plan",
    "require_session_artifact": true
  }
}
```

The resulting call is equivalent to:

```python
create_run_plan_executor(
    config_path="config/ngspice_optimization.json"
)
```

## Complete launch command

```bash
python -m openams.cli.launch_optimization \
  --input runtime/launch_input.json \
  --runtime-config config/optimization_composition.json
```

No ngspice runtime environment variable is required.

## Validation

The composition root validates:

- the factory reference;
- the keyword-argument object;
- factory import and callability;
- invocation compatibility;
- returned component type.

A factory invocation error is wrapped as:

```text
OptimizationCompositionError
```

with the original `TypeError` retained as the cause.

## Architectural result

All runtime dependencies are now traceable from the composition artifact:

```text
optimization_composition.json
        ├── run-plan executor factory
        ├── ngspice runtime configuration path
        ├── run-plan artifact directory
        └── session-artifact strictness
```

This improves reproducibility because the launch no longer depends on a hidden
secondary environment variable.
