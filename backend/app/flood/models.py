"""Data records shared by rainfall, susceptibility, bucket, and risk layers."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


RiskLevel = Literal["LOW", "MODERATE", "HIGH", "VERY_HIGH", "CRITICAL"]


@dataclass(frozen=True)
class RainfallStep:
    time: datetime
    rainfall_mm: float
    duration_hours: float = 1.0


@dataclass(frozen=True)
class RoadRiskState:
    road_id: str
    scenario: str | None
    susceptibility: float
    threshold: float
    current_flood_loading: float
    risk_score: float
    risk_level: RiskLevel
    threshold_reached: bool
    time_to_threshold_hours: float | None
    elapsed_hours: float
    rainfall_mm: float
    cumulative_rain_mm: float
    observed_at: datetime
    source: str


@dataclass(frozen=True)
class SusceptibilityEvidence:
    road_id: str
    flood_depth_cm: float | None
    hazard_rank: int


@dataclass(frozen=True)
class RiskFrame:
    elapsed_hours: float
    rainfall_mm: float
    cumulative_rain_mm: float
    observed_at: datetime
    states: list[RoadRiskState]
