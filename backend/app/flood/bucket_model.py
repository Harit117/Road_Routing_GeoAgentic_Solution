"""Normalized bucket dynamics; units are model quantities, never water depth."""

from app.flood.config import RiskModelConfig


class BucketModel:
    """Apply transparent rainfall normalization and per-road susceptibility.

    Rainfall is divided by a configurable reference in millimeters. The base
    fill and susceptibility gain are prototype coefficients with no physical
    runoff interpretation. Each bucket is capped at B_MAX.
    """

    def __init__(self, config: RiskModelConfig):
        self.config = config

    def normalize_rainfall(self, rainfall_mm: float) -> float:
        if rainfall_mm < 0:
            raise ValueError("rainfall cannot be negative")
        return rainfall_mm / self.config.rainfall_reference_mm

    def advance(
        self,
        current_loading: float,
        rainfall_mm: float,
        susceptibility: float,
    ) -> float:
        if not 0 <= susceptibility <= 1:
            raise ValueError("susceptibility must be within [0, 1]")
        normalized_rain = self.normalize_rainfall(rainfall_mm)
        modifier = (
            self.config.base_fill_rate
            + self.config.susceptibility_gain * susceptibility
        )
        return min(
            self.config.b_max,
            max(0.0, current_loading)
            + normalized_rain * modifier,
        )
