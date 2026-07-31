from __future__ import annotations

from types import ModuleType
import sys

from openams.optimization.evaluation import (
    ObjectiveDefinition,
    ObjectiveDirection,
)
from openams.optimization.ngspice_runtime import (
    NgspiceOptimizationRuntimeFactory,
    NgspiceRuntimeSpec,
    ReferenceProposerRunPlanExecutor,
)
from openams.optimization.plan_executor import (
    RunPlanExecutionRequest,
)
from openams.optimization.run_plan import (
    OptimizationRouteSelector,
    SynthesisRunInput,
)


def install_runtime_module(monkeypatch):
    module = ModuleType("test_ngspice_components")
    module.create_workflow = lambda: (
        lambda assignments: assignments
    )
    module.create_objectives = lambda: (
        ObjectiveDefinition(
            name="gain",
            measurement="gain_db",
            analysis="ac",
            direction=ObjectiveDirection.MAXIMIZE,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "test_ngspice_components",
        module,
    )


def test_ngspice_leaf_builds_run_plan_executor(monkeypatch):
    install_runtime_module(monkeypatch)

    executor = NgspiceOptimizationRuntimeFactory().build(
        NgspiceRuntimeSpec(
            assignment_workflow_factory=(
                "test_ngspice_components:create_workflow"
            ),
            objectives_factory=(
                "test_ngspice_components:create_objectives"
            ),
            proposer="midpoint",
        )
    )

    assert isinstance(
        executor,
        ReferenceProposerRunPlanExecutor,
    )
    assert executor.contract_proposer.source == (
        "midpoint_reference"
    )


def test_contract_route_receives_default_reference_proposer(
    monkeypatch,
):
    install_runtime_module(monkeypatch)
    executor = NgspiceOptimizationRuntimeFactory().build(
        NgspiceRuntimeSpec(
            assignment_workflow_factory=(
                "test_ngspice_components:create_workflow"
            ),
            objectives_factory=(
                "test_ngspice_components:create_objectives"
            ),
            proposer="grid",
            points_per_dimension=2,
        )
    )

    plan = OptimizationRouteSelector().select(
        SynthesisRunInput(
            unresolved_ranges={"x": (0.0, 1.0)}
        )
    )
    seen = {}

    def execute(self, *, plan, request):
        seen["proposer"] = request.proposer
        return "cycle"

    super_class = executor.__class__.__mro__[1]
    monkeypatch.setattr(
        super_class,
        "execute",
        execute,
    )

    result = executor.execute(
        plan=plan,
        request=RunPlanExecutionRequest(
            session_id="session",
            batch_size=1,
        ),
    )

    assert result == "cycle"
    assert seen["proposer"] is executor.contract_proposer
