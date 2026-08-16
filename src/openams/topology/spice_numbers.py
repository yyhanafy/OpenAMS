"""SPICE scalar parsing."""

from __future__ import annotations

import re

_NUMBER = re.compile(
    r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?"
    r"(?:meg|mil|t|g|k|m|u|n|p|f)?$",
    re.IGNORECASE,
)

_SUFFIX = {
    "t": 1e12,
    "g": 1e9,
    "meg": 1e6,
    "k": 1e3,
    "m": 1e-3,
    "u": 1e-6,
    "n": 1e-9,
    "p": 1e-12,
    "f": 1e-15,
    "mil": 25.4e-6,
}


def parse_spice_scalar(token: str) -> float | str:
    """Convert a complete SPICE numeric token to SI, otherwise preserve it."""

    text = token.strip()
    if not _NUMBER.fullmatch(text):
        return text

    lower = text.lower()
    suffix = ""
    for candidate in ("meg", "mil", "t", "g", "k", "m", "u", "n", "p", "f"):
        if lower.endswith(candidate):
            suffix = candidate
            lower = lower[: -len(candidate)]
            break
    return float(lower) * _SUFFIX.get(suffix, 1.0)
