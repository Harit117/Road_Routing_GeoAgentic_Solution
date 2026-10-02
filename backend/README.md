# Backend: flood simulation skeleton

FastAPI service that loads the road network from `girlgeeks/data/processed`,
runs a tick-by-tick rainfall simulation over every road, and serves a map
viewer. Flood-model rules and routing are deliberately placeholders.

## Run

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

- Map viewer: http://localhost:8000/
- API docs: http://localhost:8000/docs
- Tests: `pytest`

## How it fits together

```
girlgeeks/data/processed  ──>  network/loader.py   ──>  RoadNetwork (roads + static flood context + graph)
                                                              │
rainfall (mm/h per tick)  ──>  simulation/engine.py ──>  FloodModel.step()  ──>  loading per road, per tick
                                                              │
                                                       api/*  ──>  static/ map viewer
                                                              │
                                                       routing/ (stub: mission profiles only)
```

**Loading** is the bucket fill level of a road: 0 = dry, 1 = flood threshold
reached. It is relative, not a water depth. The engine records, for every
road, the first tick it reached 1 (`onset_tick`): that ordering is what
routing will consume.

Status bands (`simulation/engine.py`): safe < 0.5 ≤ watch < 0.8 ≤ risky < 1.0 ≤ flooded.

## Where each member plugs in

| Task | Where |
| --- | --- |
| Real flood model | Subclass `FloodModel` in `app/simulation/flood_models/`, register it in `flood_models/__init__.py`. Choose it with `"model": "<name>"` when creating a simulation. `placeholder_bucket.py` shows the contract. |
| Open-Meteo rainfall | Produce a `RainfallSeries` (`app/simulation/rainfall.py`); the hourly `precipitation` array maps 1:1 onto ticks. |
| Routing (A\*) | `app/routing/`: `network.graph` is a `networkx.MultiDiGraph` whose edges carry `road_index`; look up `simulation.frames[t].loading[road_index]` for the current flood state. Implement `POST /api/route`. Mission profiles are in `routing/missions.py`. |
| Whole of Chennai | Regenerate data with `girlgeeks/scripts/02_download_roads.py` for a Chennai bbox, saving files as `chennai_roads.geojson` / `chennai_road_nodes.geojson`, then run with `FLOOD_REGION=chennai`. |

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/network/summary` | Counts, bbox, roads per hazard category |
| GET | `/api/network/roads` | Road GeoJSON; property `i` indexes the loading arrays |
| GET | `/api/network/roads/{road_id}` | Static context + loading history + onset tick |
| GET | `/api/network/hazard-zones` | Hazard polygons clipped to the network area |
| GET | `/api/network/flood-points` | Recorded inundation points in the area |
| GET | `/api/simulation/models`, `/presets` | Available flood models and rainfall presets |
| POST | `/api/simulation` | New simulation: `{"preset": "cloudburst"}` or `{"rainfall_mm_per_h": [5, 8, 20]}`, optional `model`, `start_time` |
| GET | `/api/simulation` | Current tick, rainfall, per-tick status counts |
| POST | `/api/simulation/step?n=1`, `/run`, `/reset` | Advance or rewind |
| GET | `/api/simulation/frames/{tick}` | Loading of every road at a tick |
| GET | `/api/simulation/onset` | Roads in the order they reached the flood threshold |
| GET | `/api/missions` | Mission profiles (medical, rescue, evacuation) |
| POST | `/api/route` | 501 until routing is implemented |

## Data notes

- Road hazard = highest category among all hazard polygons the road crosses
  (from `road_hazard_links.csv`).
- Road flood depth = deepest recorded inundation within 50 m, read from
  `road_flood_point_links.csv` itself, because `flood_point_id` is not unique
  in the source points (IDs 24–30, 119 and 120 each name 2–3 different places).
- One simulation is held in memory per server process.
