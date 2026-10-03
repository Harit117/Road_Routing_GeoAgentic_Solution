"""Explicit prototype parameters for the normalized road-risk model.

These values are configurable modeling choices, not scientifically calibrated
hydrological constants.
"""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class RiskModelConfig:
    b_max: float = 1.0
    base_fill_rate: float = 0.20
    susceptibility_gain: float = 0.80
    rainfall_reference_mm: float = 40.2
    depth_weight: float = 0.60
    hazard_weight: float = 0.40
    low_risk_max: float = 0.25
    moderate_risk_max: float = 0.50
    high_risk_max: float = 0.75

    def __post_init__(self) -> None:
        if self.b_max <= 0:
            raise ValueError("b_max must be positive")
        if self.rainfall_reference_mm <= 0:
            raise ValueError("rainfall_reference_mm must be positive")
        if self.base_fill_rate < 0 or self.susceptibility_gain < 0:
            raise ValueError("fill rates cannot be negative")
        if self.depth_weight < 0 or self.hazard_weight < 0:
            raise ValueError("susceptibility weights cannot be negative")
        if self.depth_weight + self.hazard_weight <= 0:
            raise ValueError("at least one susceptibility weight must be positive")
        if not (
            0 <= self.low_risk_max <= self.moderate_risk_max
            <= self.high_risk_max <= 1
        ):
            raise ValueError("risk band thresholds must be ordered within [0, 1]")

    @classmethod
    def from_environment(cls) -> "RiskModelConfig":
        """Load optional FLOOD_RISK_* overrides; defaults are prototype values."""
        defaults = cls()
        return cls(
            b_max=float(os.getenv("FLOOD_RISK_B_MAX", defaults.b_max)),
            base_fill_rate=float(
                os.getenv("FLOOD_RISK_BASE_FILL_RATE", defaults.base_fill_rate)
            ),
            susceptibility_gain=float(
                os.getenv("FLOOD_RISK_SUSCEPTIBILITY_GAIN", defaults.susceptibility_gain)
            ),
            rainfall_reference_mm=float(
                os.getenv(
                    "FLOOD_RISK_RAINFALL_REFERENCE_MM",
                    defaults.rainfall_reference_mm,
                )
            ),
            depth_weight=float(
                os.getenv("FLOOD_RISK_DEPTH_WEIGHT", defaults.depth_weight)
            ),
            hazard_weight=float(
                os.getenv("FLOOD_RISK_HAZARD_WEIGHT", defaults.hazard_weight)
            ),
            low_risk_max=float(
                os.getenv("FLOOD_RISK_LOW_MAX", defaults.low_risk_max)
            ),
            moderate_risk_max=float(
                os.getenv("FLOOD_RISK_MODERATE_MAX", defaults.moderate_risk_max)
            ),
            high_risk_max=float(
                os.getenv("FLOOD_RISK_HIGH_MAX", defaults.high_risk_max)
            ),
        )
