"""In-memory representation of the road network and its static flood context."""

from dataclasses import dataclass, field

import networkx as nx

# Official OpenCity hazard categories, lowest to highest. 0 = no hazard polygon.
HAZARD_RANK = {"Very Low": 1, "Low": 2, "Moderate": 3, "High": 4, "Very High": 5}


@dataclass(slots=True)
class Road:
    """One directed OSM edge (u -> v). Two-way streets appear twice."""

    index: int  # position in RoadNetwork.roads; simulation arrays use it
    road_id: str
    u: int
    v: int
    key: int
    name: str | None
    highway: str
    oneway: bool
    is_bridge: bool
    is_tunnel: bool
    length_m: float
    coords: list[tuple[float, float]]  # (lon, lat)
    # Static flood context from the data layer
    hazard_category: str | None = None  # highest category the road crosses
    hazard_rank: int = 0
    hazard_zone_count: int = 0
    flood_depth_cm: float | None = None  # deepest recorded inundation within 50 m
    flood_point_count: int = 0


@dataclass(eq=False)  # hashed by identity so API payloads can be cached per network
class RoadNetwork:
    region: str
    roads: list[Road]
    nodes: dict[int, tuple[float, float]]  # node_id -> (lon, lat)
    bbox: tuple[float, float, float, float]  # west, south, east, north
    flood_points: list[dict] = field(default_factory=list)
    hazard_zones: list[dict] = field(default_factory=list)  # GeoJSON features
    graph: nx.MultiDiGraph = field(default_factory=nx.MultiDiGraph)
    by_id: dict[str, Road] = field(default_factory=dict)
