"""Road susceptibility from linked historical inundation and hazard evidence."""

from collections.abc import Iterable

from app.flood.config import RiskModelConfig
from app.flood.models import SusceptibilityEvidence


class SusceptibilityCalculator:
    """Compute a configurable 0..1 evidence score for each road.

    Depth is normalized by the largest linked recorded depth in the loaded
    network. Hazard category rank is normalized by the OpenCity rank maximum
    (5). A missing road-level observation contributes zero evidence rather
    than a fabricated depth or category.
    """

    def __init__(self, config: RiskModelConfig):
        self.config = config

    def calculate(
        self, evidence: Iterable[SusceptibilityEvidence]
    ) -> dict[str, float]:
        rows = list(evidence)
        max_depth = max(
            (row.flood_depth_cm for row in rows if row.flood_depth_cm is not None),
            default=0.0,
        )
        result: dict[str, float] = {}
        for row in rows:
            depth_score = (
                min(1.0, max(0.0, row.flood_depth_cm / max_depth))
                if row.flood_depth_cm is not None and max_depth > 0
                else 0.0
            )
            hazard_score = min(1.0, max(0.0, row.hazard_rank / 5.0))
            score = (
                self.config.depth_weight * depth_score
                + self.config.hazard_weight * hazard_score
            ) / (self.config.depth_weight + self.config.hazard_weight)
            result[row.road_id] = min(1.0, max(0.0, score))
        return result
