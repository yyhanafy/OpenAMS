from __future__ import annotations

import json
from pathlib import Path

from openams.cli import launch_validated_optimization


class FakeReport:
    def to_dict(self):
        return {
            "schema_version": 1,
            "status": "valid",
            "composition_path": "/config/runtime.json",
        }


def test_validated_launch_runs_preflight_before_launch(
    tmp_path: Path,
    monkeypatch,
):
    events = []

    class FakePreflight:
        def validate(self, path):
            events.append(("preflight", Path(path)))
            return FakeReport()

    def fake_launch(argv):
        events.append(("launch", list(argv)))
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

    config = tmp_path / "composition.json"
    result = launch_validated_optimization.main(
        [
            "--runtime-config",
            str(config),
            "--input",
            "launch.json",
            "--output-dir",
            "runtime/run_0001",
        ]
    )

    assert result == 0
    assert events == [
        ("preflight", config),
        (
            "launch",
            [
                "--runtime-config",
                str(config),
                "--input",
                "launch.json",
                "--output-dir",
                "runtime/run_0001",
            ],
        ),
    ]


def test_invalid_preflight_prevents_launch(
    tmp_path: Path,
    monkeypatch,
):
    class FakePreflight:
        def validate(self, path):
            raise (
                launch_validated_optimization
                .OptimizationRuntimePreflightError(
                    "broken runtime graph"
                )
            )

    called = {"launch": False}

    def fake_launch(argv):
        called["launch"] = True
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

    result = launch_validated_optimization.main(
        [
            "--runtime-config",
            str(tmp_path / "composition.json"),
            "--input",
            "launch.json",
        ]
    )

    assert result == 2
    assert called["launch"] is False


def test_preflight_report_can_be_persisted(
    tmp_path: Path,
    monkeypatch,
):
    class FakePreflight:
        def validate(self, path):
            return FakeReport()

    monkeypatch.setattr(
        launch_validated_optimization,
        "OptimizationRuntimePreflight",
        FakePreflight,
    )
    monkeypatch.setattr(
        launch_validated_optimization.launch_optimization,
        "main",
        lambda argv: 0,
    )

    output = tmp_path / "audit" / "preflight.json"
    result = launch_validated_optimization.main(
        [
            "--runtime-config",
            str(tmp_path / "composition.json"),
            "--preflight-output",
            str(output),
            "--input",
            "launch.json",
        ]
    )

    assert result == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "valid"


def test_launch_exit_code_is_preserved(
    tmp_path: Path,
    monkeypatch,
):
    class FakePreflight:
        def validate(self, path):
            return FakeReport()

    monkeypatch.setattr(
        launch_validated_optimization,
        "OptimizationRuntimePreflight",
        FakePreflight,
    )
    monkeypatch.setattr(
        launch_validated_optimization.launch_optimization,
        "main",
        lambda argv: 7,
    )

    result = launch_validated_optimization.main(
        [
            "--runtime-config",
            str(tmp_path / "composition.json"),
            "--input",
            "launch.json",
        ]
    )

    assert result == 7
