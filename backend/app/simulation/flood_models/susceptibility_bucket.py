"""Road flood model built on the Flood & Risk engineer's rules in app/flood/.

Per road:
  susceptibility = weighted recorded inundation depth + hazard category (0..1)
  threshold      = B_MAX * (1 - susceptibility)   (flood-prone roads: smaller bucket)
  bucket        += rain_mm / reference * (base_fill + gain * susceptibility), capped at B_MAX

The engine's loading is bucket / threshold, so 1.0 means the road-specific
threshold is reached, the same meaning as risk_score in /api/flood-risk.
Coefficients come from RiskModelConfig (FLOOD_RISK_* env overrides).
"""

from app.flood.bucket_model import BucketModel
from app.flood.config import RiskModelConfig
from app.flood.models import SusceptibilityEvidence
from app.flood.susceptibility import SusceptibilityCalculator
from app.network.models import RoadNetwork
from app.simulation.flood_models.base import FloodModel


class SusceptibilityBucketModel(FloodModel):
    name = "susceptibility_bucket"
    description = (
        "Historical susceptibility (recorded flood depth + hazard category) sets "
        "each road's threshold; normalized rainfall fills its bucket (app/flood)."
    )

    def __init__(self, config: RiskModelConfig | None = None):
        self.config = config or RiskModelConfig.from_environment()
        self.bucket = BucketModel(self.config)

    def reset(self, network: RoadNetwork) -> None:
        scores = SusceptibilityCalculator(self.config).calculate(
            SusceptibilityEvidence(r.road_id, r.flood_depth_cm, r.hazard_rank)
            for r in network.roads
        )
        self.susceptibility = [scores[r.road_id] for r in network.roads]
        self.threshold = [self.config.b_max * (1.0 - s) for s in self.susceptibility]
        self.water = [0.0] * len(self.susceptibility)

    def step(self, rainfall_mm_per_h: float, dt_hours: float) -> list[float]:
        rain_mm = rainfall_mm_per_h * dt_hours
        self.water = [
            self.bucket.advance(w, rain_mm, s) for w, s in zip(self.water, self.susceptibility)
        ]
        return [self._loading(w, t) for w, t in zip(self.water, self.threshold)]

    @staticmethod
    def _loading(water: float, threshold: float) -> float:
        if threshold <= 0:  # fully susceptible road: any water reaches the threshold
            return 1.0 if water > 0 else 0.0
        return water / threshold
