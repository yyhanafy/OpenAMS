"""Preflight and launch an OpenAMS optimization run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from openams.cli import launch_optimization
from openams.optimization.preflight import (
    OptimizationRuntimePreflight,
    OptimizationRuntimePreflightError,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the OpenAMS optimization runtime graph and "
            "launch only when preflight succeeds"
        ),
        add_help=False,
    )
    parser.add_argument(
        "--runtime-config",
        required=True,
        type=Path,
        help="Optimization composition JSON",
    )
    parser.add_argument(
        "--preflight-output",
        type=Path,
        help="Optional persisted preflight report JSON",
    )
    parser.add_argument(
        "--help",
        action="store_true",
        dest="show_help",
        help="Show this wrapper and launch CLI help",
    )
    return parser


def _render_report(report) -> str:
    return json.dumps(
        report.to_dict(),
        indent=2,
        sort_keys=True,
    )


def _persist_report(path: Path, rendered: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    wrapper_args, launch_args = parser.parse_known_args(argv)

    if wrapper_args.show_help:
        parser.print_help()
        print()
        print("Underlying launch command:")
        try:
            return launch_optimization.main(["--help"])
        except SystemExit as exc:
            return int(exc.code or 0)

    try:
        report = OptimizationRuntimePreflight().validate(
            wrapper_args.runtime_config
        )
    except OptimizationRuntimePreflightError as exc:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "invalid",
                    "stage": "preflight",
                    "error": str(exc),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    rendered = _render_report(report)
    print(rendered)

    if wrapper_args.preflight_output is not None:
        _persist_report(
            wrapper_args.preflight_output,
            rendered,
        )

    forwarded = [
        "--runtime-config",
        str(wrapper_args.runtime_config),
        *launch_args,
    ]
    return launch_optimization.main(forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
