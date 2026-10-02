"""Download a directed OpenStreetMap road graph for the evacuation demo area."""

from pathlib import Path

import osmnx as ox


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "data" / "processed"

# Default MVP area: Velachery, Chennai. Change these four values if the team
# later selects a different area. OSMnx expects (west, south, east, north).
WEST, SOUTH, EAST, NORTH = 80.1980, 12.9640, 80.2380, 13.0000


def ensure_column(frame, column: str, default: object = None) -> None:
    """Add a column when OpenStreetMap has no tag of that type in this area."""
    if column not in frame.columns:
        frame[column] = default


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    bbox = (WEST, SOUTH, EAST, NORTH)

    # A directed graph preserves intersections and legal one-way travel.
    graph = ox.graph_from_bbox(
        bbox=bbox,
        network_type="drive",
        simplify=True,
        retain_all=True,
    )
    ox.save_graphml(graph, OUTPUT_DIR / "velachery_roads.graphml")

    nodes, edges = ox.graph_to_gdfs(graph, nodes=True, edges=True)
    edges = edges.reset_index()  # exposes graph columns: u, v, key

    for column, default in {
        "name": None,
        "highway": None,
        "oneway": False,
        "bridge": False,
        "tunnel": False,
        "length": None,
    }.items():
        ensure_column(edges, column, default)

    edges["road_id"] = edges.apply(
        lambda row: f"osm_{row['u']}_{row['v']}_{row['key']}", axis=1
    )
    roads = edges.rename(columns={"length": "length_m"})[
        [
            "road_id",
            "u",
            "v",
            "key",
            "name",
            "highway",
            "oneway",
            "bridge",
            "tunnel",
            "length_m",
            "geometry",
        ]
    ].to_crs("EPSG:4326")

    nodes = nodes.reset_index().rename(columns={"osmid": "node_id"}).to_crs("EPSG:4326")
    roads.to_file(OUTPUT_DIR / "velachery_roads.geojson", driver="GeoJSON")
    nodes[["node_id", "x", "y", "geometry"]].to_file(
        OUTPUT_DIR / "velachery_road_nodes.geojson", driver="GeoJSON"
    )

    print(f"Created {len(roads)} directed road segments")
    print(f"Created {len(nodes)} road-intersection nodes")
    print("Outputs written to data/processed/")


if __name__ == "__main__":
    main()
