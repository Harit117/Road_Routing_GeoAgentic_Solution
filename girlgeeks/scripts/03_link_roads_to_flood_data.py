"""Create road-to-flood relationship files for the risk and routing modules."""

from pathlib import Path

import geopandas as gpd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
METRIC_CRS = "EPSG:32644"  # UTM zone 44N: distances are measured in metres.
FLOOD_POINT_RADIUS_M = 50


def main() -> None:
    roads = gpd.read_file(PROCESSED_DIR / "velachery_roads.geojson")
    hazards = gpd.read_file(PROCESSED_DIR / "chennai_flood_hazard.geojson")
    points = gpd.read_file(PROCESSED_DIR / "chennai_flood_points.geojson")

    roads_m = roads.to_crs(METRIC_CRS)
    hazards_m = hazards.to_crs(METRIC_CRS)
    points_m = points.to_crs(METRIC_CRS)

    # One road can intersect multiple hazard polygons. Preserve every source
    # relationship instead of assigning a risk score at this stage.
    hazard_links = gpd.sjoin(
        roads_m[["road_id", "geometry"]],
        hazards_m[["hazard_id", "hazard_category", "geometry"]],
        how="inner",
        predicate="intersects",
    ).drop(columns="geometry")
    hazard_links = hazard_links[["road_id", "hazard_id", "hazard_category"]].drop_duplicates()
    hazard_links.to_csv(PROCESSED_DIR / "road_hazard_links.csv", index=False)

    # A point is linked to every road segment whose 50 m buffer contains it.
    # Calculating in EPSG:32644 makes this an actual 50-metre distance.
    road_buffers = roads_m[["road_id", "geometry"]].copy()
    road_buffers["geometry"] = road_buffers.geometry.buffer(FLOOD_POINT_RADIUS_M)
    point_matches = gpd.sjoin(
        points_m,
        road_buffers,
        how="inner",
        predicate="within",
    )
    road_geometries = roads_m.geometry
    point_matches["distance_m"] = point_matches.apply(
        lambda row: row.geometry.distance(road_geometries.loc[row["index_right"]]),
        axis=1,
    ).round(2)
    point_links = point_matches[
        [
            "road_id",
            "flood_point_id",
            "distance_m",
            "depth_inches",
            "depth_cm",
            "zone",
            "ward",
        ]
    ].drop_duplicates()
    point_links.to_csv(PROCESSED_DIR / "road_flood_point_links.csv", index=False)

    # A convenience layer for the map. It contains raw contextual values, not
    # a final flood score: dynamic risk remains Member 2's responsibility.
    category_rank = {"Very Low": 1, "Low": 2, "Moderate": 3, "High": 4, "Very High": 5}
    highest_hazard = hazard_links.copy()
    highest_hazard["rank"] = highest_hazard["hazard_category"].map(category_rank).fillna(0)
    highest_hazard = (
        highest_hazard.sort_values("rank", ascending=False)
        .drop_duplicates("road_id")
        [["road_id", "hazard_category"]]
    )
    nearest_point = (
        point_links.sort_values("distance_m")
        .drop_duplicates("road_id")
        [["road_id", "distance_m", "depth_inches", "depth_cm"]]
        .rename(columns={"distance_m": "nearest_flood_point_distance_m"})
    )
    road_context = roads.merge(highest_hazard, on="road_id", how="left").merge(
        nearest_point, on="road_id", how="left"
    )
    road_context.to_file(
        PROCESSED_DIR / "velachery_roads_with_flood_context.geojson",
        driver="GeoJSON",
    )

    print(f"Created {len(hazard_links)} road-to-hazard links")
    print(f"Created {len(point_links)} road-to-flood-point links within {FLOOD_POINT_RADIUS_M} m")
    print("Outputs written to data/processed/")


if __name__ == "__main__":
    main()
