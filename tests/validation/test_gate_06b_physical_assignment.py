import subprocess
import sys


def test_gate_06b_physical_assignment_help() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "tools/validation/validate_gate_06b_physical_assignment.py",
            "--help",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert completed.returncode == 0
    assert "--input-dir" in completed.stdout
