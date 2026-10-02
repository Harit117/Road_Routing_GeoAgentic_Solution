"""Rainfall input: one intensity value (mm/h) per simulation tick.

Today the series comes from the request body or a named preset. An Open-Meteo
source only needs to produce the same RainfallSeries (its hourly
`precipitation` array maps 1:1 onto ticks when step_minutes = 60).
"""

from dataclasses import dataclass
from datetime import datetime

# Synthetic storms for demoing the simulation without a live feed.
PRESETS: dict[str, list[float]] = {
    "intensifying_storm": [0, 5, 8, 20, 35, 50, 45, 30, 15, 8, 4, 2, 0],
    "steady_moderate": [10.0] * 12,
    "cloudburst": [2, 4, 80, 95, 60, 10, 5, 2, 0, 0, 0, 0],
    "light_drizzle": [2, 3, 3, 4, 3, 2, 2, 1, 1, 0],
}


@dataclass(frozen=True)
class RainfallSeries:
    mm_per_hour: list[float]
    start: datetime
    source: str  # "manual", "preset:<name>", later "open-meteo"

    def __len__(self) -> int:
        return len(self.mm_per_hour)


def from_preset(name: str, start: datetime) -> RainfallSeries:
    if name not in PRESETS:
        raise KeyError(name)
    return RainfallSeries(list(PRESETS[name]), start, f"preset:{name}")


def from_values(values: list[float], start: datetime) -> RainfallSeries:
    if any(v < 0 for v in values):
        raise ValueError("rainfall cannot be negative")
    return RainfallSeries(list(values), start, "manual")
