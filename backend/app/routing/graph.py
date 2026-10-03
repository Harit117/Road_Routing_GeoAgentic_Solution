"""Routing view of the road network: adjacency, travel times and snapping."""

from dataclasses import dataclass

from app.network.models import RoadNetwork
from app.routing.geo import project_on_line

# Assumed emergency-vehicle speeds in congested urban traffic (km/h).
# PLACEHOLDER: OSM maxspeed is almost never tagged in Velachery.
SPEED_KMH = {
    "primary": 40,
    "primary_link": 30,
    "secondary": 35,
    "secondary_link": 30,
    "tertiary": 30,
    "tertiary_link": 25,
    "residential": 20,
    "unclassified": 20,
    "road": 20,
    "living_street": 10,
}
DEFAULT_SPEED_KMH = 20
MAX_SNAP_DISTANCE_M = 250


@dataclass(frozen=True)
class Snap:
    road_index: int
    segment_index: int
    point: tuple[float, float]  # (lon, lat) on the road
    fraction: float  # 0 = at road.u, 1 = at road.v
    distance_m: float  # from the clicked point


class RoutingGraph:
    def __init__(self, network: RoadNetwork):
        self.network = network
        roads = network.roads
        self.travel_min = [
            r.length_m / (SPEED_KMH.get(r.highway, DEFAULT_SPEED_KMH) * 1000 / 60)
            for r in roads
        ]
        # Fastest possible metres per minute: keeps the A* heuristic admissible.
        self.max_speed_m_per_min = max(SPEED_KMH.values()) * 1000 / 60
        self.out: dict[int, list[int]] = {n: [] for n in network.nodes}
        for r in roads:
            self.out[r.u].append(r.index)
        # The opposite-direction twin of a two-way road (same geometry reversed).
        self.reverse: dict[int, int] = {}
        by_ends = {}
        for r in roads:
            by_ends.setdefault((r.u, r.v), []).append(r)
        for r in roads:
            for twin in by_ends.get((r.v, r.u), []):
                if twin.coords == r.coords[::-1]:
                    self.reverse[r.index] = twin.index
        pad = 0.003  # ~300 m: cheap bounding-box prefilter for snapping
        self._boxes = [
            (
                min(c[0] for c in r.coords) - pad,
                min(c[1] for c in r.coords) - pad,
                max(c[0] for c in r.coords) + pad,
                max(c[1] for c in r.coords) + pad,
            )
            for r in roads
        ]

    def snap(self, lon: float, lat: float, road_index: int | None = None) -> Snap | None:
        """Nearest point on the network, or on one given road (a moving
        vehicle knows which road it is on, so it must not jump to a neighbour)."""
        if road_index is not None:
            d, seg, point, frac = project_on_line((lon, lat), self.network.roads[road_index].coords)
            return Snap(road_index, seg, point, frac, d)
        best = None
        for r, (x0, y0, x1, y1) in zip(self.network.roads, self._boxes):
            if not (x0 <= lon <= x1 and y0 <= lat <= y1):
                continue
            d, seg, point, frac = project_on_line((lon, lat), r.coords)
            if best is None or d < best.distance_m:
                best = Snap(r.index, seg, point, frac, d)
        if best is None or best.distance_m > MAX_SNAP_DISTANCE_M:
            return None
        return best
