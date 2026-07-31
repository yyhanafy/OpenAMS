"""CLI adapter for the atomic OpenAMS optimization launch service."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
from typing import Callable, Sequence

from openams.optimization.launch_input import (
    OptimizationLaunchInputParser,
)
from openams.optimization.launch_service import (
    OptimizationLaunchService,
)


class OptimizationLaunchCliError(RuntimeError):
    """Raised for CLI factory and wiring errors."""


def _load_factory(
    reference: str,
) -> Callable[[], OptimizationLaunchService]:
    if ":" not in reference:
        raise OptimizationLaunchCliError(
            "factory must use the form module:function"
        )

    module_name, function_name = reference.split(":", 1)
    if not module_name or not function_name:
        raise OptimizationLaunchCliError(
            "factory must use the form module:function"
        )

    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise OptimizationLaunchCliError(
            f"failed to import factory module: {module_name}"
        ) from exc

    factory = getattr(module, function_name, None)
    if not callable(factory):
        raise OptimizationLaunchCliError(
            f"factory is not callable: {reference}"
        )
    return factory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Launch an OpenAMS optimization workflow from a "
            "normalized synthesis-input JSON document"
        )
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Normalized optimization launch JSON",
    )
    parser.add_argument(
        "--factory",
        required=True,
        help=(
            "Zero-argument service factory using "
            "module:function syntax"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    request = OptimizationLaunchInputParser().load(args.input)
    service = _load_factory(args.factory)()

    if not isinstance(service, OptimizationLaunchService):
        raise OptimizationLaunchCliError(
            "factory did not return OptimizationLaunchService"
        )

    result = service.launch(request)
    summary = {
        "route": result.plan.route.value,
        "status": result.manifest.status.value,
        "manifest": str(result.manifest_json),
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
