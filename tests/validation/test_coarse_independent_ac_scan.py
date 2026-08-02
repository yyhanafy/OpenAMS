import numpy as np


def test_requested_grid_size() -> None:
    i5 = list(range(40))
    w1 = np.linspace(1.0, 50.0, 25)
    vout = np.linspace(0.6, 1.5, 10)
    assert len(i5) * len(w1) * len(vout) == 10000
    assert w1[0] == 1.0
    assert w1[-1] == 50.0
    assert np.isclose(vout[1] - vout[0], 0.1)
