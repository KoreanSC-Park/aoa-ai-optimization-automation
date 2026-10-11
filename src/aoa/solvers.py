"""Deterministic, license-free mathematical mock solver."""

from __future__ import annotations

import math
from typing import Literal


MOCK_SOLVER_VERSION = "1"


def solve_mock(kind: Literal["sphere", "rosenbrock", "branin"], parameters: dict[str, float]) -> dict[str, float]:
    """Return one metric from a standard benchmark, without external solver access."""
    ordered = list(parameters.values())
    if kind == "sphere":
        value = sum(number * number for number in ordered)
    elif kind == "rosenbrock":
        if len(ordered) < 2:
            raise ValueError("Rosenbrock requires at least two variables")
        value = sum(
            100.0 * (ordered[index + 1] - ordered[index] ** 2) ** 2 + (1.0 - ordered[index]) ** 2
            for index in range(len(ordered) - 1)
        )
    elif kind == "branin":
        if len(ordered) < 2:
            raise ValueError("Branin requires at least two variables")
        x, y = ordered[:2]
        a, b, c = 1.0, 5.1 / (4.0 * 3.141592653589793**2), 5.0 / 3.141592653589793
        r, s, t = 6.0, 10.0, 1.0 / (8.0 * 3.141592653589793)
        value = a * (y - b * x**2 + c * x - r) ** 2 + s * (1.0 - t) * math.cos(x) + s
    else:  # Pydantic prevents this; defensive for direct calls.
        raise ValueError(f"Unsupported mock solver: {kind}")
    return {kind: float(value), "objective": float(value)}
