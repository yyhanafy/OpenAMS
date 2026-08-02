# Validated optimization launch

## Purpose

The optimization launch path now has one repository-owned command that joins
preflight validation and execution.

```text
launch_validated_optimization
        ↓
OptimizationRuntimePreflight
        ↓ valid
launch_optimization
        ↓
OptimizationLaunchService
        ↓
persisted run-plan execution
```

If preflight fails, the launch command is never invoked.

## Command

```bash
python -m openams.cli.launch_validated_optimization \
  --runtime-config config/optimization_composition.json \
  --input runtime/launch_input.json \
  --output-dir runtime/optimization_run
```

All arguments not owned by the wrapper are forwarded unchanged to the existing
`launch_optimization` CLI.

The wrapper owns:

```text
--runtime-config
--preflight-output
--help
```

## Persisting the preflight report

```bash
python -m openams.cli.launch_validated_optimization \
  --runtime-config config/optimization_composition.json \
  --preflight-output runtime/optimization_preflight.json \
  --input runtime/launch_input.json \
  --output-dir runtime/optimization_run
```

This writes the normalized preflight report before launch.

## Exit codes

```text
0   preflight succeeded and launch succeeded
2   preflight failed; launch was not attempted
N   launch was attempted and returned its original nonzero code N
```

The wrapper preserves the underlying launch exit code.

## Failure boundary

An invalid runtime produces a structured response:

```json
{
  "schema_version": 1,
  "status": "invalid",
  "stage": "preflight",
  "error": "..."
}
```

This makes CI and scripted execution distinguish configuration failures from
simulation or optimization failures.

## Architectural result

The recommended external entry point is now:

```text
validate configuration
        +
launch optimization
        =
launch_validated_optimization
```

The standalone commands remain available for focused diagnostics:

```text
validate_optimization_runtime
launch_optimization
```
