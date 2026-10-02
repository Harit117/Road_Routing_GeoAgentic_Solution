"""Convert the raw OpenCity flood KML files into clean GeoJSON layers.

This script intentionally preserves source facts only. It does not assign a
flood-risk score; that is the Flood & Risk Engineer's responsibility.
"""

from pathlib import Path

import geopandas as gpd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "open_city"
OUTPUT_DIR = PROJECT_ROOT / "data" / "processed"

POINTS_FILE = RAW_DIR / "inindationpoints.kml"
HAZARDS_FILE = RAW_DIR / "floodhazarmap.kml"


def convert_points() -> gpd.GeoDataFrame:
    """Read inundation points and retain the fields useful to the team."""
    points = gpd.read_file(POINTS_FILE).to_crs("EPSG:4326")

    cleaned = points[
        ["F_ID", "DEPTH", "ZONE", "WARD", "F_REMARKS", "geometry"]
    ].copy()
    cleaned = cleaned.rename(
        columns={
            "F_ID": "flood_point_id",
            "DEPTH": "depth_inches",
            "ZONE": "zone",
            "WARD": "ward",
            "F_REMARKS": "remarks",
        }
    )
    fallback_ids = cleaned.index.to_series(index=cleaned.index).astype(str)
    cleaned["flood_point_id"] = cleaned["flood_point_id"].astype("string").fillna(fallback_ids).astype(str)
    cleaned["depth_inches"] = cleaned["depth_inches"].astype(float)
    cleaned["depth_cm"] = (cleaned["depth_inches"] * 2.54).round(2)
    cleaned["latitude"] = cleaned.geometry.y.round(7)
    cleaned["longitude"] = cleaned.geometry.x.round(7)
    return cleaned


def convert_hazards() -> gpd.GeoDataFrame:
    """Read hazard polygons and retain the official category supplied in KML."""
    hazards = gpd.read_file(HAZARDS_FILE).to_crs("EPSG:4326")

    cleaned = hazards[["OBJECTID", "CATEGORY", "geometry"]].copy()
    cleaned = cleaned.rename(
        columns={"OBJECTID": "hazard_id", "CATEGORY": "hazard_category"}
    )
    fallback_ids = cleaned.index.to_series(index=cleaned.index).astype(str)
    cleaned["hazard_id"] = cleaned["hazard_id"].astype("string").fillna(fallback_ids).astype(str)
    cleaned["hazard_category"] = cleaned["hazard_category"].str.strip()
    return cleaned


def main() -> None:
    if not POINTS_FILE.exists() or not HAZARDS_FILE.exists():
        raise FileNotFoundError(
            "Expected raw KML files are missing. Check data/raw/open_city/."
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    points = convert_points()
    hazards = convert_hazards()

    points.to_file(OUTPUT_DIR / "chennai_flood_points.geojson", driver="GeoJSON")
    hazards.to_file(OUTPUT_DIR / "chennai_flood_hazard.geojson", driver="GeoJSON")
    points.drop(columns="geometry").to_csv(
        OUTPUT_DIR / "chennai_flood_points.csv", index=False
    )

    print(f"Created {len(points)} flood points")
    print(f"Created {len(hazards)} hazard polygons")
    print("Hazard categories:", ", ".join(sorted(hazards.hazard_category.dropna().unique())))
    print("Outputs written to data/processed/")


if __name__ == "__main__":
    main()
