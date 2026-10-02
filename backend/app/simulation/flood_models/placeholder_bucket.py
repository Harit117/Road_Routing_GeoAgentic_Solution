"""PLACEHOLDER bucket model so the pipeline runs end to end.

Every number here is a stand-in until the calibrated model replaces it:
capacity comes only from the hazard category, a recorded flood point nearby
shrinks it, and every bucket drains at a constant rate.
"""

from app.network.models import RoadNetwork
from app.simulation.flood_models.base import FloodModel

# Bucket capacity in "mm of rain" per hazard rank (0 = no hazard polygon).
CAPACITY_BY_HAZARD_RANK = {0: 220.0, 1: 180.0, 2: 130.0, 3: 90.0, 4: 60.0, 5: 40.0}
FLOOD_POINT_CAPACITY_FACTOR = 0.7  # historically inundated nearby -> smaller bucket
BRIDGE_CAPACITY_FACTOR = 5.0  # elevated decks rarely flood
DRAIN_MM_PER_H = 10.0


class PlaceholderBucketModel(FloodModel):
    name = "placeholder_bucket"
    description = (
        "Stand-in rules: capacity from hazard category and nearby flood "
        "points, constant drainage. Replace with the calibrated model."
    )

    def reset(self, network: RoadNetwork) -> None:
        self.capacity = []
        for road in network.roads:
            cap = CAPACITY_BY_HAZARD_RANK[road.hazard_rank]
            if road.flood_point_count:
                cap *= FLOOD_POINT_CAPACITY_FACTOR
            if road.is_bridge:
                cap *= BRIDGE_CAPACITY_FACTOR
            self.capacity.append(cap)
        self.water_mm = [0.0] * len(self.capacity)

    def step(self, rainfall_mm_per_h: float, dt_hours: float) -> list[float]:
        net = (rainfall_mm_per_h - DRAIN_MM_PER_H) * dt_hours
        self.water_mm = [max(0.0, w + net) for w in self.water_mm]
        return [w / c for w, c in zip(self.water_mm, self.capacity)]
