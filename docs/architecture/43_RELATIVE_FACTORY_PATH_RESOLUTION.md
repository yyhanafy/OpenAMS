# Relative factory-path resolution

## Problem

Configured component factories introduced explicit runtime paths, but relative
paths were interpreted against the process working directory.

That made this command ambiguous:

```bash
cd /some/unrelated/directory

python -m openams.cli.launch_optimization \
  --input /repo/runtime/launch.json \
  --runtime-config /repo/config/optimization.json
```

A factory argument such as:

```json
"config_path": "ngspice/runtime.json"
```

could incorrectly resolve beneath `/some/unrelated/directory`.

## Resolution rule

Factory configuration can now declare which keyword arguments are paths:

```json
{
  "factory":
    "openams.optimization.ngspice_runtime:create_run_plan_executor",
  "kwargs": {
    "config_path": "ngspice/runtime.json"
  },
  "path_kwargs": [
    "config_path"
  ]
}
```

The resolved value is:

```text
/repo/config/ngspice/runtime.json
```

because the composition file is:

```text
/repo/config/optimization.json
```

## Complete composition example

```json
{
  "schema_version": 1,
  "composition": {
    "run_plan_executor_factory": {
      "factory":
        "openams.optimization.ngspice_runtime:create_run_plan_executor",
      "kwargs": {
        "config_path": "ngspice_optimization.json"
      },
      "path_kwargs": [
        "config_path"
      ]
    },
    "plan_subdirectory": "plan",
    "require_session_artifact": true
  }
}
```

## Behavior

For every name listed in `path_kwargs`:

- the name must exist in `kwargs`;
- the value must be a path string;
- an absolute path is preserved;
- a relative path resolves against the composition file directory;
- the normalized absolute string is passed to the factory.

Keyword arguments not listed in `path_kwargs` are never modified.

## In-memory specifications

When `OptimizationCompositionSpec.from_mapping(...)` is called without a
`base_directory`, path values remain unchanged.

This preserves deterministic programmatic construction and backward
compatibility.

## Reproducibility result

The runtime dependency chain is now independent of the shell working directory:

```text
composition artifact location
        ↓
declared path-valued factory arguments
        ↓
normalized absolute runtime paths
        ↓
infrastructure factory
```
