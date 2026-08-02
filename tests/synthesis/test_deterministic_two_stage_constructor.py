from openams.synthesis.deterministic_two_stage_constructor import TwoStageConstructionPolicy

def test_policy_is_explicit():
    policy=TwoStageConstructionPolicy(n1_v=0.6,vbias_v=0.6)
    assert policy.n1_v == 0.6
    assert policy.vbias_v == 0.6
