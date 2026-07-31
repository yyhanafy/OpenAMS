"""Validate an optimization runtime composition without executing it."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from openams.optimization.preflight import (
    OptimizationRuntimePreflight,
    OptimizationRuntimePreflightError,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate OpenAMS optimization runtime wiring without "
            "launching simulations"
        )
    )
    parser.add_argument(
        "--runtime-config",
        required=True,
        type=Path,
        help="Optimization composition JSON",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional preflight report JSON path",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        report = OptimizationRuntimePreflight().validate(
            args.runtime_config
        )
    except OptimizationRuntimePreflightError as exc:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "invalid",
                    "error": str(exc),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    payload = report.to_dict()
    rendered = json.dumps(
        payload,
        indent=2,
        sort_keys=True,
    )
    print(rendered)

    if args.output is not None:
        args.output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        args.output.write_text(
            rendered + "\n",
            encoding="utf-8",
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
