from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[2] / "src" / "openams"

ALLOWED = {
    "model": set(),
    "io": set(),
    "metadata": {"model"},
    "topology": {"model", "metadata"},
    "constraints": {"model", "metadata", "topology"},
    "planning": {"model", "constraints"},
    "technology": {"model"},
    "synthesis": {"model", "planning", "technology"},
    "simulation": {"model"},
    "evaluation": {"model"},
    "adapters": {"io", "technology"},
}


def _openams_target(node: ast.AST) -> str | None:
    if isinstance(node, ast.Import):
        names = [alias.name for alias in node.names]
    elif isinstance(node, ast.ImportFrom):
        names = [node.module or ""]
    else:
        return None

    for name in names:
        if name.startswith("openams."):
            parts = name.split(".")
            if len(parts) >= 2:
                return parts[1]
    return None


def test_package_imports_follow_layer_policy() -> None:
    violations: list[str] = []

    for package, allowed in ALLOWED.items():
        package_dir = PACKAGE_ROOT / package
        if not package_dir.exists():
            continue

        for source in package_dir.rglob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
            for node in ast.walk(tree):
                target = _openams_target(node)
                if target is not None and target != package and target not in allowed:
                    violations.append(
                        f"{source.relative_to(PACKAGE_ROOT)} imports openams.{target}"
                    )

    assert violations == []
