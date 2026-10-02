"""Mission profiles: what a route is for, and how much flood risk it tolerates.

Routing is not implemented yet. These profiles fix the shape A* will consume:
edge cost = travel_time + flood_penalty_weight * flood_risk, and edges whose
loading exceeds max_loading are treated as closed.
PLACEHOLDER values until the routing member tunes them.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MissionProfile:
    id: str
    label: str
    destination_type: str  # "hospital", "relief_centre", ...
    vehicle: str
    flood_penalty_weight: float  # the lambda in the cost function
    max_loading: float  # roads above this loading are impassable for this vehicle


MISSIONS: dict[str, MissionProfile] = {
    m.id: m
    for m in [
        MissionProfile("medical", "Medical emergency", "hospital", "ambulance", 5.0, 0.8),
        MissionProfile("rescue", "Rescue operation", "relief_centre", "rescue_truck", 2.0, 1.2),
        MissionProfile("evacuation", "Evacuation", "relief_centre", "bus", 8.0, 0.6),
    ]
}
