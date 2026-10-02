# Chennai Flood-Aware Evacuation Routing — Data Layer

## Purpose

This folder contains Member 1's geospatial inputs for a Velachery, Chennai MVP.
It supplies map context only; live rainfall and final flood-risk scores are
calculated by Member 2, while routing is calculated by Member 3.

## Source data

- `data/raw/open_city/inindationpoints.kml`: historical inundation points.
  `DEPTH` is supplied in inches.
- `data/raw/open_city/floodhazarmap.kml`: flood-hazard polygons supplied by
  OpenCity / Greater Chennai Corporation.
- OpenStreetMap: drivable road network for the Velachery demo area.

## Processed outputs

| File | What it contains | Intended user |
| --- | --- | --- |
| `chennai_flood_points.geojson` | 192 historical flood points, including `depth_inches` and `depth_cm` | Member 2 / map |
| `chennai_flood_hazard.geojson` | 7,453 hazard polygons with the official category | Member 2 / map |
| `velachery_roads.graphml` | Directed road-routing graph with intersections and one-way rules | Member 3 |
| `velachery_roads.geojson` | 8,616 directed road segments | Members 2, 3, and 5 |
| `road_hazard_links.csv` | Every road-to-hazard-polygon intersection | Member 2 |
| `road_flood_point_links.csv` | Road-to-inundation-point links within 50 m, including recorded depth | Member 2 |
| `velachery_roads_with_flood_context.geojson` | Map-ready roads with highest intersecting hazard category and nearest flood-point context | Member 5 |

## Assumptions

- All web-map outputs use EPSG:4326 (latitude/longitude).
- Distance joins use EPSG:32644, so the flood-point threshold is 50 metres.
- Hazard categories are preserved exactly as supplied: Very Low, Low, Moderate,
  High, and Very High.
- This data layer does **not** assign a final flood-risk score.

## Re-run scripts

```bash
source .venv/bin/activate
python scripts/01_convert_flood_data.py
python scripts/02_download_roads.py
python scripts/03_link_roads_to_flood_data.py
```
