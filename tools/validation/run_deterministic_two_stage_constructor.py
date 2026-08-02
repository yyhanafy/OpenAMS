#!/usr/bin/env python3
from __future__ import annotations
import json, os
from pathlib import Path
from openams.synthesis.deterministic_two_stage_constructor import (
    ConstructionError, TwoStageConstructionPolicy, construct_two_stage_assignment,
)
from openams.technology.ml_continuous_oracle import MlpContinuousTechnologyOracle

def main() -> int:
    out = Path("examples/two_stage_opamp/generated/assignment_synthesis/deterministic_dependency")
    out.mkdir(parents=True, exist_ok=True)
    oracle = MlpContinuousTechnologyOracle(
        {"nmos":Path(os.environ["OPENAMS_MLP_NMOS"]),"pmos":Path(os.environ["OPENAMS_MLP_PMOS"])},
        out / "adaptive_mlp_points.csv",
    )
    policy = TwoStageConstructionPolicy(n1_v=0.60, vbias_v=0.60)
    try:
        assignment = construct_two_stage_assignment(
            oracle, i_m5_a=1.00164e-5, w_m1_um=16.0, vout_v=1.5, policy=policy,
        )
        artifact={"status":"PASS","assignment_count":1,"mlp_queries":oracle.query_count,"assignments":[assignment]}
        rc=0
    except ConstructionError as exc:
        artifact={"status":"NO_ASSIGNMENT","assignment_count":0,"mlp_queries":oracle.query_count,"failure":str(exc),"assignments":[]}
        rc=1
    path=out/"deterministic_assignment.json"
    path.write_text(json.dumps(artifact,indent=2)+"\n")
    print("===== OPENAMS DETERMINISTIC DEPENDENCY CONSTRUCTOR =====")
    print("status:",artifact["status"]); print("assignments:",artifact["assignment_count"]); print("MLP queries:",artifact["mlp_queries"])
    if "failure" in artifact: print("failure:",artifact["failure"])
    print("output:",path)
    return rc
if __name__ == "__main__": raise SystemExit(main())
