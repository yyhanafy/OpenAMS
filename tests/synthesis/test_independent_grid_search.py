from openams.synthesis.independent_grid_search import GridPoint, inclusive_grid, one_point_independent_regions

def test_inclusive_grid():
    assert inclusive_grid(0.5, 0.7, 0.1) == [0.5, 0.6, 0.7]

def test_one_point_regions():
    base = {"domains": {"i_m5_a": {}, "w_m1_um": {}, "vout_v": {}}}
    p = GridPoint(0, 20e-6, 10.0, 1.2)
    result = one_point_independent_regions(base, p)
    assert result["domains"]["i_m5_a"]["candidate_values"] == [20e-6]
    assert result["domains"]["w_m1_um"]["candidate_values"] == [10.0]
    assert result["domains"]["vout_v"]["candidate_values"] == [1.2]
