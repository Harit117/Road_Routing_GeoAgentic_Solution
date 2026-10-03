"""Destinations (hospitals, relief centres), each attached to a network node."""

import json
from dataclasses import dataclass
from pathlib import Path

from app.network.models import RoadNetwork


@dataclass(frozen=True)
class Facility:
    id: str
    type: str  # "hospital" | "relief_centre"
    name: str
    node_id: int
    lon: float
    lat: float
    road_indices: tuple[int, ...]  # roads touching the node: their loading = site flooding


def load_facilities(path: Path, network: RoadNetwork) -> dict[str, Facility]:
    with path.open(encoding="utf-8") as f:
        raw = json.load(f)["facilities"]
    touching: dict[int, list[int]] = {}
    for r in network.roads:
        touching.setdefault(r.u, []).append(r.index)
        touching.setdefault(r.v, []).append(r.index)
    facilities = {}
    for item in raw:
        node = int(item["node_id"])
        if node not in network.nodes:
            raise ValueError(f"facility {item['id']}: node {node} is not in the road network")
        lon, lat = network.nodes[node]
        facilities[item["id"]] = Facility(
            id=item["id"],
            type=item["type"],
            name=item["name"],
            node_id=node,
            lon=lon,
            lat=lat,
            road_indices=tuple(sorted(set(touching[node]))),
        )
    return facilities
