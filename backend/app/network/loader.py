"""Load Member 1's processed files into a RoadNetwork.

Reads only plain GeoJSON/CSV, so the API needs no GIS libraries at runtime.
Joins are done here from the link tables rather than from
*_roads_with_flood_context.geojson, whose name/highway fields mix lists and
stringified lists.
"""

import csv
import json
from pathlib import Path

import networkx as nx

from app.config import Settings
from app.network.models import HAZARD_RANK, Road, RoadNetwork


def _as_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return " / ".join(str(v) for v in value)
    return str(value)


def _first(value, default: str) -> str:
    if isinstance(value, list):
        return str(value[0]) if value else default
    return str(value) if value else default


def _bbox_of(coords) -> tuple[float, float, float, float]:
    xs, ys = [], []

    def walk(c):
        if isinstance(c[0], (int, float)):
            xs.append(c[0])
            ys.append(c[1])
        else:
            for part in c:
                walk(part)

    walk(coords)
    return min(xs), min(ys), max(xs), max(ys)


def _intersects(a, b) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def _drop_z(coords):
    if isinstance(coords[0], (int, float)):
        return coords[:2]
    return [_drop_z(c) for c in coords]


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_network(settings: Settings) -> RoadNetwork:
    data = settings.data_dir
    region = settings.region

    roads: list[Road] = []
    for feature in _read_json(data / f"{region}_roads.geojson")["features"]:
        p = feature["properties"]
        roads.append(
            Road(
                index=len(roads),
                road_id=p["road_id"],
                u=int(p["u"]),
                v=int(p["v"]),
                key=int(p["key"]),
                name=_as_text(p.get("name")),
                highway=_first(p.get("highway"), "unclassified"),
                oneway=bool(p.get("oneway")),
                is_bridge=p.get("bridge") not in (None, False, "no"),
                is_tunnel=p.get("tunnel") not in (None, False, "no"),
                length_m=float(p["length_m"]),
                coords=[tuple(c[:2]) for c in feature["geometry"]["coordinates"]],
            )
        )
    by_id = {r.road_id: r for r in roads}

    nodes = {
        int(f["properties"]["node_id"]): (f["properties"]["x"], f["properties"]["y"])
        for f in _read_json(data / f"{region}_road_nodes.geojson")["features"]
    }

    # Hazard: keep the highest category among all polygons a road crosses.
    for row in _read_csv(data / "road_hazard_links.csv"):
        road = by_id.get(row["road_id"])
        if road is None:
            continue
        road.hazard_zone_count += 1
        rank = HAZARD_RANK.get(row["hazard_category"], 0)
        if rank > road.hazard_rank:
            road.hazard_rank = rank
            road.hazard_category = row["hazard_category"]

    # Flood points: keep the deepest recorded inundation within 50 m. Depth is
    # taken from the link row itself because flood_point_id is not unique in
    # the source data.
    for row in _read_csv(data / "road_flood_point_links.csv"):
        road = by_id.get(row["road_id"])
        if road is None:
            continue
        road.flood_point_count += 1
        depth = float(row["depth_cm"])
        if road.flood_depth_cm is None or depth > road.flood_depth_cm:
            road.flood_depth_cm = depth

    xs = [lon for lon, _ in nodes.values()]
    ys = [lat for _, lat in nodes.values()]
    bbox = (min(xs), min(ys), max(xs), max(ys))

    # Chennai-wide layers, clipped to the road network's extent for the map.
    flood_points = [
        {
            "flood_point_id": row["flood_point_id"],
            "depth_cm": float(row["depth_cm"]),
            "remarks": row["remarks"].strip() or None,
            "lon": float(row["longitude"]),
            "lat": float(row["latitude"]),
        }
        for row in _read_csv(data / "chennai_flood_points.csv")
        if bbox[0] <= float(row["longitude"]) <= bbox[2]
        and bbox[1] <= float(row["latitude"]) <= bbox[3]
    ]
    hazard_zones = []
    for f in _read_json(data / "chennai_flood_hazard.geojson")["features"]:
        geom = f["geometry"]
        if geom and _intersects(_bbox_of(geom["coordinates"]), bbox):
            hazard_zones.append(
                {
                    "type": "Feature",
                    "properties": f["properties"],
                    "geometry": {
                        "type": geom["type"],
                        "coordinates": _drop_z(geom["coordinates"]),
                    },
                }
            )

    graph = nx.MultiDiGraph()
    for node_id, (lon, lat) in nodes.items():
        graph.add_node(node_id, x=lon, y=lat)
    for r in roads:
        graph.add_edge(r.u, r.v, key=r.key, road_index=r.index, length_m=r.length_m)

    return RoadNetwork(
        region=region,
        roads=roads,
        nodes=nodes,
        bbox=bbox,
        flood_points=flood_points,
        hazard_zones=hazard_zones,
        graph=graph,
        by_id=by_id,
    )
