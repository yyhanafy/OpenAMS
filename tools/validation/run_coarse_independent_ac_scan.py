#!/usr/bin/env python3
"""Unified OpenAMS coarse independent scan entry point.

Compatibility contract:
- Without ``--compiled-model``, run the frozen two-stage implementation exactly.
- With ``--compiled-model``, run the topology-generic compiled-model MLP backend.

The installer preserves the existing script as
``run_coarse_independent_ac_scan_two_stage_legacy.py``.
"""
from __future__ import annotations

import sys


def main() -> int:
    if "--compiled-model" in sys.argv[1:]:
        from run_generic_compiled_scan import main as generic_main
        return generic_main(sys.argv[1:])
    from run_coarse_independent_ac_scan_two_stage_legacy import main as legacy_main
    return legacy_main()



_LEGACY_MODULE = None


def _load_legacy_module():
    """Load the frozen two-stage implementation."""

    import importlib.util
    from pathlib import Path

    legacy_path = (
        Path(__file__).resolve().parent
        / "run_coarse_independent_ac_scan_two_stage_legacy.py"
    )

    spec = importlib.util.spec_from_file_location(
        "openams_two_stage_coarse_scan_legacy",
        legacy_path,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"cannot load legacy coarse-scan module: {legacy_path}"
        )

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _legacy_module():
    """Return the cached legacy two-stage module."""

    global _LEGACY_MODULE

    if _LEGACY_MODULE is None:
        _LEGACY_MODULE = _load_legacy_module()

    return _LEGACY_MODULE


def make_fieldnames():
    """Preserve the original public schema-v3 API."""

    return _legacy_module().make_fieldnames()



if __name__ == "__main__":
    raise SystemExit(main())
