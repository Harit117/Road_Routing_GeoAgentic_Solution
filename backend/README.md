# Backend: flood simulation skeleton

FastAPI service that loads the road network from `girlgeeks/data/processed`,
runs rainfall simulations, and serves a map viewer. The routing-facing
`/api/flood-risk` service now uses a scenario-based relative road-risk model;
the general `/api/simulation` model registry and `/api/route` remain available
for existing demos and integration work.

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

For flood-risk API responses, `current_flood_loading` and `threshold` are
normalized model quantities, while `risk_score` is the clamped ratio of those
quantities. The legacy `loading` field aliases `risk_score`, so 1.0 means the
road-specific threshold was reached. None of these values is a water depth.

Status bands (`simulation/engine.py`): safe < 0.5 ≤ watch < 0.8 ≤ risky < 1.0 ≤ flooded.

## Where each member plugs in

| Task | Where |
| --- | --- |
| Road flood-risk model | `app/flood/` contains susceptibility, rainfall providers, normalized bucket dynamics, and risk progression. `app/simulation/flood_risk_service.py` adapts it to the established Member 3 API. |
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
| GET | `/health`, `/api/health` | Service health |
| GET | `/api/flood-risk/model-status` | Model status, prototype parameters, calibration/live-feed limitations |
| GET | `/api/flood-risk/roads/{road_id}` | Active-input state; optional `?scenario=heavy` for historical forcing |
| POST | `/api/flood-risk/roads:batch` | Active-input states, or selected scenario with `{"road_ids":[...],"scenario":"heavy"}` |
| POST | `/api/flood-risk/simulate` | Isolated historical `scenario`, existing `preset`, or manual hourly rainfall input |
| GET | `/api/missions` | Mission profiles (medical, rescue, evacuation) |
| POST | `/api/route` | 501 until routing is implemented |

### Routing handoff: Flood & Risk Engineer (Member 2) → Routing Engineer (Member 3)

The `/api/flood-risk` endpoints preserve the routing integration paths and core
response fields while adding susceptibility, road-specific threshold, current
normalized loading, clamped risk score/level, and threshold timing. `loading`
continues as a routing-compatible alias for `risk_score`; legacy `status` values
remain `safe`, `watch`, `risky`, or `flooded`. `time_to_threshold_minutes` is
retained, and `time_to_threshold_hours` is also returned. Either timing field is
null when the selected rainfall series did not reach the road threshold.

Fetch selected current road states in one call:

```http
POST /api/flood-risk/roads:batch
Content-Type: application/json

{"road_ids": ["osm_299880378_313444440_0", "osm_299880378_313444440_1"]}
```

Response shape:

```json
{
  "states": [
    {
      "road_id": "osm_299880378_313444440_0",
      "status": "safe",
      "loading": 0.0,
      "susceptibility": 0.42,
      "threshold": 0.58,
      "current_flood_loading": 0.0,
      "risk_score": 0.0,
      "risk_level": "LOW",
      "threshold_reached": false,
      "elapsed_hours": 0.0,
      "time_to_threshold_hours": null,
      "rainfall_mm_per_h": 0.0,
      "cumulative_rain_mm": 0.0,
      "observed_at": "2026-10-03T12:00:00",
      "time_to_threshold_minutes": null,
      "source": "preset:intensifying_storm"
    }
  ],
  "unknown_road_ids": ["osm_299880378_313444440_1"],
  "observed_at": "2026-10-03T12:00:00",
  "scenario": null,
  "model_status": "scenario_based_prototype"
}
```

Run an isolated historical or caller-supplied scenario without changing the
active simulation used by the map or current-state endpoints:

```http
POST /api/flood-risk/simulate
Content-Type: application/json

{"scenario": "heavy"}
```

The response contains `model_status`, `model_name`, source and scenario timing,
and one final road state per road. `scenario` accepts `normal`, `moderate`,
`heavy`, or `extreme`. Existing `preset` and `rainfall_mm_per_h` request forms
remain supported. Single-road lookup optionally accepts the same scenario as a
query parameter. Batch requests can include a scenario and continue to report
unknown IDs in `unknown_road_ids`.

The schema is defined in `app/api/schemas.py`; calculations are isolated in
`app/flood/` and the API adapter in `app/simulation/flood_risk_service.py`.

## Scenario-based road flood risk

The `RiskEngine` combines historical inundation evidence from
`road_flood_point_links.csv` and hazard evidence from `road_hazard_links.csv`.
Depth is normalized to the deepest linked depth in the loaded network; hazard
rank is normalized to the OpenCity rank maximum. By default susceptibility is
`0.60 * normalized_depth + 0.40 * normalized_hazard`, with either weight
configurable. A road without a linked observation receives zero evidence for
that component; no depth/category is invented.

For susceptibility `S_i`, the normalized threshold is `B_i = B_MAX * (1-S_i)`.
Each hourly rainfall amount is normalized by a configurable 40.2 mm reference,
then multiplied by `BASE_FILL_RATE + SUSCEPTIBILITY_GAIN * S_i`. Defaults are
`B_MAX=1`, base fill `0.20`, and susceptibility gain `0.80`. These are
transparent prototype parameters, not physically calibrated runoff constants.
The bucket is capped at `B_MAX`; risk is `min(1, F_i/B_i)`. A zero threshold is
handled as immediately reached with a critical score, without division by zero.
Risk labels are application labels, not official flood classifications.

Parameters can be overridden with `FLOOD_RISK_B_MAX`,
`FLOOD_RISK_BASE_FILL_RATE`, `FLOOD_RISK_SUSCEPTIBILITY_GAIN`,
`FLOOD_RISK_RAINFALL_REFERENCE_MM`, `FLOOD_RISK_DEPTH_WEIGHT`,
`FLOOD_RISK_HAZARD_WEIGHT`, `FLOOD_RISK_LOW_MAX`,
`FLOOD_RISK_MODERATE_MAX`, and `FLOOD_RISK_HIGH_MAX`.

The model estimates relative road risk and time-to-threshold under a selected
rainfall forcing. It does not predict exact water depth or exact flood onset and
does not implement physically calibrated hydrology. OpenCity historical flood
observations describe spatial susceptibility; the Velachery rainfall scenarios
provide temporal forcing. No live rainfall source is configured. Current-state
responses use the active simulation input (the startup demo preset by default)
and identify that source; historical scenario responses are explicitly
scenario-based rather than live conditions.

Generate the per-road hourly export with:

```bash
python girlgeeks/scripts/05_build_road_flood_risk.py
```

This writes `girlgeeks/data/processed/road_flood_risk_scenarios.csv` with one
final state row per road and scenario after consuming all 48 hourly rainfall
observations. The `hour` column is the elapsed scenario hour represented by the
final state; `time_to_threshold_hours` records the first crossing during the
full sequence, or is blank when the threshold was not reached.

## Data notes

- Road hazard = highest category among all hazard polygons the road crosses
  (from `road_hazard_links.csv`).
- Road flood depth = deepest recorded inundation within 50 m, read from
  `road_flood_point_links.csv` itself, because `flood_point_id` is not unique
  in the source points (IDs 24–30, 119 and 120 each name 2–3 different places).
- One simulation is held in memory per server process.
