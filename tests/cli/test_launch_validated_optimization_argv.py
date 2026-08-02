from __future__ import annotations

import sys

from openams.cli import launch_validated_optimization


class FakeReport:
    def to_dict(self):
        return {
            "schema_version": 1,
            "status": "valid",
        }


def test_main_none_reads_process_argv(monkeypatch):
    seen = {}

    class FakePreflight:
        def validate(self, path):
            seen["runtime_config"] = str(path)
            return FakeReport()

    def fake_launch(argv):
        seen["launch_argv"] = list(argv)
        return 0

    monkeypatch.setattr(
        launch_validated_optimization,
        "OptimizationRuntimePreflight",
        FakePreflight,
    )
    monkeypatch.setattr(
        launch_validated_optimization.launch_optimization,
        "main",
        fake_launch,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "launch_validated_optimization.py",
            "--runtime-config",
            "config/composition.json",
            "--input",
            "runtime/launch.json",
            "--output-dir",
            "runtime/run",
        ],
    )

    assert launch_validated_optimization.main() == 0
    assert seen["runtime_config"] == (
        "config/composition.json"
    )
    assert seen["launch_argv"] == [
        "--runtime-config",
        "config/composition.json",
        "--input",
        "runtime/launch.json",
        "--output-dir",
        "runtime/run",
    ]
