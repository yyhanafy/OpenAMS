from openams.synthesis.continuous_dependency_executor import ContinuousDependencyExecutor

def test_simple_chain():
    state, records = ContinuousDependencyExecutor().execute(
        initial_state={"i_m5_a": 10e-6, "w_m1_um": 16.0},
        rules=[
            {"id":"i1","operation":"divide","numerator":"i_m5_a","denominator":2,"output":"i_m1_a"},
            {"id":"i2","operation":"copy","source":"i_m1_a","output":"i_m2_a"},
            {"id":"w2","operation":"copy","source":"w_m1_um","output":"w_m2_um"},
        ],
    )
    assert state["i_m1_a"] == 5e-6
    assert state["i_m2_a"] == 5e-6
    assert state["w_m2_um"] == 16.0
    assert [r.rule_id for r in records] == ["i1","i2","w2"]
