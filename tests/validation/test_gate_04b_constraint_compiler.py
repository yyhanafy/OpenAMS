import json
import subprocess
import sys
from pathlib import Path


def test_gate_04b_constraint_compiler_validator(tmp_path: Path) -> None:
    constraints = [
        {
            "name": "balanced_input_left",
            "kind": "equality",
            "expression": "device.M1.current == 0.5 * device.M5.current",
            "source": "design_intent",
        },
        {
            "name": "balanced_input_right",
            "kind": "equality",
            "expression": "device.M2.current == 0.5 * device.M5.current",
            "source": "design_intent",
        },
        {
            "name": "active_load_left",
            "kind": "equality",
            "expression": "device.M3.current == device.M1.current",
            "source": "design_intent",
        },
        {
            "name": "active_load_right",
            "kind": "equality",
            "expression": "device.M4.current == device.M2.current",
            "source": "design_intent",
        },
        {
            "name": "output_node_kcl",
            "kind": "topology_derived",
            "expression": "device.M6.current == device.M7.current",
            "source": "design_intent",
        },
    ]

    constraint_path = tmp_path / "compiler_constraints.json"
    constraint_path.write_text(
        json.dumps(constraints),
        encoding="utf-8",
    )
    output_dir = tmp_path / "evidence"

    completed = subprocess.run(
        [
            sys.executable,
            "tools/validation/validate_gate_04b_constraint_compiler.py",
            "--constraints",
            str(constraint_path),
            "--output-dir",
            str(output_dir),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout

    summary = json.loads(
        (output_dir / "execution_results.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["status"] == "PASS"
    assert summary["compiled_constraint_count"] == 5
    assert summary["retained_count"] == 2
