from openams.synthesis.generic_complete_step5 import enumerate_independent_domains


def test_enumerates_continuous_and_discrete_domains():
    artifact = {
        "domains": {
            "w_m1_um": {
                "candidate_values": [],
                "technology_minimum": 1.0,
                "technology_maximum": 50.0,
            },
            "vnb1_v": {"candidate_values": [0.5, 0.6]},
            "i_m3_a": {"candidate_values": [1e-5, 2e-5, 3e-5]},
        }
    }
    names, combinations, values = enumerate_independent_domains(
        artifact,
        continuous_samples={"w_m1_um": 25},
        range_overrides={"w_m1_um": (1.0, 50.0)},
    )
    assert names == ["w_m1_um", "vnb1_v", "i_m3_a"]
    assert len(values["w_m1_um"]) == 25
    assert len(combinations) == 25 * 2 * 3
