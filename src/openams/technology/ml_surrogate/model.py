from __future__ import annotations

from dataclasses import asdict, dataclass

import torch
from torch import nn


@dataclass(frozen=True)
class MosMlpConfig:
    input_dim: int = 5
    output_dim: int = 5
    hidden_dims: tuple[int, ...] = (128, 128, 128, 64)

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["hidden_dims"] = list(self.hidden_dims)
        return value

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "MosMlpConfig":
        return cls(input_dim=int(value["input_dim"]), output_dim=int(value["output_dim"]),
                   hidden_dims=tuple(int(x) for x in value["hidden_dims"]))


class MosMlp(nn.Module):
    def __init__(self, config: MosMlpConfig = MosMlpConfig()) -> None:
        super().__init__()
        dims = (config.input_dim, *config.hidden_dims, config.output_dim)
        layers: list[nn.Module] = []
        for left, right in zip(dims[:-2], dims[1:-1]):
            layers.extend((nn.Linear(left, right), nn.SiLU()))
        layers.append(nn.Linear(dims[-2], dims[-1]))
        self.network = nn.Sequential(*layers)
        self.config = config

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.network(features)
