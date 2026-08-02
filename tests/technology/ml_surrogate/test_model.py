import torch
from openams.technology.ml_surrogate.model import MosMlp, MosMlpConfig

def test_model_shape_and_parameter_count():
    model = MosMlp(MosMlpConfig())
    assert model(torch.zeros(3, 5)).shape == (3, 5)
    count = sum(p.numel() for p in model.parameters())
    assert 40000 < count < 60000
