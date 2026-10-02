"""Replaceable rainfall sources for scenario files, presets, and future feeds."""

import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from app.flood.models import RainfallStep
from app.simulation.rainfall import PRESETS


SCENARIO_NAMES = ("normal", "moderate", "heavy", "extreme")


class RainfallProvider(Protocol):
    def get_scenario(self, scenario: str) -> list[RainfallStep]:
        """Return an ordered rainfall time series for one named scenario."""


class HistoricalScenarioRainfallProvider:
    """Load the generated historical scenarios once at service startup."""

    def __init__(self, processed_dir: Path):
        path = processed_dir / "rainfall_scenarios.csv"
        scenarios: dict[str, list[RainfallStep]] = {name: [] for name in SCENARIO_NAMES}
        with path.open(encoding="utf-8", newline="") as source:
            for row in csv.DictReader(source):
                name = row["scenario"]
                if name not in scenarios:
                    continue
                scenarios[name].append(
                    RainfallStep(
                        time=datetime.fromisoformat(row["time"]),
                        rainfall_mm=float(row["rain_mm"]),
                    )
                )
        for name, steps in scenarios.items():
            steps.sort(key=lambda item: item.time)
            if len(steps) != 48:
                raise ValueError(
                    f"historical scenario {name!r} must contain 48 hourly rows; "
                    f"found {len(steps)}"
                )
            if any(
                current.time - previous.time != timedelta(hours=1)
                for previous, current in zip(steps, steps[1:])
            ):
                raise ValueError(f"historical scenario {name!r} is not hourly")
        self._scenarios = scenarios

    @property
    def scenario_names(self) -> tuple[str, ...]:
        return SCENARIO_NAMES

    def get_scenario(self, scenario: str) -> list[RainfallStep]:
        try:
            return list(self._scenarios[scenario])
        except KeyError as error:
            raise KeyError(scenario) from error


class PresetRainfallProvider:
    """Adapter for existing generic simulation presets."""

    @staticmethod
    def get_series(name: str, start: datetime, step_minutes: int) -> list[RainfallStep]:
        try:
            values = PRESETS[name]
        except KeyError as error:
            raise KeyError(name) from error
        duration = step_minutes / 60
        return [
            RainfallStep(
                time=start + timedelta(minutes=(index + 1) * step_minutes),
                rainfall_mm=value * duration,
                duration_hours=duration,
            )
            for index, value in enumerate(values)
        ]


class SequenceRainfallProvider:
    """Adapter for caller-supplied hourly rainfall; usable for a live-feed bridge."""

    @staticmethod
    def from_values(
        values_mm_per_hour: list[float], start: datetime, step_minutes: int
    ) -> list[RainfallStep]:
        if not values_mm_per_hour:
            raise ValueError("rainfall series cannot be empty")
        if any(value < 0 for value in values_mm_per_hour):
            raise ValueError("rainfall cannot be negative")
        duration = step_minutes / 60
        return [
            RainfallStep(
                time=start + timedelta(minutes=(index + 1) * step_minutes),
                rainfall_mm=value * duration,
                duration_hours=duration,
            )
            for index, value in enumerate(values_mm_per_hour)
        ]
