"""Small, deterministic design-of-experiments generators."""

from __future__ import annotations

import random

from aoa.models import DoeConfig, VariableSpec


def generate_design(config: DoeConfig, variables: list[VariableSpec]) -> list[dict[str, float]]:
    """Generate a reproducible LHS or random design in the requested bounds."""
    rng = random.Random(config.seed)
    samples = config.samples
    if samples == 0:
        return []
    if config.method == "random":
        return [
            {variable.name: rng.uniform(variable.lower, variable.upper) for variable in variables}
            for _ in range(samples)
        ]

    columns: dict[str, list[float]] = {}
    for variable in variables:
        strata = list(range(samples))
        rng.shuffle(strata)
        columns[variable.name] = [
            variable.lower + ((stratum + rng.random()) / samples) * (variable.upper - variable.lower)
            for stratum in strata
        ]
    return [
        {variable.name: columns[variable.name][row] for variable in variables}
        for row in range(samples)
    ]
