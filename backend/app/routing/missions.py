"""Mission profiles: where a trip goes and how much flood risk it tolerates.

Edge cost = travel_minutes * (1 + flood_penalty_weight * loading^2), and any
road whose loading reaches max_loading by the time the vehicle gets there is
treated as closed. PLACEHOLDER values until tuned against the real model.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MissionProfile:
    id: str
    label: str
    facility_type: str  # which facilities this mission can end at
    vehicle: str
    flood_penalty_weight: float  # lambda: how strongly wet roads are avoided
    max_loading: float  # roads at or above this loading are impassable


MISSIONS: dict[str, MissionProfile] = {
    m.id: m
    for m in [
        # An ambulance accepts some wet road to save time on a critical patient.
        MissionProfile("medical", "Medical emergency", "hospital", "ambulance", 4.0, 0.8),
        # A loaded evacuation bus is cautious: it avoids water earlier and harder.
        MissionProfile("evacuation", "Evacuation", "relief_centre", "bus", 8.0, 0.6),
    ]
}
